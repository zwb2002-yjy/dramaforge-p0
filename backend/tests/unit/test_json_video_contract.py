"""Request-only JSON video contract; fixtures do not qualify a live server."""

from __future__ import annotations

import json
from uuid import UUID

import httpx
import pytest
from app.config import Settings
from app.providers.catalog_loader import ModelCatalogLoader
from app.providers.catalog_publication import catalog_new_create_blocker
from app.providers.compiled_options import (
    compiled_generation_evidence,
    uncompiled_requested_options,
)
from app.providers.intents import (
    ArtifactReferenceIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
    VideoOutputIntent,
)
from app.providers.manifest import ModelCapabilityManifest
from app.providers.openai_compatible_media import (
    OpenAICompatibleMediaClient,
    OpenAICompatibleMediaRuntime,
    OpenAICompatibleVideoCompiler,
    normalize_json_video_base_url,
)
from app.providers.registry import get_plugin
from app.providers.runtime import CompiledVideoRequest, ProviderResumeToken, ResolvedReference

PROFILE = "openai_json_video_v1"
CONTRACT = "@contract/json-video-t2v-v1"


def _manifest() -> ModelCapabilityManifest:
    raw = next(m.as_dict() for m in ModelCatalogLoader().load() if m.identity[2] == CONTRACT)
    assert raw["lifecycle"] == "preview" and raw["implementation_status"] == "documented"
    assert "output.media_conformance_unverified" in raw["documented_features"]
    return ModelCapabilityManifest.model_validate(raw)


def _intent(**output: object) -> VideoGenerationIntentV1:
    return VideoGenerationIntentV1(
        prompt="A ceramic cup stands on a plain table.",
        mode_id="text_to_video",
        output=VideoOutputIntent.model_validate(output),
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )


async def _compile(intent: VideoGenerationIntentV1, refs=None):
    return await OpenAICompatibleVideoCompiler(PROFILE).compile(
        intent, _manifest(), refs or [], invoke_model_value="configured-local-model"
    )


@pytest.mark.asyncio
async def test_request_compiles_only_captured_json_fields_with_visible_native_ratio() -> None:
    compiled = await _compile(
        _intent(duration_seconds=5, resolution="832x480", aspect_ratio="adaptive")
    )
    assert compiled.protocol_profile == PROFILE
    assert compiled.wire_request == {
        "model": "configured-local-model",
        "prompt": "A ceramic cup stands on a plain table.",
        "seconds": 5,
        "size": "832x480",
    }
    effective, transformations = compiled_generation_evidence(compiled)
    assert effective == {"duration_seconds": 5, "resolution": "832x480", "aspect_ratio": "26:15"}
    assert len(transformations) == 1
    assert transformations[0].from_value == "adaptive"
    assert transformations[0].to_value == "26:15"
    assert (
        uncompiled_requested_options(
            {"duration_seconds": 5, "resolution": "832x480", "aspect_ratio": "adaptive"},
            effective,
            transformations,
        )
        == []
    )
    assert compiled.reference_artifact_ids == []


@pytest.mark.asyncio
async def test_only_manifest_defaults_fill_missing_output() -> None:
    compiled = await _compile(_intent())
    assert compiled.wire_request["seconds"] == 5
    assert compiled.wire_request["size"] == "832x480"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options",
    [
        {"duration_seconds": 0},
        {"duration_seconds": 8},
        {"resolution": "720x1280"},
        {"aspect_ratio": "9:16"},
        {"aspect_ratio": "16:9"},
        {"seed": 0},
        {"generate_audio": False},
        {"generate_audio": True},
    ],
)
async def test_unimplemented_output_is_rejected_before_submission(options) -> None:
    with pytest.raises(ValueError):
        await _compile(_intent(**options))


@pytest.mark.asyncio
async def test_both_selected_and_extra_resolved_references_are_rejected() -> None:
    ref = ResolvedReference(
        artifact_id=UUID(int=1), role="first_frame", content_bytes=b"not-a-real-image"
    )
    selected = _intent()
    selected.references = [ArtifactReferenceIntent(artifact_id=ref.artifact_id, role=ref.role)]
    for intent, refs in ((selected, [ref]), (_intent(), [ref])):
        with pytest.raises(ValueError, match="reference"):
            await _compile(intent, refs)


@pytest.mark.asyncio
async def test_contract_revision_profile_and_mode_cannot_fall_back() -> None:
    compiler = OpenAICompatibleVideoCompiler(PROFILE)
    for changes in ({"model_revision": "unknown"}, {"protocol_profile": "openai_media_v1"}):
        with pytest.raises(ValueError):
            await compiler.compile(
                _intent(), _manifest().model_copy(update=changes), [], invoke_model_value="remote"
            )
    with pytest.raises(ValueError):
        await _compile(_intent().model_copy(update={"mode_id": "first_frame"}))
    with pytest.raises(ValueError):
        await OpenAICompatibleVideoCompiler().compile(
            _intent(), _manifest(), [], invoke_model_value="remote"
        )


def test_preview_cannot_become_a_production_contract_from_discovery() -> None:
    item = next(m for m in ModelCatalogLoader().load() if m.identity[2] == CONTRACT)
    assert (
        catalog_new_create_blocker(
            *item.identity,
            item.manifest_hash,
            lifecycle=item.publication_lifecycle,
            catalog_source="protocol_contract",
        )
        == "MODEL_LIFECYCLE_INACTIVE"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 408, 429, 500, 503])
async def test_unknown_create_responses_are_single_submission_without_retry(status: int) -> None:
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={"unexpected": "no verified task envelope"})

    compiled = CompiledVideoRequest(
        provider_type="openai_compatible_media",
        protocol_profile=PROFILE,
        model_id="remote",
        operation="video.generate",
        wire_request={"model": "remote", "prompt": "synthetic", "seconds": 5, "size": "832x480"},
        request_schema_version="2026-10-30",
        safe_request_summary={"transport": "json"},
    )
    runtime = OpenAICompatibleMediaRuntime(
        protocol_profile=PROFILE,
        settings=Settings(
            openai_compatible_media_enabled=True,
            openai_compatible_media_auth_mode="none",
            openai_compatible_media_api_key="",
        ),
        host="https://example.test/v1",
        transport=httpx.MockTransport(handler),
    )
    result = await runtime.submit_video(compiled)
    assert result.status == "unknown_submission"
    assert result.error_code == "PROVIDER_SUBMISSION_UNKNOWN"
    assert len(seen) == 1
    assert "Authorization" not in seen[0].headers
    assert seen[0].headers["Content-Type"].startswith("application/json")
    assert json.loads(seen[0].content) == compiled.wire_request


@pytest.mark.asyncio
async def test_anonymous_submission_accepts_captured_shape_without_default_key() -> None:
    """Observed 202 envelope shape, with task ID/time sanitized; not media qualification."""
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            202,
            json={"id": "synthetic-job", "object": "video", "status": "queued", "created_at": 0},
        )

    compiled = await _compile(_intent())
    runtime = OpenAICompatibleMediaRuntime(
        protocol_profile=PROFILE,
        settings=Settings(
            openai_compatible_media_enabled=True,
            openai_compatible_media_auth_mode="none",
            openai_compatible_media_api_key="global-default",
        ),
        host="https://example.test/custom/v1",
        transport=httpx.MockTransport(handler),
    )
    result = await runtime.submit_video(compiled)
    assert result.status == "queued" and result.remote_task_id == "synthetic-job"
    assert result.resume_token.protocol_profile == PROFILE
    assert len(seen) == 1 and seen[0].url.path == "/custom/v1/videos"
    assert "Authorization" not in seen[0].headers
    assert json.loads(seen[0].content) == compiled.wire_request


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_definite_http_rejection_remains_failed_and_is_not_retried(status: int) -> None:
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(status, json={"error": "synthetic rejection"})

    runtime = OpenAICompatibleMediaRuntime(
        protocol_profile=PROFILE,
        settings=Settings(
            openai_compatible_media_enabled=True,
            openai_compatible_media_auth_mode="none",
            openai_compatible_media_api_key="",
        ),
        host="https://example.test/v1",
        transport=httpx.MockTransport(handler),
    )
    assert (await runtime.submit_video(await _compile(_intent()))).status == "failed"
    assert count == 1


@pytest.mark.asyncio
async def test_transport_timeout_remains_unknown_and_never_repeats_create() -> None:
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        raise httpx.ReadTimeout("synthetic", request=request)

    runtime = OpenAICompatibleMediaRuntime(
        protocol_profile=PROFILE,
        settings=Settings(
            openai_compatible_media_enabled=True,
            openai_compatible_media_auth_mode="none",
            openai_compatible_media_api_key="",
        ),
        host="https://example.test/v1",
        transport=httpx.MockTransport(handler),
    )
    result = await runtime.submit_video(await _compile(_intent()))
    assert result.status == "unknown_submission" and count == 1


@pytest.mark.asyncio
async def test_poll_does_not_adopt_server_file_path_or_external_url_and_cancel_is_closed() -> None:
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "synthetic-job",
                "status": "completed",
                "url": "https://unrelated.example/result.mp4",
                "file_path": "/server/private.mp4",
            },
        )

    runtime = OpenAICompatibleMediaRuntime(
        protocol_profile=PROFILE,
        settings=Settings(
            openai_compatible_media_enabled=True,
            openai_compatible_media_auth_mode="none",
            openai_compatible_media_api_key="",
        ),
        host="https://example.test/v1",
        transport=httpx.MockTransport(handler),
    )
    token = ProviderResumeToken(
        provider_type="openai_compatible_media",
        protocol_profile=PROFILE,
        remote_task_id="synthetic/job",
        query_kind="video_id",
    )
    poll = await runtime.poll_video(token)
    assert poll.artifact_uri == "provider-content"
    assert poll.status == "succeeded"
    assert len(requests) == 1 and requests[0].url.raw_path == b"/v1/videos/synthetic%2Fjob"
    assert (await runtime.cancel_video(token)).status == "failed"
    assert len(requests) == 1


def test_protocol_metadata_keeps_preview_and_anonymous_support_separate_from_legacy() -> None:
    plugin = get_plugin("openai_compatible_media", PROFILE)
    assert plugin.auth_modes == frozenset({"none", "bearer"})
    assert plugin.manual_model_ids and plugin.model_list_path == "/models"
    assert plugin.compiler_factory()[0] is None
    assert not plugin.catalog_manifests  # Only the preview candidate exists.
    assert get_plugin("openai_compatible_media", "openai_media_v1").auth_modes == frozenset(
        {"bearer"}
    )
    settings = Settings(
        openai_compatible_media_enabled=True,
        openai_compatible_media_auth_mode="none",
        openai_compatible_media_api_key="",
    )
    assert OpenAICompatibleMediaClient(
        settings, host="https://example.test/v1", protocol_profile=PROFILE
    ).configured()
    assert not OpenAICompatibleMediaClient(settings, host="https://example.test/v1").configured()


@pytest.mark.parametrize("path", ["/v1/videos", "/v1/videos/generations"])
def test_operation_url_is_not_silently_rewritten_to_another_generation_endpoint(path: str) -> None:
    with pytest.raises(ValueError, match="API base prefix"):
        normalize_json_video_base_url("https://example.test" + path)
    assert (
        normalize_json_video_base_url("https://example.test/custom/v1/")
        == "https://example.test/custom/v1"
    )
