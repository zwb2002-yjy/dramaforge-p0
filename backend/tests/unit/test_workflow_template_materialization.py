"""Materialize registered dialogue templates through the actual graph service."""

import pytest
from app.director.workflows.template_nodes import two_character_dialogue_definition
from app.production.service import GraphService
from tests.unit.test_proposal_commands import _seed


@pytest.mark.asyncio
@pytest.mark.parametrize("primary", ["character_a", "character_b"])
async def test_dialogue_template_materializes_each_reference_once(session, primary):
    project, shot, user = await _seed(session)
    definition = two_character_dialogue_definition(
        character_reference_keys=("character_a", "character_b"),
        primary_character_reference_key=primary,
        context={},
    )
    refs = [edge for edge in definition["edges"] if edge[0].startswith("character_")]
    assert refs == [[primary, "keyframe"],
                    ["character_b" if primary == "character_a" else "character_a", "keyframe"]]
    service = GraphService(session)
    graph = await service.create_graph(project_id=project.id, scope_type="shot",
        scope_entity_id=shot.id, template_key="two-character-dialogue-v1",
        created_by=user.id, definition=definition)
    materialized = await service.materialize_definition(version_id=graph.current_version_id)
    assert len(materialized.edges) == len(definition["edges"])
