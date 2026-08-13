"""V3 ModelAdapter V2 + legacy bridge translation tests (Phase 3).

Translation is pure: a V3 capability request becomes a provider-native wire body
with no I/O. The core V3 acceptance (§69.2) is exercised here: the SAME
ImageToVideoRequest produces two structurally different native payloads (Agnes
flat body vs Ark content[]), and the Adapter layer owns every difference.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from app.providers.adapters_v2 import (
    BridgeComponents,
    LegacyAdapterBridge,
    _compiler_translation_evidence,
    submission_status_to_v3,
)
from app.providers.capabilities import Capability
from app.providers.catalog_seed_data import seed_manifests_for
from app.providers.contracts import (
    ArtifactRef,
    ExecutionContext,
    GenerationStatus,
    ImageGenerateRequest,
    ImageToVideoRequest,
    ResolvedArtifact,
)
from app.providers.errors import (
    ProviderStateMappingError,
    ResumeTokenUnavailableError,
)
from app.providers.manifest import (
    ModelCapabilityManifest,
    to_v3_model_manifest,
)
from app.providers.runtime import (
    CancelResult,
    CostResult,
    PollResult,
    ProviderResumeToken,
    ResolvedReference,
    SubmissionResult,
)


def _frame() -> ResolvedArtifact:
    return ResolvedArtifact(
        artifact_id="00000000-0000-0000-0000-000000000001",
        mime_type="image/png",
        signed_url="https://cdn.example.com/frame1.png",
    )


def _uuid_of(value: str):
    from uuid import UUID

    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _bridge_for(provider_type: str, media: str) -> LegacyAdapterBridge:
    seed = seed_manifests_for(provider_type=provider_type)
    manifest = ModelCapabilityManifest.model_validate(
        seed[0] if media == "image" else seed[1]
    )
    transport_id = "ark-image-v1" if provider_type == "volcengine" and media == "image" else (
        "ark-video-v1" if provider_type == "volcengine" else (
            "minimax-cn-v1" if provider_type == "minimax" else (
            "agnes-image-v1" if media == "image" else "agnes-video-v1"
            )
        )
    )
    v3 = to_v3_model_manifest(manifest, transport_profile_id=transport_id)
    from app.providers.agnes import AgnesImageCompiler, AgnesVideoCompiler
    from app.providers.minimax import MiniMaxImageCompiler, MiniMaxVideoCompiler
    from app.providers.volcengine import ArkImageCompiler, ArkVideoCompiler

    if provider_type == "agnes":
        image_compiler: object = AgnesImageCompiler()
        video_compiler: object = AgnesVideoCompiler()
    elif provider_type == "minimax":
        image_compiler = MiniMaxImageCompiler()
        video_compiler = MiniMaxVideoCompiler()
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


class TestTranslationMiniMax:
    async def test_adaptive_wire_ratio_is_audited_as_first_frame_inheritance(self) -> None:
        bridge = _bridge_for("minimax", "video")
        request = ImageToVideoRequest(
            prompt="dialogue close-up",
            image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
            duration_seconds=5,
            resolution="768P",
            aspect_ratio="9:16",
        )
        result = await bridge.translate(
            Capability.VIDEO_IMAGE_TO_VIDEO,
            request,
            {"first_frame": _frame()},
        )

        assert result.native_request["ratio"] == "adaptive"
        assert result.native_request["duration"] == 5
        assert result.effective_request.common_options == {
            "aspect_ratio": "9:16",
            "duration_seconds": 5,
            "resolution": "768P",
            "generate_audio": False,
        }
        assert result.translation_report.effective_options == (
            result.effective_request.common_options
        )
        assert result.translation_report.transformations[0].model_dump() == {
            "field": "aspect_ratio",
            "from_value": "9:16",
            "to_value": "adaptive",
            "reason": "provider_inherits_aspect_ratio_from_first_frame",
        }

    async def test_missing_project_ratio_fails_closed(self) -> None:
        bridge = _bridge_for("minimax", "video")
        request = ImageToVideoRequest(
            prompt="dialogue close-up",
            image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
            duration_seconds=5,
        )
        with pytest.raises(ValueError, match="first-frame-inherited ratio"):
            await bridge.translate(
                Capability.VIDEO_IMAGE_TO_VIDEO,
                request,
                {"first_frame": _frame()},
            )


def test_compiler_translation_evidence_rejects_unallowlisted_secret_field() -> None:
    compiled = SimpleNamespace(
        safe_request_summary={
            "effective_common_options": {"api_key": "must-not-be-trusted"},
            "translation_transformations": [],
        }
    )
    with pytest.raises(ValueError, match="safe common options"):
        _compiler_translation_evidence(compiled)


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


class _FakeRuntime:
    """Records the compiled request the bridge submits; no real HTTP."""

    def __init__(self) -> None:
        self.submitted: list[object] = []

    async def submit_video(self, request: object) -> object:
        self.submitted.append(request)
        return SubmissionResult(
            remote_task_id="task-1",
            status="queued",
            resume_token=ProviderResumeToken(
                provider_type="test", protocol_profile="test", remote_task_id="task-1"
            ),
        )

    async def submit_image(self, request: object) -> object:
        self.submitted.append(request)
        return SubmissionResult(
            remote_task_id="task-1",
            status="succeeded",
            artifact_uri="https://cdn.example.com/out.png",
        )

    async def poll_video(self, resume: object) -> object:
        return PollResult(
            status="succeeded", artifact_uri="https://cdn.example.com/out.mp4"
        )

    async def cancel_video(self, resume: object) -> object:
        return CancelResult(
            status="cancelled"
        )

    async def fetch_cost(self, resume: object) -> object:
        return CostResult(
            amount=1.0, currency="USD"
        )


def _runtime_bridge(
    provider_type: str, media: str, *, resolver: object | None = None
) -> tuple[LegacyAdapterBridge, _FakeRuntime]:
    """Bridge with a wired fake runtime (so create/poll actually execute)."""
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
    runtime = _FakeRuntime()
    bridge = LegacyAdapterBridge(
        v3,
        BridgeComponents(
            a_b_manifest=manifest,
            image_compiler=image_compiler if media == "image" else None,
            video_compiler=video_compiler if media == "video" else None,
            runtime=runtime,
        ),
        invoke_model_value=manifest.model_id,
        resolver=resolver,  # type: ignore[arg-type]
    )
    return bridge, runtime


class TestReferenceResolverClosure:
    """BLOCK-4: the resolver's ResolvedReference must actually reach the
    compiler — URL for Ark, bytes for Agnes, both for I2I + I2V."""

    def _url_resolver(self, url: str) -> object:
        def resolver(refs: list[tuple[str, ResolvedArtifact]]) -> list[ResolvedReference]:
            return [
                ResolvedReference(
                    role=role,
                    artifact_id=_uuid_of(item.artifact_id),
                    content_url=url,
                    mime_type="image/png",
                    fingerprint="f" * 64,
                )
                for role, item in refs
            ]

        return resolver

    async def test_ark_i2v_uses_resolved_url(self) -> None:
        bridge, runtime = _runtime_bridge(
            "volcengine", "video", resolver=self._url_resolver("https://cdn.example.com/f1.png")
        )
        await bridge.create(
            Capability.VIDEO_IMAGE_TO_VIDEO,
            ImageToVideoRequest(
                prompt="p",
                image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
            ),
            ExecutionContext(trace_id="t"),
        )
        compiled = runtime.submitted[0]
        assert compiled.wire_request["content"][1]["image_url"]["url"] == "https://cdn.example.com/f1.png"

    async def test_ark_i2i_uses_resolved_url(self) -> None:
        bridge, runtime = _runtime_bridge(
            "volcengine", "image", resolver=self._url_resolver("https://cdn.example.com/ref.png")
        )
        await bridge.create(
            Capability.IMAGE_GENERATE,
            ImageGenerateRequest(
                prompt="p",
                reference_images=[
                    ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001")
                ],
            ),
            ExecutionContext(trace_id="t"),
        )
        compiled = runtime.submitted[0]
        assert compiled.wire_request["image"] == ["https://cdn.example.com/ref.png"]

    async def test_agnes_i2v_uses_resolved_bytes(self) -> None:
        fake_bytes = b"\x89PNG\r\n\x1a\nfake-image"

        def resolver(refs: list[tuple[str, ResolvedArtifact]]) -> list[ResolvedReference]:
            return [
                ResolvedReference(
                    role=role,
                    artifact_id=_uuid_of(item.artifact_id),
                    content_bytes=fake_bytes,
                    mime_type="image/png",
                    fingerprint="f" * 64,
                )
                for role, item in refs
            ]

        bridge, runtime = _runtime_bridge("agnes", "video", resolver=resolver)
        await bridge.create(
            Capability.VIDEO_IMAGE_TO_VIDEO,
            ImageToVideoRequest(
                prompt="p",
                image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
            ),
            ExecutionContext(trace_id="t"),
        )
        compiled = runtime.submitted[0]
        # Agnes embeds the reference as raw base64 in the flat body.
        assert compiled.wire_request["image"] == base64.b64encode(fake_bytes).decode("ascii")


class TestStrictStatusMapping:
    """HIGH-1: unknown provider status must never silently map to SUBMITTED."""

    def test_known_status_maps(self) -> None:
        assert submission_status_to_v3("succeeded") == GenerationStatus.SUCCEEDED
        assert submission_status_to_v3("processing") == GenerationStatus.SUBMITTED

    def test_unknown_status_raises(self) -> None:
        with pytest.raises(ProviderStateMappingError):
            submission_status_to_v3("totally_new_status")


class TestDurableResumeToken:
    """HIGH-2: poll/cancel/cost never depend on process-local memory."""

    async def test_create_returns_resume_token_in_metadata(self) -> None:
        bridge, _runtime = _runtime_bridge(
            "volcengine",
            "video",
            resolver=self._url_resolver("https://cdn.example.com/f1.png"),
        )
        result = await bridge.create(
            Capability.VIDEO_IMAGE_TO_VIDEO,
            ImageToVideoRequest(
                prompt="p",
                image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
            ),
            ExecutionContext(trace_id="t"),
        )
        token = result.provider_metadata["resume_token"]
        assert token["remote_task_id"] == "task-1"

    async def test_poll_without_token_provider_raises(self) -> None:
        bridge, _runtime = _runtime_bridge("volcengine", "video")
        with pytest.raises(ResumeTokenUnavailableError):
            await bridge.poll("task-1", ExecutionContext(trace_id="t"))

    async def test_poll_with_token_provider_delegates(self) -> None:
        bridge, runtime = _runtime_bridge("volcengine", "video")
        bridge._token_provider = lambda remote_task_id: ProviderResumeToken(
            provider_type="volcengine",
            protocol_profile="ark_cn_v1",
            remote_task_id=remote_task_id,
        )
        poll = await bridge.poll("task-1", ExecutionContext(trace_id="t"))
        assert poll.status == GenerationStatus.SUCCEEDED
        assert poll.artifact_uri == "https://cdn.example.com/out.mp4"

    def _url_resolver(self, url: str) -> object:
        def resolver(refs: list[tuple[str, ResolvedArtifact]]) -> list[ResolvedReference]:
            return [
                ResolvedReference(
                    role=role,
                    artifact_id=_uuid_of(item.artifact_id),
                    content_url=url,
                    mime_type="image/png",
                    fingerprint="f" * 64,
                )
                for role, item in refs
            ]

        return resolver
