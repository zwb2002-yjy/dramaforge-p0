"""Tests for the protocol-level OpenAI-compatible media adapter."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from app.config import Settings
from app.providers.catalog_seed_data import SEED_MANIFESTS
from app.providers.intents import (
    ArtifactReferenceIntent,
    ImageGenerationIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
    VideoOutputIntent,
)
from app.providers.manifest import ModelCapabilityManifest
from app.providers.openai_compatible_media import (
    OPENAI_MEDIA_PROFILE,
    OpenAICompatibleImageCompiler,
    OpenAICompatibleMediaClient,
    OpenAICompatibleMediaRuntime,
    OpenAICompatibleVideoCompiler,
)
from app.providers.runtime import (
    CompiledImageRequest,
    CompiledVideoRequest,
    ResolvedReference,
)


def _settings() -> Settings:
    return Settings(
        openai_compatible_media_enabled=True,
        openai_compatible_media_api_key="test-key",
        openai_compatible_media_base_url="https://example.test/v1",
        openai_compatible_media_image_model="image-model",
        openai_compatible_media_video_model="video-model",
    )


def _manifest(model_id: str, revision: str = "v1") -> ModelCapabilityManifest:
    raw = next(
        item for item in SEED_MANIFESTS
        if item["model_id"] == model_id and item["model_revision"] == revision
    )
    return ModelCapabilityManifest.model_validate(raw)


@pytest.mark.asyncio
async def test_protocol_client_uses_openai_compatible_image_and_video_shapes() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST" and request.url.path == "/v1/images/generations":
            return httpx.Response(
                200,
                json={"data": [{"url": "https://cdn.example/image.png"}]},
            )
        if request.method == "POST" and request.url.path == "/v1/videos":
            return httpx.Response(202, json={"id": "vid-1", "status": "queued"})
        if request.method == "GET" and request.url.path == "/v1/videos/vid-1":
            return httpx.Response(
                200,
                json={"id": "vid-1", "status": "completed", "output_url": "https://cdn.example/video.mp4"},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = OpenAICompatibleMediaClient(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    image = await client.create_image(prompt="portrait")
    video = await client.create_video(
        prompt="subtle motion", image_bytes=b"png", image_mime="image/png"
    )
    poll = await client.poll_video("vid-1")

    assert image["status"] == "succeeded"
    assert video["remote_task_id"] == "vid-1"
    assert poll["status"] == "succeeded"
    assert poll["artifact_uri"] == "https://cdn.example/video.mp4"
    assert seen[0].headers["authorization"] == "Bearer test-key"
    assert seen[0].url.path == "/v1/images/generations"
    assert seen[1].url.path == "/v1/videos"
    assert seen[1].headers["content-type"].startswith("multipart/form-data")


@pytest.mark.asyncio
async def test_local_video_poll_uses_connection_content_even_with_https_output_url() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.raw_path == b"/v1/videos/video%2F1"
        return httpx.Response(
            200,
            json={
                "id": "video/1",
                "status": "completed",
                "output_url": "https://cdn.example/video.mp4",
            },
        )

    settings = _settings().model_copy(
        update={"openai_compatible_media_base_url": "http://192.0.2.10:30020/v1"}
    )
    client = OpenAICompatibleMediaClient(settings, transport=httpx.MockTransport(handler))
    poll = await client.poll_video("video/1")
    assert poll["status"] == "succeeded"
    assert poll["artifact_uri"] == "provider-content"


@pytest.mark.asyncio
async def test_compilers_bind_discovered_model_id_not_protocol_contract_id() -> None:
    artifact_id = uuid4()
    selection = ModelSelectionIntent(mode="explicit_binding", model_binding_id=uuid4())
    image_intent = ImageGenerationIntent(
        prompt="portrait",
        reference_artifact_id=artifact_id,
        reference_mime="image/png",
        selection=selection,
    )
    image_ref = ResolvedReference(
        role="reference_image",
        artifact_id=artifact_id,
        content_bytes=b"png",
        mime_type="image/png",
        fingerprint="sha256:png",
    )
    image_request = await OpenAICompatibleImageCompiler().compile(
        image_intent,
        _manifest("@contract/openai-image-v1"),
        [image_ref],
        invoke_model_value="discovered-image-model",
    )

    video_intent = VideoGenerationIntentV1(
        prompt="subtle motion",
        references=[ArtifactReferenceIntent(artifact_id=artifact_id, role="first_frame")],
        selection=selection,
    )
    video_ref = ResolvedReference(
        role="first_frame",
        artifact_id=artifact_id,
        content_url="https://cdn.example/frame.png",
        mime_type="image/png",
    )
    video_request = await OpenAICompatibleVideoCompiler().compile(
        video_intent,
        _manifest("@contract/openai-video-v1"),
        [video_ref],
        invoke_model_value="discovered-video-model",
    )

    assert image_request.protocol_profile == OPENAI_MEDIA_PROFILE
    assert image_request.wire_request["model"] == "discovered-image-model"
    assert image_request.wire_request["image_b64"] == "cG5n"
    assert video_request.wire_request["model"] == "discovered-video-model"
    assert video_request.wire_request["input_image_url"] == "https://cdn.example/frame.png"


@pytest.mark.asyncio
async def test_text_video_contract_compiles_without_a_first_frame() -> None:
    intent = VideoGenerationIntentV1(
        prompt="A quiet street at dawn",
        mode_id="text_to_video",
        selection=ModelSelectionIntent(mode="explicit_binding", model_binding_id=uuid4()),
    )
    request = await OpenAICompatibleVideoCompiler().compile(
        intent,
        _manifest("@contract/sglang-h3-t2v-v1"),
        [],
        invoke_model_value="/models/MiniMax-H3-runtime",
    )
    assert request.wire_request["model"] == "/models/MiniMax-H3-runtime"
    assert request.reference_artifact_ids == []
    assert request.safe_request_summary["reference_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "roles", "task", "frame_indices"),
    [
        ("text_to_video", [], "t2va", []),
        ("first_frame", ["first_frame"], "fl2va", [0]),
        ("last_frame", ["last_frame"], "fl2va", [-1]),
        ("first_last_frame", ["first_frame", "last_frame"], "fl2va", [0, -1]),
    ],
)
async def test_h3_fl2va_modes_compile_json_keyframes(
    mode: str, roles: list[str], task: str, frame_indices: list[int]
) -> None:
    ids = [uuid4() for _ in roles]
    intent = VideoGenerationIntentV1(
        prompt="A quiet street at dawn",
        mode_id=mode,
        references=[
            ArtifactReferenceIntent(artifact_id=artifact_id, role=role)
            for artifact_id, role in zip(ids, roles, strict=True)
        ],
        selection=ModelSelectionIntent(mode="explicit_binding", model_binding_id=uuid4()),
    )
    refs = [
        ResolvedReference(
            role=role, artifact_id=artifact_id, content_bytes=b"image",
            mime_type="image/png",
        )
        for artifact_id, role in zip(ids, roles, strict=True)
    ]
    request = await OpenAICompatibleVideoCompiler().compile(
        intent, _manifest("@contract/sglang-h3-fl2va-v1"), refs,
        invoke_model_value="discovered-h3",
    )
    assert request.wire_request["task"] == task
    assert [item["frame_index"] for item in request.wire_request["conditions"]] == frame_indices
    assert all(item["role"] == "keyframe" for item in request.wire_request["conditions"])
    assert request.reference_artifact_ids == ids

    async def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.headers["content-type"] == "application/json"
        assert http_request.url.path == "/v1/videos"
        assert f'"task":"{task}"'.encode() in await http_request.aread()
        return httpx.Response(202, json={"id": "fl-job", "status": "queued"})

    runtime = OpenAICompatibleMediaRuntime(
        settings=_settings(), transport=httpx.MockTransport(handler)
    )
    assert (await runtime.submit_video(request)).remote_task_id == "fl-job"


@pytest.mark.asyncio
async def test_h3_fl2va_rejects_wrong_frame_mode_and_identity() -> None:
    artifact_id = uuid4()
    intent = VideoGenerationIntentV1(
        prompt="Morning river", mode_id="last_frame",
        references=[ArtifactReferenceIntent(artifact_id=artifact_id, role="first_frame")],
        selection=ModelSelectionIntent(mode="explicit_binding", model_binding_id=uuid4()),
    )
    with pytest.raises(ValueError, match="frame mode"):
        await OpenAICompatibleVideoCompiler().compile(
            intent, _manifest("@contract/sglang-h3-fl2va-v1"),
            [ResolvedReference(
                role="first_frame", artifact_id=artifact_id,
                content_bytes=b"image", mime_type="image/png",
            )],
            invoke_model_value="discovered-h3",
        )


@pytest.mark.asyncio
async def test_h3_ref2va_v2_accepts_multiple_images_and_rejects_over_limit() -> None:
    ids = [uuid4() for _ in range(10)]
    intent = VideoGenerationIntentV1(
        prompt="Use each picture as reference", mode_id="omni_reference",
        references=[
            ArtifactReferenceIntent(artifact_id=artifact_id, role="reference_image")
            for artifact_id in ids
        ],
        selection=ModelSelectionIntent(mode="explicit_binding", model_binding_id=uuid4()),
    )
    refs = [ResolvedReference(
        role="reference_image", artifact_id=artifact_id,
        content_bytes=b"image", mime_type="image/png",
    ) for artifact_id in ids]
    compiler = OpenAICompatibleVideoCompiler()
    manifest = _manifest("@contract/sglang-h3-ref2va-v1", "v2")
    nine = intent.model_copy(update={"references": intent.references[:9]})
    compiled = await compiler.compile(nine, manifest, refs[:9], invoke_model_value="discovered-h3")
    assert len(compiled.wire_request["conditions"]) == 9
    with pytest.raises(ValueError, match="at most 9"):
        await compiler.compile(intent, manifest, refs, invoke_model_value="discovered-h3")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["reference_video", "reference_audio"])
@pytest.mark.parametrize(
    ("durations", "error"),
    [
        ([2, 13], None),
        ([8, 8], "total duration"),
        ([1], "duration must"),
        ([16], "duration must"),
        ([None], "verified media duration"),
        ([2, 2, 2, 2], "at most 3"),
    ],
)
async def test_ref2va_v2_checks_media_duration_and_cardinality(
    role: str, durations: list[float | None], error: str | None,
) -> None:
    ids = [uuid4() for _ in durations]
    intent = VideoGenerationIntentV1(
        prompt="Follow the reference", mode_id="omni_reference",
        references=[ArtifactReferenceIntent(artifact_id=aid, role=role) for aid in ids],
        selection=ModelSelectionIntent(mode="explicit_binding", model_binding_id=uuid4()),
    )
    refs = [
        ResolvedReference(
            artifact_id=aid, role=role, content_bytes=b"media",
            mime_type="video/mp4" if role == "reference_video" else "audio/wav",
            duration_seconds=duration,
        )
        for aid, duration in zip(ids, durations, strict=True)
    ]
    compiler = OpenAICompatibleVideoCompiler()
    if error:
        with pytest.raises(ValueError, match=error):
            await compiler.compile(
                intent, _manifest("@contract/sglang-h3-ref2va-v1", "v2"), refs,
                invoke_model_value="discovered-h3",
            )
    else:
        compiled = await compiler.compile(
            intent, _manifest("@contract/sglang-h3-ref2va-v1", "v2"), refs,
            invoke_model_value="discovered-h3",
        )
        assert len(compiled.wire_request["conditions"]) == len(durations)


@pytest.mark.asyncio
async def test_ref2va_v2_checks_mixed_file_limit() -> None:
    roles = ["reference_image"] * 9 + ["reference_video"] * 3 + ["reference_audio"]
    refs = [
        ResolvedReference(
            artifact_id=uuid4(), role=role, content_bytes=b"media", duration_seconds=2,
            mime_type={"reference_image": "image/png", "reference_video": "video/mp4",
                       "reference_audio": "audio/wav"}[role],
        )
        for role in roles
    ]
    intent = VideoGenerationIntentV1(
        prompt="Use the mixed references", mode_id="omni_reference",
        references=[ArtifactReferenceIntent(artifact_id=ref.artifact_id, role=ref.role)
                    for ref in refs],
        selection=ModelSelectionIntent(mode="explicit_binding", model_binding_id=uuid4()),
    )
    compiler = OpenAICompatibleVideoCompiler()
    twelve = intent.model_copy(update={"references": intent.references[:12]})
    compiled = await compiler.compile(
        twelve, _manifest("@contract/sglang-h3-ref2va-v1", "v2"), refs[:12],
        invoke_model_value="discovered-h3",
    )
    assert len(compiled.wire_request["conditions"]) == 12
    with pytest.raises(ValueError, match="12 files in total"):
        await compiler.compile(
            intent, _manifest("@contract/sglang-h3-ref2va-v1", "v2"), refs,
            invoke_model_value="discovered-h3",
        )


@pytest.mark.asyncio
async def test_h3_ref2va_compiles_ordered_media_conditions_and_json_submission() -> None:
    ids = [uuid4(), uuid4(), uuid4()]
    roles = ["reference_image", "reference_video", "reference_audio"]
    mimes = ["image/png", "video/mp4", "audio/wav"]
    intent = VideoGenerationIntentV1(
        prompt="A river at dawn, following <Video 1>",
        mode_id="omni_reference",
        references=[
            ArtifactReferenceIntent(artifact_id=artifact_id, role=role)
            for artifact_id, role in zip(ids, roles, strict=True)
        ],
        selection=ModelSelectionIntent(mode="explicit_binding", model_binding_id=uuid4()),
    )
    refs = [
        ResolvedReference(
            role=role,
            artifact_id=artifact_id,
            content_bytes=f"bytes-{index}".encode(),
            mime_type=mime,
            fingerprint=f"hash-{index}",
        )
        for index, (artifact_id, role, mime) in enumerate(zip(ids, roles, mimes, strict=True))
    ]
    compiled = await OpenAICompatibleVideoCompiler().compile(
        intent,
        _manifest("@contract/sglang-h3-ref2va-v1"),
        refs,
        invoke_model_value="/models/MiniMax-H3-runtime",
    )
    assert compiled.wire_request["task"] == "ref2va"
    assert [condition["type"] for condition in compiled.wire_request["conditions"]] == [
        "image", "video", "audio"
    ]
    assert all(condition["uri"].startswith(f"data:{mime};base64,") for condition, mime in zip(
        compiled.wire_request["conditions"], mimes, strict=True
    ))
    assert compiled.reference_artifact_ids == ids
    assert "conditions" not in compiled.safe_request_summary

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["content-type"] == "application/json"
        assert request.url.path == "/v1/videos"
        assert b'"task":"ref2va"' in await request.aread()
        return httpx.Response(200, json={"id": "ref-job", "status": "queued"})

    runtime = OpenAICompatibleMediaRuntime(
        settings=_settings(), transport=httpx.MockTransport(handler)
    )
    submitted = await runtime.submit_video(compiled)
    assert submitted.remote_task_id == "ref-job"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "mime", "media_type"),
    [
        ("reference_image", "image/png", "image"),
        ("reference_audio", "audio/wav", "audio"),
    ],
)
async def test_h3_ref2va_accepts_single_image_or_audio_reference(
    role: str, mime: str, media_type: str
) -> None:
    artifact_id = uuid4()
    intent = VideoGenerationIntentV1(
        prompt="Morning river",
        mode_id="omni_reference",
        references=[ArtifactReferenceIntent(artifact_id=artifact_id, role=role)],
        selection=ModelSelectionIntent(mode="explicit_binding", model_binding_id=uuid4()),
    )
    compiled = await OpenAICompatibleVideoCompiler().compile(
        intent,
        _manifest("@contract/sglang-h3-ref2va-v1"),
        [ResolvedReference(
            role=role,
            artifact_id=artifact_id,
            content_bytes=b"reference",
            mime_type=mime,
        )],
        invoke_model_value="/models/MiniMax-H3-runtime",
    )
    assert compiled.wire_request["conditions"][0]["type"] == media_type


def test_h3_ref2va_refuses_a_false_native_audio_setting() -> None:
    artifact_id = uuid4()
    intent = VideoGenerationIntentV1(
        prompt="Morning river",
        mode_id="omni_reference",
        output=VideoOutputIntent(generate_audio=False),
        references=[ArtifactReferenceIntent(artifact_id=artifact_id, role="reference_video")],
        selection=ModelSelectionIntent(mode="explicit_binding", model_binding_id=uuid4()),
    )
    with pytest.raises(ValueError, match="cannot be disabled"):
        OpenAICompatibleVideoCompiler().validate(
            intent, _manifest("@contract/sglang-h3-ref2va-v1")
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("historical_request", [False, True])
async def test_text_video_runtime_uses_multipart_and_completed_content_url(
    historical_request: bool,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert request.url.path == "/v1/videos"
            assert request.headers["content-type"].startswith("multipart/form-data")
            body = await request.aread()
            assert b"/models/MiniMax-H3-runtime" in body
            assert b'"task": "t2va"' in body
            assert b"input_reference" not in body
            return httpx.Response(202, json={"id": "video-1", "status": "queued"})
        if request.url.path == "/v1/videos/video-1/content":
            return httpx.Response(
                200, content=b"video-bytes", headers={"content-type": "video/mp4"}
            )
        assert request.url.path == "/v1/videos/video-1"
        return httpx.Response(200, json={"id": "video-1", "status": "completed"})

    request = await OpenAICompatibleVideoCompiler().compile(
        VideoGenerationIntentV1(
            prompt="A quiet street at dawn",
            mode_id="text_to_video",
            selection=ModelSelectionIntent(mode="explicit_binding", model_binding_id=uuid4()),
        ),
        _manifest("@contract/sglang-h3-t2v-v1"),
        [],
        invoke_model_value="/models/MiniMax-H3-runtime",
    )
    if historical_request:
        request.safe_request_summary.pop("transport")
    runtime = OpenAICompatibleMediaRuntime(
        settings=_settings(),
        transport=httpx.MockTransport(handler),
    )
    submitted = await runtime.submit_video(request)
    assert submitted.status == "queued"
    assert submitted.resume_token is not None
    polled = await runtime.poll_video(submitted.resume_token)
    assert polled.status == "succeeded"
    assert polled.artifact_uri == "provider-content"
    assert await runtime.fetch_artifact(submitted.resume_token) == b"video-bytes"


@pytest.mark.asyncio
async def test_runtime_sends_compiled_model_without_substituting_settings_default() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/images/edits"
        body = await request.aread()
        assert b"discovered-image-model" in body
        return httpx.Response(200, json={"data": [{"url": "https://cdn.example/image.png"}]})

    compiler = OpenAICompatibleImageCompiler()
    artifact_id = uuid4()
    request = await compiler.compile(
        ImageGenerationIntent(
            prompt="portrait",
            reference_artifact_id=artifact_id,
            reference_mime="image/png",
            selection=ModelSelectionIntent(mode="explicit_binding", model_binding_id=uuid4()),
        ),
        _manifest("@contract/openai-image-v1"),
        [
            ResolvedReference(
                role="reference_image",
                artifact_id=artifact_id,
                content_bytes=b"png",
                mime_type="image/png",
            )
        ],
        invoke_model_value="discovered-image-model",
    )
    runtime = OpenAICompatibleMediaRuntime(
        settings=_settings(),
        transport=httpx.MockTransport(handler),
    )
    result = await runtime.submit_image(request)
    assert result.status == "succeeded"
    assert result.artifact_uri == "https://cdn.example/image.png"


@pytest.mark.asyncio
async def test_runtime_marks_transport_errors_as_unknown_submission() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("connection lost", request=request)

    runtime = OpenAICompatibleMediaRuntime(
        settings=_settings(),
        transport=httpx.MockTransport(handler),
    )
    image_request = CompiledImageRequest(
        provider_type="openai_compatible_media",
        protocol_profile=OPENAI_MEDIA_PROFILE,
        model_id="discovered-image-model",
        operation="image.generate",
        wire_request={"model": "discovered-image-model", "prompt": "portrait"},
        request_schema_version="1",
    )
    video_request = CompiledVideoRequest(
        provider_type="openai_compatible_media",
        protocol_profile=OPENAI_MEDIA_PROFILE,
        model_id="discovered-video-model",
        operation="video.generate",
        wire_request={"model": "discovered-video-model", "prompt": "motion"},
        request_schema_version="1",
    )

    image_result = await runtime.submit_image(image_request)
    video_result = await runtime.submit_video(video_request)

    assert image_result.status == "unknown_submission"
    assert image_result.error_code == "PROVIDER_SUBMISSION_UNKNOWN"
    assert image_result.error == "ConnectError"
    assert video_result.status == "unknown_submission"
    assert video_result.error_code == "PROVIDER_SUBMISSION_UNKNOWN"
    assert video_result.error == "ConnectError"
    assert calls == 2
