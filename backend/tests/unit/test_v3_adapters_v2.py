"""V3 ModelAdapter V2 + legacy bridge translation tests (Phase 3).

Translation is pure: a V3 capability request becomes a provider-native wire body
with no I/O. The core V3 acceptance (§69.2) is exercised here: the SAME
ImageToVideoRequest produces two structurally different native payloads (Agnes
flat body vs Ark content[]), and the Adapter layer owns every difference.
"""

from __future__ import annotations

import pytest
from app.providers.adapters_v2 import BridgeComponents, LegacyAdapterBridge
from app.providers.capabilities import Capability
from app.providers.catalog_seed_data import seed_manifests_for
from app.providers.contracts import ArtifactRef, ImageToVideoRequest, ResolvedArtifact
from app.providers.manifest import (
    ModelCapabilityManifest,
    to_v3_model_manifest,
)


def _frame() -> ResolvedArtifact:
    return ResolvedArtifact(
        artifact_id="00000000-0000-0000-0000-000000000001",
        mime_type="image/png",
        signed_url="https://cdn.example.com/frame1.png",
    )


def _bridge_for(provider_type: str, media: str) -> LegacyAdapterBridge:
    seed = seed_manifests_for(provider_type=provider_type)
    manifest = ModelCapabilityManifest.model_validate(
        seed[0] if media == "image" else seed[1]
    )
    transport_id = "ark-image-v1" if provider_type == "volcengine" and media == "image" else (
        "ark-video-v1" if provider_type == "volcengine" else (
            "agnes-image-v1" if media == "image" else "agnes-video-v1"
        )
    )
    v3 = to_v3_model_manifest(manifest, transport_profile_id=transport_id)
    from app.providers.agnes import AgnesImageCompiler, AgnesVideoCompiler
    from app.providers.volcengine import ArkImageCompiler, ArkVideoCompiler

    if provider_type == "agnes":
        image_compiler: object = AgnesImageCompiler()
        video_compiler: object = AgnesVideoCompiler()
    else:
        image_compiler = ArkImageCompiler()
        video_compiler = ArkVideoCompiler()
    return LegacyAdapterBridge(
        v3,
        BridgeComponents(
            a_b_manifest=manifest,
            image_compiler=image_compiler,
            video_compiler=video_compiler,
            runtime=None,
        ),
        invoke_model_value=manifest.model_id,
    )


class TestTranslationAgnes:
    async def test_image_to_video_native_body(self) -> None:
        bridge = _bridge_for("agnes", "video")
        request = ImageToVideoRequest(
            prompt="人物缓慢转头",
            image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
            duration_seconds=5,
        )
        result = await bridge.translate(
            Capability.VIDEO_IMAGE_TO_VIDEO,
            request,
            {"first_frame": _frame()},
        )
        body = result.native_request
        # Agnes flat body: model/prompt/num_frames/frame_rate/height/width/image
        assert body["model"] == "agnes-video-v2.0"
        assert body["prompt"] == "人物缓慢转头"
        assert body["num_frames"] == 121
        assert body["frame_rate"] == 24
        assert body["height"] == 1280
        assert body["width"] == 720
        assert body["image"] == "https://cdn.example.com/frame1.png"
        assert result.effective_request.capability == Capability.VIDEO_IMAGE_TO_VIDEO


class TestTranslationArk:
    async def test_image_to_video_native_body(self) -> None:
        bridge = _bridge_for("volcengine", "video")
        request = ImageToVideoRequest(
            prompt="人物缓慢转头",
            image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
        )
        result = await bridge.translate(
            Capability.VIDEO_IMAGE_TO_VIDEO,
            request,
            {"first_frame": _frame()},
        )
        body = result.native_request
        # Ark content[] body: model + content[{text}, {image_url first_frame}]
        assert body["model"] == "doubao-seedance-1-0-pro-250528"
        content = body["content"]
        assert content[0] == {"type": "text", "text": "人物缓慢转头"}
        assert content[1] == {
            "type": "image_url",
            "image_url": {"url": "https://cdn.example.com/frame1.png"},
            "role": "first_frame",
        }

    async def test_same_request_two_providers_no_business_branch(self) -> None:
        """The core V3 acceptance: identical semantic request, different payloads,
        produced purely by the Adapter layer."""
        request = ImageToVideoRequest(
            prompt="人物缓慢转头",
            image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
        )
        agnes_body = (
            await _bridge_for("agnes", "video").translate(
                Capability.VIDEO_IMAGE_TO_VIDEO,
                request,
                {"first_frame": _frame()},
            )
        ).native_request
        ark_body = (
            await _bridge_for("volcengine", "video").translate(
                Capability.VIDEO_IMAGE_TO_VIDEO,
                request,
                {"first_frame": _frame()},
            )
        ).native_request
        assert set(agnes_body) != set(ark_body)
        assert agnes_body["image"] == ark_body["content"][1]["image_url"]["url"]


class TestBridgeRefusesWithoutRuntime:
    async def test_create_requires_runtime(self) -> None:
        bridge = _bridge_for("agnes", "video")
        with pytest.raises(RuntimeError):
            # runtime=None on the bridge -> create refuses, never guesses transport
            from app.providers.contracts.common import ExecutionContext

            await bridge.create(
                Capability.VIDEO_IMAGE_TO_VIDEO,
                ImageToVideoRequest(
                    prompt="p",
                    image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
                ),
                ExecutionContext(trace_id="t"),
            )

    async def test_invalid_capability_raises(self) -> None:
        bridge = _bridge_for("agnes", "video")
        with pytest.raises(ValueError):
            await bridge.translate(
                Capability.AUDIO_TTS,
                ImageToVideoRequest(
                    prompt="p",
                    image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
                ),
                {},
            )
