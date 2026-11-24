"""Malformed stored participation stays visible as blocked, never a page crash."""

from copy import deepcopy
from uuid import uuid4

import pytest
from app.assets.models import Shot
from app.director.workflows.workflow_read_models import build_shot_workflow_state
from tests.unit.test_workflow_planning_freeze import _one_ref_manifest


@pytest.mark.parametrize("invalid", [
    "role", "asset", "version", "importance", "duplicate", "shape",
])
def test_invalid_participation_is_explicitly_unsupported(invalid):
    entry = {"asset_id": str(uuid4()), "asset_version_id": str(uuid4()),
             "screen_role": "primary", "importance": 50}
    entries = [entry]
    if invalid == "role":
        entry["screen_role"] = "invented-role"
    elif invalid == "asset":
        entry["asset_id"] = "not-a-uuid"
    elif invalid == "version":
        entry["asset_version_id"] = "not-a-uuid"
    elif invalid == "importance":
        entry["importance"] = 101
    elif invalid == "duplicate":
        entries.append(dict(entry))
    else:
        entries = ["invalid"]
    shot = Shot(id=uuid4(), scene_id=uuid4(), project_id=uuid4(), shot_number=1, status="draft",
                director_state={"workflow_participations": entries})
    before = deepcopy(shot.director_state)
    state = build_shot_workflow_state(shot=shot, episode_id=uuid4(),
                                      assessment_manifest=_one_ref_manifest())
    assert state.capability_assessment is not None
    assert state.capability_assessment.status == "UNSUPPORTED"
    assert state.capability_assessment.reason
    assert shot.director_state == before
