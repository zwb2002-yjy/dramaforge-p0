"""Deterministic Director video-output capability preflight tests."""

from decimal import Decimal

from app.director.shooting_service import _video_preflight_blockers


def _h3_operation() -> dict[str, object]:
    return {
        "capabilities": ["video.i2v.first_frame"],
        "reference_constraints": {"first_frame": {"min": 1, "max": 1}},
        "output_constraints": {
            "aspect_ratio": "adaptive",
            "duration_seconds": 5,
            "resolution": "768P",
            "native_audio": False,
        },
    }


def test_h3_adaptive_ratio_and_five_second_shots_are_supported() -> None:
    for ratio in ("9:16", "16:9"):
        assert _video_preflight_blockers(
            operation_manifest=_h3_operation(),
            project_aspect_ratio=ratio,
            requested_durations=frozenset({Decimal("5")}),
        ) == []


def test_h3_rejects_storyboard_duration_not_in_discrete_model_contract() -> None:
    assert _video_preflight_blockers(
        operation_manifest=_h3_operation(),
        project_aspect_ratio="9:16",
        requested_durations=frozenset({Decimal("4"), Decimal("5")}),
    ) == ["MODEL_DURATION_UNSUPPORTED"]


def test_fractional_storyboard_duration_is_not_treated_as_integer_wire_duration() -> None:
    operation = _h3_operation()
    operation["output_constraints"] = {
        "aspect_ratio": "adaptive",
        "duration_seconds": {"allowed": [4.5, 5]},
    }
    assert _video_preflight_blockers(
        operation_manifest=operation,
        project_aspect_ratio="9:16",
        requested_durations=frozenset({Decimal("4.5")}),
    ) == ["MODEL_DURATION_UNSUPPORTED"]


def test_adaptive_ratio_without_exact_first_frame_contract_fails_closed() -> None:
    operation = _h3_operation()
    operation["reference_constraints"] = {"first_frame": {"min": 0, "max": 1}}
    assert _video_preflight_blockers(
        operation_manifest=operation,
        project_aspect_ratio="9:16",
        requested_durations=frozenset({Decimal("5")}),
    ) == ["MODEL_ASPECT_RATIO_INHERITANCE_UNVERIFIED"]


def test_unknown_duration_capability_fails_closed() -> None:
    operation = _h3_operation()
    operation["output_constraints"] = {"aspect_ratio": "adaptive"}
    assert _video_preflight_blockers(
        operation_manifest=operation,
        project_aspect_ratio="9:16",
        requested_durations=frozenset({Decimal("5")}),
    ) == ["MODEL_DURATION_UNVERIFIED"]
