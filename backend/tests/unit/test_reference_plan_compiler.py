"""P4-02 ReferencePlanCompiler tests (03 §32).

Covers: generic image ref; first/last; multi reference; unsupported video
reference; purpose approximate; ref count exceed; mutually exclusive.
"""

from __future__ import annotations

from uuid import uuid4

from app.production.reference_intents import (
    ShotReferenceIntent,
    compile_references,
)
from app.providers.capabilities import Capability
from app.providers.manifest import (
    CapabilitySpec,
    ConstraintSpec,
    InputSlotSpec,
    ModelManifest,
    SubmissionSemantics,
)


def _video_manifest(
    *,
    include_reference_video: bool = False,
    mutually_exclusive: list[list[str]] | None = None,
) -> ModelManifest:
    input_slots: dict[str, InputSlotSpec] = {
        "first_frame": InputSlotSpec(
            required=True, minimum=1, maximum=1, media_types=["image/*"]
        ),
        "last_frame": InputSlotSpec(
            minimum=0, maximum=1, media_types=["image/*"]
        ),
        "reference_image": InputSlotSpec(
            minimum=0, maximum=4, media_types=["image/*"]
        ),
    }
    if include_reference_video:
        input_slots["reference_video"] = InputSlotSpec(
            minimum=0, maximum=2, media_types=["video/*"]
        )
    return ModelManifest(
        manifest_version="1",
        id="agnes/video-model",
        provider_id="agnes",
        model_name="video-model",
        display_name="Video Model",
        capability_specs={
            Capability.VIDEO_IMAGE_TO_VIDEO: CapabilitySpec(
                capability=Capability.VIDEO_IMAGE_TO_VIDEO,
                transport_profile_id="t1",
                input_slots=input_slots,
                constraints=ConstraintSpec(
                    mutually_exclusive=mutually_exclusive or []
                ),
            )
        },
        execution_mode="async_poll",
        submission_semantics=SubmissionSemantics(),
    )


def _ref(
    purpose: str,
    *,
    mime: str = "image/png",
    artifact_id=None,
) -> ShotReferenceIntent:
    return ShotReferenceIntent(
        purpose=purpose,
        artifact_id=artifact_id or uuid4(),
        mime_type=mime,
    )


def test_generic_image_reference_exact() -> None:
    result = compile_references(
        manifest=_video_manifest(),
        capability=Capability.VIDEO_IMAGE_TO_VIDEO,
        references=[_ref("generic_reference")],
    )
    assert len(result.planned_references) == 1
    reference = result.planned_references[0]
    assert reference.delivery == "exact"
    assert reference.role == "reference_image"
    assert result.unsupported == []


def test_first_last_frame_exact() -> None:
    result = compile_references(
        manifest=_video_manifest(),
        capability=Capability.VIDEO_IMAGE_TO_VIDEO,
        references=[_ref("first_frame"), _ref("last_frame")],
    )
    by_purpose = {r.purpose: r for r in result.planned_references}
    assert by_purpose["first_frame"].role == "first_frame"
    assert by_purpose["first_frame"].delivery == "exact"
    assert by_purpose["last_frame"].role == "last_frame"
    assert by_purpose["last_frame"].delivery == "exact"


def test_multi_reference_preserved_in_order() -> None:
    intents = [
        _ref("identity"),
        _ref("clothing"),
        _ref("pose"),
    ]
    result = compile_references(
        manifest=_video_manifest(),
        capability=Capability.VIDEO_IMAGE_TO_VIDEO,
        references=intents,
    )
    assert [r.purpose for r in result.planned_references] == [
        "identity",
        "clothing",
        "pose",
    ]
    assert all(r.delivery == "exact" for r in result.planned_references)
    assert len(result.planned_references) == 3


def test_unsupported_video_reference_not_silently_dropped() -> None:
    # action -> reference_video, but the manifest declares no reference_video slot.
    result = compile_references(
        manifest=_video_manifest(),
        capability=Capability.VIDEO_IMAGE_TO_VIDEO,
        references=[_ref("action", mime="video/mp4")],
    )
    assert len(result.planned_references) == 1
    reference = result.planned_references[0]
    assert reference.delivery == "unsupported"
    assert reference.role == "reference_video"
    # surfaced, never silently dropped
    assert len(result.unsupported) == 1
    assert any(gap.severity == "fatal" for gap in result.capability_gaps)


def test_purpose_approximate_requires_explicit_acceptance() -> None:
    intent = _ref("camera_language", mime="video/mp4")
    strict = compile_references(
        manifest=_video_manifest(include_reference_video=True),
        capability=Capability.VIDEO_IMAGE_TO_VIDEO,
        references=[intent],
    )
    reference = strict.planned_references[0]
    assert reference.delivery == "approximate"
    assert reference.role == "reference_video"
    assert strict.accepted_approximations == []
    assert any(gap.severity == "warning" for gap in strict.capability_gaps)

    accepted = compile_references(
        manifest=_video_manifest(include_reference_video=True),
        capability=Capability.VIDEO_IMAGE_TO_VIDEO,
        references=[intent],
        accept_approximations=True,
    )
    assert accepted.accepted_approximations == ["camera_language"]
    assert not any(gap.severity == "warning" for gap in accepted.capability_gaps)


def test_ref_count_exceed() -> None:
    result = compile_references(
        manifest=_video_manifest(),
        capability=Capability.VIDEO_IMAGE_TO_VIDEO,
        references=[_ref("identity") for _ in range(5)],
    )
    exact = [r for r in result.planned_references if r.delivery == "exact"]
    unsupported = result.unsupported
    assert len(exact) == 4  # slot maximum = 4
    assert len(unsupported) == 1
    assert "exceed" in unsupported[0].reason or "exceeds" in unsupported[0].reason


def test_mutually_exclusive_groups() -> None:
    manifest = _video_manifest(
        mutually_exclusive=[["first_frame", "last_frame", "reference_image"]]
    )
    result = compile_references(
        manifest=manifest,
        capability=Capability.VIDEO_IMAGE_TO_VIDEO,
        references=[_ref("first_frame"), _ref("identity")],
    )
    # first_frame + reference_image occupy two members of one exclusive group.
    assert any(gap.severity == "fatal" for gap in result.capability_gaps)
    assert len(result.unsupported) == 2
