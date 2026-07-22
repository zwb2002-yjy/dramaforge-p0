from __future__ import annotations

import pytest
from app.execution.shot_pipeline import (
    SHOT_EDGES,
    SHOT_NODE_BY_KEY,
    SHOT_NODES,
    SHOT_PIPELINE_NODES,
    shot_pipeline_definition,
)


def test_formal_shot_pipeline_has_one_consistent_definition() -> None:
    assert len(SHOT_NODES) == len(set(SHOT_NODES)) == 9
    assert tuple(node.key for node in SHOT_PIPELINE_NODES) == SHOT_NODES
    assert set(SHOT_NODE_BY_KEY) == set(SHOT_NODES)
    assert all(source in SHOT_NODE_BY_KEY for source, _target in SHOT_EDGES)
    assert all(target in SHOT_NODE_BY_KEY for _source, target in SHOT_EDGES)

    definition = shot_pipeline_definition(plan_id="plan-1")
    assert definition["plan_id"] == "plan-1"
    assert definition["nodes"] == [
        {
            "key": node.key,
            "type": node.node_type,
            "display_name": node.display_name,
        }
        for node in SHOT_PIPELINE_NODES
    ]
    assert definition["edges"] == [list(edge) for edge in SHOT_EDGES]


def test_pipeline_context_cannot_override_canonical_graph_fields() -> None:
    with pytest.raises(ValueError, match="canonical fields"):
        shot_pipeline_definition(nodes=[])
