"""V3 CapabilityRouter + strict validator tests (Phase 4).

Router integration: resolve → select → validate → dispatch, with no provider
mapping logic in the router. Validator: strict fail-fast on unsupported
options / input slots / constraint violations (spec Appendix B).
"""

from __future__ import annotations

import pytest
from app.providers.capabilities import Capability
from app.providers.contracts import (
    ArtifactRef,
    ExecutionContext,
    GenerationStatus,
    ImageGenerateRequest,
    ImageToVideoRequest,
    ProviderCreateResult,
    ProviderPollResult,
)
from app.providers.errors import (
    InvalidOptionCombinationError,
    UnsupportedCapabilityError,
    UnsupportedOptionError,
)
from app.providers.manifest import (
    CapabilitySpec,
    ConditionalConstraint,
    ConstraintSpec,
    InputSlotSpec,
    ModelManifest,
    ParameterSpec,
    SubmissionSemantics,
)
from app.providers.registry import ModelRegistry, UnknownModelError
from app.providers.router import CapabilityRouter
from app.providers.validator import CapabilityValidator


class _RecorderAdapter:
    provider_id = "test"
    model_id = "test/model"

    def __init__(self, manifest: ModelManifest) -> None:
        self._manifest = manifest
        self.created: list[object] = []

    @property
    def manifest(self) -> ModelManifest:
        return self._manifest

    async def translate(
        self, capability: Capability, request: object, resolved_artifacts: object
    ) -> object:
        return {}

    async def create(self, capability: Capability, request: object, context: object) -> object:
        self.created.append(request)
        return ProviderCreateResult(
            status=GenerationStatus.SUBMITTED,
            remote_task_id="task-1",
        )

    async def poll(self, remote_task_id: str, context: object) -> object:
        return ProviderPollResult(status=GenerationStatus.SUCCEEDED)

    async def cancel(self, remote_task_id: str, context: object) -> object:
        return {"status": "cancelled"}

    async def fetch_cost(self, remote_task_id: str, context: object) -> object:
        return {"amount": 0.0}


def _image_manifest() -> ModelManifest:
    return ModelManifest(
        manifest_version="1",
        id="test/model",
        provider_id="test",
        model_name="model",
        display_name="Model",
        capability_specs={
            Capability.IMAGE_GENERATE: CapabilitySpec(
                capability=Capability.IMAGE_GENERATE,
                input_slots={
                    "reference_image": InputSlotSpec(minimum=0, maximum=1, media_types=["image/*"])
                },
                common_options={
                    "size": ParameterSpec(type="string", enum=["1024x768", "2048x2048"]),
                },
                native_options={"seed": ParameterSpec(type="integer")},
                constraints=ConstraintSpec(),
                transport_profile_id="t1",
            ),
        },
        execution_mode="sync",
        submission_semantics=SubmissionSemantics(),
    )


def _video_manifest() -> ModelManifest:
    return ModelManifest(
        manifest_version="1",
        id="test/video",
        provider_id="test",
        model_name="video",
        display_name="Video",
        capability_specs={
            Capability.VIDEO_IMAGE_TO_VIDEO: CapabilitySpec(
                capability=Capability.VIDEO_IMAGE_TO_VIDEO,
                input_slots={
                    "first_frame": InputSlotSpec(
                        required=True, minimum=1, maximum=1, media_types=["image/*"]
                    )
                },
                common_options={
                    "duration_seconds": ParameterSpec(type="number"),
                    "resolution": ParameterSpec(type="string", enum=["720p", "1080p"]),
                },
                native_options={},
                constraints=ConstraintSpec(
                    conditional=[
                        ConditionalConstraint(
                            when={"duration_seconds": 10},
                            allowed={"resolution": ["720p"]},
                        ),
                    ]
                ),
                transport_profile_id="t1",
            ),
        },
        execution_mode="async_poll",
        submission_semantics=SubmissionSemantics(),
    )


class TestValidator:
    def test_required_input_slot_missing(self) -> None:
        validator = CapabilityValidator()
        # Model requires BOTH first_frame and last_frame; an ImageToVideoRequest
        # only provides first_frame -> required slot missing.
        spec = CapabilitySpec(
            capability=Capability.VIDEO_FIRST_LAST_FRAME,
            input_slots={
                "first_frame": InputSlotSpec(required=True, minimum=1, maximum=1),
                "last_frame": InputSlotSpec(required=True, minimum=1, maximum=1),
            },
            transport_profile_id="t1",
        )
        request = ImageToVideoRequest(
            prompt="p",
            image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
        )
        with pytest.raises(InvalidOptionCombinationError):
            validator.validate(request, spec)

    def test_input_slot_too_many_references(self) -> None:
        validator = CapabilityValidator()
        spec = _image_manifest().capability_specs[Capability.IMAGE_GENERATE]
        request = ImageGenerateRequest(
            prompt="p",
            reference_images=[ArtifactRef(artifact_id="a"), ArtifactRef(artifact_id="b")],
        )
        with pytest.raises(InvalidOptionCombinationError):
            validator.validate(request, spec)

    def test_unsupported_common_option_rejected(self) -> None:
        validator = CapabilityValidator()
        spec = _image_manifest().capability_specs[Capability.IMAGE_GENERATE]
        # "seed" is declared as a native option, not a common option; passing it
        # as a top-level option must fail strict.
        with pytest.raises(UnsupportedOptionError):
            validator.validate(ImageGenerateRequest(prompt="p", seed=1), spec)

    def test_unsupported_native_option_rejected(self) -> None:
        validator = CapabilityValidator()
        spec = _image_manifest().capability_specs[Capability.IMAGE_GENERATE]
        request = ImageGenerateRequest(prompt="p", native_options={"unknown": True})
        with pytest.raises(UnsupportedOptionError):
            validator.validate(request, spec)

    def test_enum_violation_rejected(self) -> None:
        validator = CapabilityValidator()
        spec = _image_manifest().capability_specs[Capability.IMAGE_GENERATE]
        with pytest.raises(UnsupportedOptionError):
            validator.validate(ImageGenerateRequest(prompt="p", size="320x240"), spec)

    def test_conditional_duration_resolution_matrix(self) -> None:
        validator = CapabilityValidator()
        spec = _video_manifest().capability_specs[Capability.VIDEO_IMAGE_TO_VIDEO]
        frame = ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001")
        # 10s + 1080p violates the matrix (10s allows only 720p)
        with pytest.raises(InvalidOptionCombinationError):
            validator.validate(
                ImageToVideoRequest(
                    prompt="p", image=frame, duration_seconds=10, resolution="1080p"
                ),
                spec,
            )
        # 10s + 720p is allowed
        validator.validate(
            ImageToVideoRequest(prompt="p", image=frame, duration_seconds=10, resolution="720p"),
            spec,
        )


class TestRouter:
    def _router(self) -> tuple[CapabilityRouter, _RecorderAdapter]:
        registry = ModelRegistry()
        adapter = _RecorderAdapter(_image_manifest())
        registry.register(_image_manifest(), adapter)
        return CapabilityRouter(registry=registry), adapter

    async def test_dispatch_calls_adapter(self) -> None:
        router, adapter = self._router()
        result = await router.create(
            capability=Capability.IMAGE_GENERATE,
            request=ImageGenerateRequest(prompt="p"),
            context=ExecutionContext(trace_id="t"),
        )
        assert result.status == GenerationStatus.SUBMITTED
        assert len(adapter.created) == 1

    async def test_unknown_requested_model(self) -> None:
        router, _ = self._router()
        with pytest.raises(UnknownModelError):
            await router.create(
                capability=Capability.IMAGE_GENERATE,
                request=ImageGenerateRequest(prompt="p"),
                context=ExecutionContext(trace_id="t"),
                model_id="nope/model",
            )

    async def test_unsupported_capability_gate(self) -> None:
        router, _ = self._router()
        with pytest.raises(UnsupportedCapabilityError):
            await router.create(
                capability=Capability.AUDIO_TTS,
                request=ImageGenerateRequest(prompt="p"),
                context=ExecutionContext(trace_id="t"),
            )

    async def test_validation_happens_before_dispatch(self) -> None:
        router, adapter = self._router()
        with pytest.raises(UnsupportedOptionError):
            await router.create(
                capability=Capability.IMAGE_GENERATE,
                request=ImageGenerateRequest(prompt="p", size="bad"),
                context=ExecutionContext(trace_id="t"),
            )
        assert adapter.created == []

    async def test_default_selector_uses_system_default(self) -> None:
        registry = ModelRegistry()
        adapter = _RecorderAdapter(_image_manifest())
        registry.register(_image_manifest(), adapter)
        router = CapabilityRouter(registry=registry)
        # no requested_model -> system default model for IMAGE_GENERATE
        result = await router.create(
            capability=Capability.IMAGE_GENERATE,
            request=ImageGenerateRequest(prompt="p"),
            context=ExecutionContext(trace_id="t"),
        )
        assert result.status == GenerationStatus.SUBMITTED
