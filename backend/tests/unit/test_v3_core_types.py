"""V3 core-types unit tests (Phase 1). Pure-Pydantic; no ORM/Provider I/O."""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.providers.capabilities import (
    CAPABILITY_FINE_GRAINED,
    Capability,
    capability_satisfied,
)
from app.providers.contracts import (
    ArtifactRef,
    FirstLastFrameVideoRequest,
    GenerationStatus,
    ImageEditRequest,
    ImageToVideoRequest,
    ProviderCostResult,
    ProviderCreateResult,
    ReferenceToVideoRequest,
    TextGenerateRequest,
    TextToVideoRequest,
    TTSRequest,
)
from app.providers.errors import (
    ProviderErrorCode,
    SubmissionOutcomeUnknownError,
    TransportFailure,
    TransportFailureKind,
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
from app.providers.translation import EffectiveRequest, TranslationReport
from app.providers.transport import AuthSpec, PollSpec, TransportProfile
from pydantic import ValidationError


class TestCapability:
    def test_enum_values_are_stable(self) -> None:
        assert Capability.VIDEO_IMAGE_TO_VIDEO == "video.image_to_video"
        assert Capability.IMAGE_GENERATE == "image.generate"
        assert Capability.AUDIO_TTS == "audio.tts"

    def test_all_capabilities_have_fine_grained_mapping(self) -> None:
        for capability in Capability:
            assert capability in CAPABILITY_FINE_GRAINED
            assert CAPABILITY_FINE_GRAINED[capability]

    def test_capability_satisfied_or_semantics(self) -> None:
        # coarse capability satisfied by ANY fine-grained member
        assert capability_satisfied(
            Capability.VIDEO_IMAGE_TO_VIDEO, {"video.i2v.first_frame"}
        )
        assert capability_satisfied(Capability.VIDEO_IMAGE_TO_VIDEO, {"video.i2v"})
        # sibling capability is not satisfied
        assert not capability_satisfied(
            Capability.VIDEO_FIRST_LAST_FRAME, {"video.i2v.first_frame"}
        )
        assert not capability_satisfied(Capability.VIDEO_IMAGE_TO_VIDEO, {"image.t2i"})


class TestContracts:
    def test_artifact_ref(self) -> None:
        ref = ArtifactRef(artifact_id="artifact-123", revision="v2")
        assert ref.artifact_id == "artifact-123"
        assert ref.revision == "v2"

    def test_image_to_video_request(self) -> None:
        req = ImageToVideoRequest(
            prompt="人物缓慢转头",
            image=ArtifactRef(artifact_id="artifact-123"),
            duration_seconds=5,
            resolution="1080p",
            seed=42,
            native_options={"camera_fixed": True},
        )
        assert req.image.artifact_id == "artifact-123"
        assert req.duration_seconds == 5
        assert req.native_options["camera_fixed"] is True

    def test_image_to_video_requires_image(self) -> None:
        with pytest.raises(ValidationError):
            ImageToVideoRequest(prompt="no image")

    def test_first_last_frame(self) -> None:
        req = FirstLastFrameVideoRequest(
            prompt="p",
            first_frame=ArtifactRef(artifact_id="a1"),
            last_frame=ArtifactRef(artifact_id="a2"),
        )
        assert req.first_frame.artifact_id == "a1"
        assert req.last_frame.artifact_id == "a2"

    def test_reference_to_video_multiple_slots(self) -> None:
        req = ReferenceToVideoRequest(
            prompt="p",
            reference_images=[ArtifactRef(artifact_id="i1"), ArtifactRef(artifact_id="i2")],
            reference_audio=[ArtifactRef(artifact_id="a1")],
        )
        assert len(req.reference_images) == 2
        assert len(req.reference_audio) == 1
        assert req.reference_videos == []

    def test_text_and_audio_contracts(self) -> None:
        assert TextGenerateRequest(prompt="hi").prompt == "hi"
        assert TTSRequest(text="hello", voice="zh-CN-Xiaoxiao").voice == "zh-CN-Xiaoxiao"
        edit = ImageEditRequest(prompt="edit", image=ArtifactRef(artifact_id="x"))
        assert edit.image.artifact_id == "x"
        assert TextToVideoRequest(prompt="p").duration_seconds is None


class TestGenerationStatus:
    def test_vocabulary(self) -> None:
        assert GenerationStatus.SUBMIT_UNKNOWN == "submit_unknown"
        assert GenerationStatus.SUBMITTED == "submitted"
        assert GenerationStatus.CREATED == "created"


class TestManifest:
    def test_parameter_spec(self) -> None:
        spec = ParameterSpec(
            type="string",
            enum=["720p", "1080p"],
            default="1080p",
            ui_component="select",
        )
        assert spec.enum == ["720p", "1080p"]
        assert spec.ui_component == "select"

    def test_constraint_conditional_duration_resolution_matrix(self) -> None:
        constraints = ConstraintSpec(
            conditional=[
                ConditionalConstraint(
                    when={"duration_seconds": 5},
                    allowed={"resolution": ["720p", "1080p"]},
                ),
                ConditionalConstraint(
                    when={"duration_seconds": 10},
                    allowed={"resolution": ["720p"]},
                ),
            ]
        )
        assert len(constraints.conditional) == 2
        assert constraints.conditional[1].allowed["resolution"] == ["720p"]

    def test_capability_spec_slots(self) -> None:
        spec = CapabilitySpec(
            capability=Capability.VIDEO_FIRST_LAST_FRAME,
            input_slots={
                "first_frame": InputSlotSpec(required=True, minimum=1, maximum=1),
                "last_frame": InputSlotSpec(required=True, minimum=1, maximum=1),
            },
            transport_profile_id="some-video-v1",
        )
        assert spec.input_slots["first_frame"].required is True
        assert spec.transport_profile_id == "some-video-v1"

    def test_submission_semantics_default_is_not_idempotent(self) -> None:
        semantics = SubmissionSemantics()
        # paid create is NOT assumed idempotent by default (spec invariant 6)
        assert semantics.provider_idempotency_supported is False
        assert semantics.idempotency_location == "none"

    def test_model_manifest_shape(self) -> None:
        manifest = ModelManifest(
            manifest_version="1",
            id="provider/model",
            provider_id="provider",
            model_name="model",
            display_name="Model",
            capability_specs={
                Capability.VIDEO_IMAGE_TO_VIDEO: CapabilitySpec(
                    capability=Capability.VIDEO_IMAGE_TO_VIDEO,
                    transport_profile_id="t1",
                )
            },
            execution_mode="async_poll",
            submission_semantics=SubmissionSemantics(),
        )
        assert manifest.execution_mode == "async_poll"
        assert Capability.VIDEO_IMAGE_TO_VIDEO in manifest.capability_specs


class TestTransport:
    def test_transport_profile(self) -> None:
        profile = TransportProfile(
            id="ark-video-v1",
            method="POST",
            path_template="/contents/generations/tasks",
            auth=AuthSpec(scheme="bearer"),
            content_type="application/json",
            request_encoding="json",
            response_mode="async_poll",
            poll=PollSpec(method="GET", path_template="/contents/generations/tasks/{id}"),
            cancel_path_template="/contents/generations/tasks/{id}",
        )
        assert profile.response_mode == "async_poll"
        assert profile.poll is not None
        assert "{id}" in profile.poll.path_template


class TestTranslation:
    def test_translation_report(self) -> None:
        report = TranslationReport(
            requested_options={"duration_seconds": 10, "resolution": "1080p"},
            effective_options={"duration_seconds": 10, "resolution": "720p"},
        )
        assert report.effective_options["resolution"] == "720p"
        assert report.dropped_options == []

    def test_effective_request(self) -> None:
        eff = EffectiveRequest(
            capability=Capability.VIDEO_IMAGE_TO_VIDEO,
            model_id="provider/model",
            inputs={"prompt": "p"},
            common_options={"duration_seconds": 5},
        )
        assert eff.common_options["duration_seconds"] == 5


class TestTypedResults:
    def test_create_result(self) -> None:
        result = ProviderCreateResult(
            status=GenerationStatus.SUBMITTED,
            remote_task_id="task-1",
        )
        assert result.status == GenerationStatus.SUBMITTED
        assert result.remote_task_id == "task-1"

    def test_cost_result(self) -> None:
        result = ProviderCostResult(currency="USD", amount=Decimal("1.25"))
        assert result.amount == Decimal("1.25")


class TestErrors:
    def test_error_code_vocabulary(self) -> None:
        assert ProviderErrorCode.UNSUPPORTED_OPTION == "unsupported_option"
        assert ProviderErrorCode.SUBMISSION_OUTCOME_UNKNOWN == "submission_outcome_unknown"

    def test_unsupported_option_error(self) -> None:
        error = UnsupportedOptionError("seed")
        assert error.code == "unsupported_option"
        assert error.status_code == 422
        assert error.details["option"] == "seed"

    def test_unsupported_capability_error(self) -> None:
        error = UnsupportedCapabilityError("video.text_to_video")
        assert error.code == "unsupported_capability"

    def test_ambiguous_transport_failure_maps_to_submit_unknown(self) -> None:
        failure = TransportFailure(
            kind=TransportFailureKind.SUBMISSION_AMBIGUOUS,
            detail="read timeout after body sent",
        )
        assert failure.ambiguous is True
        error = failure.to_error()
        assert isinstance(error, SubmissionOutcomeUnknownError)
        assert error.code == "submission_outcome_unknown"
