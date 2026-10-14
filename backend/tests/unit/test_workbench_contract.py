"""Product-open contract selection for the existing Formal shot mainchain."""

from __future__ import annotations

import pytest
from app.providers.manifest import InputContractSpec, OperationManifest
from app.providers.workbench_contract import select_workbench_contract


def _video_operation() -> OperationManifest:
    return OperationManifest(
        operation="video.generate",
        capabilities=["video.i2v.first_frame", "video.reference.video"],
        input_contracts={
            "formal_frame": InputContractSpec(
                input_slots={
                    "first_frame": {
                        "minimum": 1,
                        "maximum": 1,
                        "media_types": ["image/*"],
                    }
                },
                minimum_total_references=1,
            ),
            "reference": InputContractSpec(
                input_slots={"reference_video": {"maximum": 3, "media_types": ["video/*"]}},
                minimum_total_references=1,
            ),
        },
    )


def test_formal_contract_selected_without_a_user_mode() -> None:
    selected = select_workbench_contract(
        operation=_video_operation(),
        media_kind="video",
        references=[("first_frame", "image/png")],
    )
    assert selected.contract_id == "formal_frame"
    assert selected.policy.allowed_contracts == {"formal_frame"}


@pytest.mark.parametrize(
    "references",
    [
        [],
        [("reference_video", "video/mp4")],
        [("first_frame", "image/png"), ("reference_video", "video/mp4")],
        [("first_frame", "image/png"), ("last_frame", "image/png")],
    ],
)
def test_formal_mainchain_rejects_other_combinations(
    references: list[tuple[str, str]],
) -> None:
    with pytest.raises(ValueError, match="Formal 首帧"):
        select_workbench_contract(
            operation=_video_operation(), media_kind="video", references=references
        )


def test_ambiguous_and_mime_invalid_contracts_fail_closed() -> None:
    operation = _video_operation()
    with pytest.raises(ValueError, match="matched 0"):
        select_workbench_contract(
            operation=operation,
            media_kind="video",
            references=[("first_frame", "video/mp4")],
        )
    operation.input_contracts["duplicate"] = operation.input_contracts["formal_frame"]
    with pytest.raises(ValueError, match="matched 2"):
        select_workbench_contract(
            operation=operation,
            media_kind="video",
            references=[("first_frame", "image/png")],
        )


def test_keyframe_selects_text_or_single_reference_contract() -> None:
    operation = OperationManifest(
        operation="image.generate",
        capabilities=["image.t2i", "image.i2i"],
        input_contracts={
            "text": InputContractSpec(maximum_total_references=0),
            "character": InputContractSpec(
                input_slots={"reference_image": {"minimum": 1, "maximum": 1}},
                minimum_total_references=1,
            ),
        },
    )
    assert (
        select_workbench_contract(
            operation=operation, media_kind="image", references=[]
        ).contract_id
        == "text"
    )
    assert (
        select_workbench_contract(
            operation=operation,
            media_kind="image",
            references=[("reference_image", "image/png")],
        ).contract_id
        == "character"
    )
    with pytest.raises(ValueError, match="matched 0"):
        select_workbench_contract(
            operation=operation,
            media_kind="image",
            references=[("reference_image", "image/png"), ("reference_image", "image/png")],
        )


def test_keyframe_multiple_references_follow_the_selected_contract_limit() -> None:
    operation = OperationManifest(
        operation="image.generate",
        capabilities=["image.i2i"],
        input_contracts={
            "multi_image": InputContractSpec(
                input_slots={"reference_image": {"minimum": 1, "maximum": 3}},
                minimum_total_references=1,
            )
        },
    )
    selected = select_workbench_contract(
        operation=operation,
        media_kind="image",
        references=[("reference_image", "image/png"), ("reference_image", "image/png")],
    )
    assert selected.contract_id == "multi_image"
    with pytest.raises(ValueError, match="matched 0"):
        select_workbench_contract(
            operation=operation,
            media_kind="image",
            references=[("reference_image", "image/png")] * 4,
        )
