"""MiniMax compiler and unified runtime tests without real provider I/O."""

from __future__ import annotations

import json
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest
from app.config import Settings
from app.providers.capability_resolver import ProductCapabilityPolicy
from app.providers.catalog_loader import ModelCatalogLoader
from app.providers.catalog_seed_data import SEED_MANIFESTS
from app.providers.intents import (
    ArtifactReferenceIntent,
    ImageGenerationIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
    VideoOutputIntent,
)
from app.providers.manifest import ModelCapabilityManifest
from app.providers.minimax import MiniMaxImageCompiler, MiniMaxRuntime, MiniMaxVideoCompiler
from app.providers.runtime import CompiledVideoRequest, ProviderResumeToken, ResolvedReference


def _manifest(model_id: str) -> ModelCapabilityManifest:
    return ModelCapabilityManifest.model_validate(
        next(item for item in SEED_MANIFESTS if item["model_id"] == model_id)
    )


def _preview_manifest(model_id: str) -> ModelCapabilityManifest:
    raw = next(
        item.as_dict()
        for item in ModelCatalogLoader().load()
        if item.identity[2] == model_id and item.as_dict()["lifecycle"] == "preview"
    )
    return ModelCapabilityManifest.model_validate(raw)


def _video_contract_manifest(*, max_variant: bool) -> ModelCapabilityManifest:
    source = next(item for item in SEED_MANIFESTS if item["model_id"] == "MiniMax-H3")
    revised = deepcopy(source)
    revised["model_revision"] = "v2-contract-test"
    if max_variant:
        revised["model_id"] = "MiniMax-H3-Max"
        revised["display_name"] = "MiniMax H3 Max"
    operation = revised["operations"]["video.generate"]
    operation["input_contracts"] = {
        "text": {"input_slots": {}, "maximum_total_references": 0},
        "frame": {
            "input_slots": {
                "first_frame": {"maximum": 1, "media_types": ["image/*"]},
                "last_frame": {"maximum": 1, "media_types": ["image/*"]},
            },
            "minimum_total_references": 1,
        },
        "reference": {
            "input_slots": {
                "reference_image": {"maximum": 9, "media_types": ["image/*"]},
                "reference_video": {"maximum": 3, "media_types": ["video/*"]},
                "reference_audio": {"maximum": 3, "media_types": ["audio/*"]},
            },
            "minimum_total_references": 1,
            "maximum_total_references": 12,
        },
    }
    operation["output_options"] = {
        "resolution": {
            "type": "string",
            "enum": ["480P", "768P"] if max_variant else ["768P", "2K"],
            "default": "768P",
        },
        "duration_seconds": {
            "type": "integer",
            "minimum": 5 if max_variant else 4,
            "maximum": 15,
            "default": 5,
        },
        "aspect_ratio": {
            "type": "string",
            "enum": ["adaptive", "9:16", "16:9"],
            "default": "adaptive",
        },
    }
    if max_variant:
        operation["output_options"]["prompt_expansion_mode"] = {
            "type": "string",
            "enum": ["balanced"],
            "default": "balanced",
        }
    return ModelCapabilityManifest.model_validate(revised)


def _settings() -> Settings:
    return Settings(
        minimax_enabled=True,
        minimax_api_key="test-minimax-key",
        minimax_base_url="https://api.minimaxi.com",
    )


@pytest.mark.asyncio
async def test_image_compiler_requires_one_https_reference_and_builds_native_body() -> None:
    artifact_id = uuid4()
    intent = ImageGenerationIntent(
        prompt="portrait",
        reference_artifact_id=artifact_id,
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    reference = ResolvedReference(
        role="reference_image",
        artifact_id=artifact_id,
        content_url="https://dramaforge.example/api/v1/provider-references/image-token",
        fingerprint="a" * 64,
    )
    compiled = await MiniMaxImageCompiler().compile(
        intent,
        _manifest("image-01"),
        [reference],
        invoke_model_value="image-01",
    )
    assert compiled.wire_request["subject_reference"] == [
        {
            "type": "character",
            "image_file": "https://dramaforge.example/api/v1/provider-references/image-token",
        }
    ]
    assert compiled.wire_request["aspect_ratio"] == "1:1"
    assert compiled.reference_artifact_ids == [artifact_id]
    assert "image-token" not in json.dumps(compiled.safe_request_summary)


@pytest.mark.asyncio
async def test_same_image_compiler_handles_manifest_driven_t2i_and_i2i() -> None:
    source = next(item for item in SEED_MANIFESTS if item["model_id"] == "image-01")
    revised = deepcopy(source)
    revised["model_revision"] = "v2-test"
    operation = revised["operations"]["image.generate"]
    operation["capabilities"] = ["image.t2i", "image.i2i"]
    operation["input_contracts"] = {
        "text": {"input_slots": {}},
        "reference": {
            "input_slots": {"reference_image": {"minimum": 1, "maximum": 1}},
            "minimum_total_references": 1,
        },
    }
    operation["output_options"] = {
        "aspect_ratio": {
            "type": "string",
            "enum": ["1:1", "9:16", "16:9"],
            "default": "9:16",
        },
        "response_format": {"type": "string", "enum": ["url", "base64"], "default": "url"},
        "n": {"type": "integer", "minimum": 1, "maximum": 9, "default": 1},
        "prompt_optimizer": {"type": "boolean", "default": False},
    }
    manifest = ModelCapabilityManifest.model_validate(revised)
    compiler = MiniMaxImageCompiler()
    policy = ProductCapabilityPolicy(
        allowed_contracts=frozenset({"text", "reference"}),
        allowed_options=frozenset({"aspect_ratio"}),
    )

    with pytest.raises(ValueError, match="explicit product policy"):
        await compiler.compile(
            ImageGenerationIntent(
                prompt="portrait", selection=ModelSelectionIntent(mode="explicit_binding")
            ),
            manifest,
            [],
            invoke_model_value="image-01",
        )
    text = await compiler.compile(
        ImageGenerationIntent(
            prompt="portrait", selection=ModelSelectionIntent(mode="explicit_binding")
        ),
        manifest,
        [],
        invoke_model_value="image-01",
        policy=policy,
    )
    assert text.wire_request["aspect_ratio"] == "9:16"
    assert text.wire_request["response_format"] == "url"
    assert text.wire_request["n"] == 1
    assert text.wire_request["prompt_optimizer"] is False
    assert "aigc_watermark" not in text.wire_request
    assert "subject_reference" not in text.wire_request
    assert text.safe_request_summary["matched_contract"] == "text"

    artifact_id = uuid4()
    image = await compiler.compile(
        ImageGenerationIntent(
            prompt="portrait",
            aspect_ratio="1:1",
            reference_artifact_id=artifact_id,
            selection=ModelSelectionIntent(mode="explicit_binding"),
        ),
        manifest,
        [
            ResolvedReference(
                role="reference_image",
                artifact_id=artifact_id,
                content_url="https://dramaforge.example/ref.png",
            )
        ],
        invoke_model_value="image-01",
        policy=policy,
    )
    assert image.wire_request["subject_reference"] == [
        {"type": "character", "image_file": "https://dramaforge.example/ref.png"}
    ]
    assert image.safe_request_summary["matched_contract"] == "reference"

    with pytest.raises(ValueError, match="no input contract"):
        await compiler.compile(
            ImageGenerationIntent(
                prompt="portrait",
                seed=7,
                selection=ModelSelectionIntent(mode="explicit_binding"),
            ),
            manifest,
            [],
            invoke_model_value="image-01",
            policy=policy,
        )

    revised["operations"]["image.generate"]["output_options"]["n"]["default"] = 2
    with pytest.raises(ValueError, match="product requires URL, one image"):
        await compiler.compile(
            ImageGenerationIntent(
                prompt="portrait", selection=ModelSelectionIntent(mode="explicit_binding")
            ),
            ModelCapabilityManifest.model_validate(revised),
            [],
            invoke_model_value="image-01",
            policy=policy,
        )


def test_video_compiler_rejects_unsupported_outputs_and_roles() -> None:
    artifact_id = uuid4()
    intent = VideoGenerationIntentV1(
        prompt="motion",
        output=VideoOutputIntent(duration_seconds=6),
        references=[ArtifactReferenceIntent(artifact_id=artifact_id, role="first_frame")],
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    with pytest.raises(ValueError, match="768P, 5 seconds"):
        MiniMaxVideoCompiler().validate(intent, _manifest("MiniMax-H3"))

    invalid_roles = intent.model_copy(
        update={
            "output": VideoOutputIntent(),
            "references": [
                ArtifactReferenceIntent(artifact_id=artifact_id, role="first_frame"),
                ArtifactReferenceIntent(artifact_id=uuid4(), role="last_frame"),
            ],
        }
    )
    with pytest.raises(ValueError, match="no other reference roles"):
        MiniMaxVideoCompiler().validate(invalid_roles, _manifest("MiniMax-H3"))


@pytest.mark.asyncio
@pytest.mark.parametrize("aspect_ratio", ["9:16", "16:9"])
async def test_video_compiler_inherits_supported_project_ratio_from_first_frame(
    aspect_ratio: str,
) -> None:
    artifact_id = uuid4()
    intent = VideoGenerationIntentV1(
        prompt="motion",
        output=VideoOutputIntent(
            aspect_ratio=aspect_ratio,  # type: ignore[arg-type]
            duration_seconds=5,
            resolution="768P",
            generate_audio=False,
        ),
        references=[ArtifactReferenceIntent(artifact_id=artifact_id, role="first_frame")],
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    compiled = await MiniMaxVideoCompiler().compile(
        intent,
        _manifest("MiniMax-H3"),
        [
            ResolvedReference(
                role="first_frame",
                artifact_id=artifact_id,
                content_url="https://cdn.example.com/first.png",
                fingerprint="b" * 64,
            )
        ],
        invoke_model_value="MiniMax-H3",
    )

    assert compiled.wire_request["ratio"] == "adaptive"
    assert compiled.wire_request["duration"] == 5
    assert compiled.safe_request_summary["effective_common_options"] == {
        "aspect_ratio": aspect_ratio,
        "duration_seconds": 5,
        "resolution": "768P",
        "generate_audio": False,
    }
    assert compiled.safe_request_summary["translation_transformations"] == [
        {
            "field": "aspect_ratio",
            "from_value": aspect_ratio,
            "to_value": "adaptive",
            "reason": "provider_inherits_aspect_ratio_from_first_frame",
        }
    ]


@pytest.mark.parametrize("aspect_ratio", [None, "1:1", "adaptive"])
def test_video_compiler_rejects_missing_or_unsupported_project_ratio(
    aspect_ratio: str | None,
) -> None:
    artifact_id = uuid4()
    intent = VideoGenerationIntentV1(
        prompt="motion",
        output=VideoOutputIntent(aspect_ratio=aspect_ratio),  # type: ignore[arg-type]
        references=[ArtifactReferenceIntent(artifact_id=artifact_id, role="first_frame")],
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    with pytest.raises(ValueError, match="first-frame-inherited ratio"):
        MiniMaxVideoCompiler().validate(intent, _manifest("MiniMax-H3"))


def test_video_compiler_rejects_missing_first_frame() -> None:
    intent = VideoGenerationIntentV1(
        prompt="motion",
        output=VideoOutputIntent(aspect_ratio="9:16", duration_seconds=5),
        references=[],
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    with pytest.raises(ValueError, match="exactly one first_frame"):
        MiniMaxVideoCompiler().validate(intent, _manifest("MiniMax-H3"))


@pytest.mark.asyncio
async def test_same_minimax_video_compiler_uses_h3_and_h3_max_manifests() -> None:
    compiler = MiniMaxVideoCompiler()
    h3 = _video_contract_manifest(max_variant=False)
    h3_max = _video_contract_manifest(max_variant=True)
    policy = ProductCapabilityPolicy(allowed_contracts=frozenset({"text", "frame"}))
    text_intent = VideoGenerationIntentV1(
        prompt="motion",
        output=VideoOutputIntent(aspect_ratio="16:9", duration_seconds=4, resolution="2K"),
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    with pytest.raises(ValueError, match="explicit product policy"):
        await compiler.compile(text_intent, h3, [], invoke_model_value=h3.model_id)
    compiled_h3 = await compiler.compile(
        text_intent, h3, [], invoke_model_value=h3.model_id, policy=policy
    )
    assert compiled_h3.wire_request["model"] == "MiniMax-H3"
    assert compiled_h3.wire_request["duration"] == 4
    assert compiled_h3.wire_request["resolution"] == "2K"
    assert compiled_h3.wire_request["ratio"] == "16:9"
    assert len(compiled_h3.wire_request["content"]) == 1
    with pytest.raises(ValueError, match="no input contract"):
        await compiler.compile(
            text_intent, h3_max, [], invoke_model_value=h3_max.model_id, policy=policy
        )

    frame_id = uuid4()
    frame_intent = VideoGenerationIntentV1(
        prompt="motion",
        output=VideoOutputIntent(aspect_ratio="9:16", duration_seconds=5, resolution="480P"),
        references=[ArtifactReferenceIntent(artifact_id=frame_id, role="first_frame")],
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    frame = ResolvedReference(
        role="first_frame",
        artifact_id=frame_id,
        content_url="https://example.com/frame.png",
    )
    compiled_max = await compiler.compile(
        frame_intent,
        h3_max,
        [frame],
        invoke_model_value=h3_max.model_id,
        policy=policy,
    )
    assert compiled_max.wire_request["model"] == "MiniMax-H3-Max"
    assert compiled_max.wire_request["resolution"] == "480P"
    assert compiled_max.wire_request["ratio"] == "adaptive"
    assert compiled_max.wire_request["extra"] == {"prompt_expansion_mode": "balanced"}
    assert compiled_max.safe_request_summary["matched_contract"] == "frame"
    assert "example.com" not in json.dumps(compiled_max.safe_request_summary)


@pytest.mark.asyncio
async def test_preview_minimax_manifests_compile_only_matching_contracts() -> None:
    image = _preview_manifest("image-01")
    h3 = _preview_manifest("MiniMax-H3")
    h3_max = _preview_manifest("MiniMax-H3-Max")
    assert {image.lifecycle, h3.lifecycle, h3_max.lifecycle} == {"preview"}

    image_request = await MiniMaxImageCompiler().compile(
        ImageGenerationIntent(
            prompt="portrait", selection=ModelSelectionIntent(mode="explicit_binding")
        ),
        image,
        [],
        invoke_model_value=image.model_id,
        policy=ProductCapabilityPolicy(allowed_contracts=frozenset({"text"})),
    )
    assert image_request.wire_request["model"] == "image-01"
    assert image_request.wire_request["n"] == 1
    assert image_request.safe_request_summary["matched_contract"] == "text"

    frame_id = uuid4()
    frame = ResolvedReference(
        role="first_frame",
        artifact_id=frame_id,
        content_url="https://example.com/frame.png",
        mime_type="image/png",
    )
    intent = VideoGenerationIntentV1(
        prompt="motion",
        output=VideoOutputIntent(aspect_ratio="9:16", duration_seconds=5, resolution="768P"),
        references=[ArtifactReferenceIntent(artifact_id=frame_id, role="first_frame")],
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    policy = ProductCapabilityPolicy(allowed_contracts=frozenset({"frame", "reference"}))
    for manifest in (h3, h3_max):
        compiled = await MiniMaxVideoCompiler().compile(
            intent, manifest, [frame], invoke_model_value=manifest.model_id, policy=policy
        )
        assert compiled.wire_request["model"] == manifest.model_id
        assert compiled.wire_request["ratio"] == "adaptive"
        assert compiled.safe_request_summary["matched_contract"] == "frame"

        conflicting = intent.model_copy(
            update={
                "references": [
                    ArtifactReferenceIntent(artifact_id=frame_id, role="first_frame"),
                    ArtifactReferenceIntent(artifact_id=uuid4(), role="reference_video"),
                ]
            }
        )
        with pytest.raises(ValueError, match="no input contract"):
            await MiniMaxVideoCompiler().compile(
                conflicting,
                manifest,
                [
                    frame,
                    ResolvedReference(
                        role="reference_video",
                        artifact_id=conflicting.references[1].artifact_id,
                        content_url="https://example.com/reference.mp4",
                        mime_type="video/mp4",
                        duration_seconds=5,
                    ),
                ],
                invoke_model_value=manifest.model_id,
                policy=policy,
            )


@pytest.mark.asyncio
async def test_minimax_video_contract_rejects_formal_reference_conflict() -> None:
    manifest = _video_contract_manifest(max_variant=False)
    frame_id, video_id = uuid4(), uuid4()
    intent = VideoGenerationIntentV1(
        prompt="motion",
        references=[
            ArtifactReferenceIntent(artifact_id=frame_id, role="first_frame"),
            ArtifactReferenceIntent(artifact_id=video_id, role="reference_video"),
        ],
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    references = [
        ResolvedReference(
            role="first_frame",
            artifact_id=frame_id,
            content_url="https://example.com/frame.png",
        ),
        ResolvedReference(
            role="reference_video",
            artifact_id=video_id,
            mime_type="video/mp4",
            content_url="https://example.com/reference.mp4",
        ),
    ]
    with pytest.raises(ValueError, match="no input contract"):
        await MiniMaxVideoCompiler().compile(
            intent,
            manifest,
            references,
            invoke_model_value=manifest.model_id,
            policy=ProductCapabilityPolicy(
                allowed_contracts=frozenset({"text", "frame", "reference"})
            ),
        )


@pytest.mark.asyncio
async def test_runtime_submits_compiled_wire_request_verbatim_and_polls_task_id() -> None:
    seen: list[tuple[str, str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, str(request.url), body))
        if request.method == "POST":
            return httpx.Response(200, json={"task_id": "task-456"})
        return httpx.Response(
            200,
            json={
                "task": {
                    "status": "succeeded",
                    "content": {"url": "https://cdn.example/video.mp4"},
                }
            },
        )

    compiled = CompiledVideoRequest(
        provider_type="minimax",
        protocol_profile="minimax_cn_v1",
        model_id="MiniMax-H3",
        operation="video.generate",
        wire_request={
            "model": "MiniMax-H3",
            "unexpected": "exact compiled body",
            "nested": {"number": 1},
        },
        request_schema_version="2026-08-13",
        safe_request_summary={"operation": "video.i2v.first_frame"},
    )
    runtime = MiniMaxRuntime(settings=_settings(), transport=httpx.MockTransport(handler))
    submitted = await runtime.submit_video(compiled)
    assert submitted.status == "queued"
    assert submitted.remote_task_id == "task-456"
    assert seen[0] == (
        "POST",
        "https://api.minimaxi.com/v2/video_generation",
        compiled.wire_request,
    )
    assert submitted.resume_token is not None
    assert submitted.resume_token.model_dump()["opaque_state"] == {}

    polled = await runtime.poll_video(
        ProviderResumeToken(
            provider_type="minimax",
            protocol_profile="minimax_cn_v1",
            remote_task_id="task-456",
        )
    )
    assert polled.status == "succeeded"
    assert polled.artifact_uri == "https://cdn.example/video.mp4"
    assert seen[1][1] == "https://api.minimaxi.com/v2/query/video_generation/task-456"
