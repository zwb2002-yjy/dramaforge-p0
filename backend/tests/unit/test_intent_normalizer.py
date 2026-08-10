"""Intent normalizer tests: capability derivation and fail-closed conflicts."""

from __future__ import annotations

from uuid import uuid4

from app.providers.intents import (
    ArtifactReferenceIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
)
from app.providers.normalizer import (
    normalize_reference_roles,
    normalize_video,
)


def _video_intent(**over: object) -> VideoGenerationIntentV1:
    defaults: dict[str, object] = {
        "prompt": "p",
        "selection": ModelSelectionIntent(mode="explicit_binding"),
    }
    defaults.update(over)
    return VideoGenerationIntentV1(**defaults)


def test_required_first_frame_derives_capability() -> None:
    intent = _video_intent(
        references=[
            ArtifactReferenceIntent(artifact_id=uuid4(), role="first_frame", required=True)
        ]
    )
    result = normalize_video(intent)
    assert result.ok
    assert result.required_capabilities == frozenset({"video.i2v.first_frame"})
    assert result.reference_roles == frozenset({"first_frame"})


def test_generate_audio_adds_audio_capability() -> None:
    intent = _video_intent(output={"generate_audio": True})
    result = normalize_video(intent)
    assert result.required_capabilities == frozenset({"video.audio.generate"})


def test_caller_declared_capabilities_union_with_derived() -> None:
    intent = _video_intent(
        references=[
            ArtifactReferenceIntent(artifact_id=uuid4(), role="first_frame", required=True)
        ],
        requirements={"required_capabilities": {"video.audio.generate"}},
    )
    result = normalize_video(intent)
    assert result.required_capabilities == frozenset(
        {"video.i2v.first_frame", "video.audio.generate"}
    )


def test_duplicate_reference_role_is_rejected() -> None:
    ref = ArtifactReferenceIntent(artifact_id=uuid4(), role="first_frame")
    result = normalize_video(
        _video_intent(references=[ref, ref.model_copy(update={"artifact_id": uuid4()})])
    )
    assert not result.ok
    assert any("duplicate reference role" in error for error in result.errors)


def test_preview_purpose_is_rejected_in_stage_ab() -> None:
    result = normalize_video(_video_intent(purpose="preview"))
    assert not result.ok
    assert any("preview" in error for error in result.errors)


def test_auto_selection_mode_is_rejected_in_stage_ab() -> None:
    result = normalize_video(
        _video_intent(selection=ModelSelectionIntent(mode="auto"))
    )
    assert not result.ok
    assert any("auto" in error for error in result.errors)


def test_normalize_reference_roles_maps_all_roles() -> None:
    references = [
        ArtifactReferenceIntent(artifact_id=uuid4(), role=role)
        for role in ("first_frame", "last_frame", "reference_image")
    ]
    capabilities, errors = normalize_reference_roles(references)
    assert errors == []
    assert capabilities == frozenset(
        {"video.i2v.first_frame", "video.i2v.last_frame", "video.reference.image"}
    )
