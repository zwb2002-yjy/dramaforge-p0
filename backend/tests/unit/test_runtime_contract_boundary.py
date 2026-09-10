"""Reject model-supplied authority and opaque runtime state at the boundary."""

from uuid import uuid4

import pytest
from app.contracts.director_runtime import ResumeSignal, RuntimeScope
from app.contracts.production_commands import ExecutionBody
from pydantic import ValidationError


@pytest.mark.parametrize("injected", ["actor_id", "workspace_id", "authorization_ref"])
def test_stage_body_cannot_claim_calling_authority(injected):
    with pytest.raises(ValidationError) as invalid:
        ExecutionBody.model_validate({
            "stage": "video", "prompt": "Move slowly", "mode_id": "image_to_video",
            "expected_shot_version": 1, "plan_fingerprint": "a" * 64,
            injected: str(uuid4()),
        })
    assert any(error["loc"] == (injected,) for error in invalid.value.errors())


@pytest.mark.parametrize("injected", ["checkpoint", "state", "messages", "tool_calls"])
def test_resume_accepts_persisted_reference_not_arbitrary_engine_state(injected):
    scope = RuntimeScope(workspace_id=uuid4(), project_id=uuid4(), actor_id=uuid4())
    with pytest.raises(ValidationError) as invalid:
        ResumeSignal.model_validate({
            "scope": scope, "turn_id": uuid4(), "signal_id": uuid4(),
            "reason": "user_decision", "reference_id": uuid4(), "expected_revision": 1,
            injected: {"next": "submit_production"},
        })
    assert any(error["loc"] == (injected,) for error in invalid.value.errors())
