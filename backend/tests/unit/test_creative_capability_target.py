"""Creative capability freeze target contract."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.api.v1.creative_capabilities import FreezeCreativeBody
from pydantic import ValidationError


def test_freeze_target_accepts_one_scene_or_shot() -> None:
    scene_id = uuid4()
    shot_id = uuid4()

    assert FreezeCreativeBody(scene_id=scene_id).scene_id == scene_id
    assert FreezeCreativeBody(shot_id=shot_id).shot_id == shot_id


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"scene_id": uuid4(), "shot_id": uuid4()},
    ],
)
def test_freeze_target_rejects_missing_or_ambiguous_target(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        FreezeCreativeBody(**payload)
