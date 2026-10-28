"""Pure Director context snapshot behavior."""

from uuid import uuid4

from app.director.context_builder import DirectorContextBuilder
from app.providers.model_profiles.slots import ModelSlot


def test_context_budget_counts_utf8_bytes_and_rejects_before_turn_creation():
    import pytest
    from app.director.context_builder import MAX_CONTEXT_BYTES
    from app.shared.errors import ValidationAppError

    with pytest.raises(ValidationAppError) as caught:
        DirectorContextBuilder.build(
            workspace_id=uuid4(),
            project_id=uuid4(),
            scope_type="project",
            scope_entity_id=uuid4(),
            slot=next(iter(ModelSlot)),
            input_versions={},
            intent_snapshot={},
            context_payload={"script": "剧" * (MAX_CONTEXT_BYTES // 3)},
        )
    assert caught.value.details["code"] == "DIRECTOR_CONTEXT_TOO_LARGE"


def test_context_builder_detaches_facts_and_intent_from_caller_mutation() -> None:
    versions: dict[str, object] = {"shot": 7}
    intent: dict[str, object] = {"constraints": ["不要推近"]}
    facts: dict[str, object] = {"shot": {"visual": "白西装"}}

    snapshot = DirectorContextBuilder.build(
        workspace_id=uuid4(),
        project_id=uuid4(),
        scope_type="shot",
        scope_entity_id=uuid4(),
        slot=ModelSlot.PLANNING_STORYBOARD,
        input_versions=versions,
        intent_snapshot=intent,
        context_payload=facts,
    )
    versions["shot"] = 8
    intent["constraints"] = ["快速推近"]
    facts["shot"] = {"visual": "黑西装"}

    frozen = snapshot.as_json()
    assert frozen["input_versions"] == {"shot": 7}
    assert frozen["intent"] == {"constraints": ["不要推近"]}
    assert frozen["context"] == {"shot": {"visual": "白西装"}}
    assert frozen["slot"] == str(ModelSlot.PLANNING_STORYBOARD)
