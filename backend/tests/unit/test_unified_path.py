"""Worker dispatch behavior, independent of private helper spellings and source layout."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.access.models import Project
from app.execution import product_path
from app.execution.models import GraphNode, NodeRun
from app.shared.errors import ValidationAppError
from sqlalchemy.ext.asyncio import AsyncSession


def test_unified_path_has_stable_execution_version():
    assert product_path.UNIFIED_PATH_VERSION == "unified-v1"


@pytest.mark.parametrize("node_type", ["keyframe", "video"])
@pytest.mark.parametrize("ownership_available", [True, False])
async def test_media_dispatch_preserves_identity_and_requires_ownership(
    monkeypatch, node_type, ownership_available,
):
    run_id, node_id, project_id = uuid4(), uuid4(), uuid4()
    run = NodeRun(
        id=run_id, graph_node_id=node_id, project_id=project_id, status="running",
        input_snapshot={"plan": {"prompt": "frozen prompt"}},
    )
    node = GraphNode(id=node_id, node_type=node_type, node_key=node_type)
    session = AsyncMock(spec=AsyncSession)
    session.get.side_effect = [run, node]
    session.scalar.side_effect = [Project(id=project_id), None]
    ownership = AsyncMock(return_value=project_id if ownership_available else None)
    monkeypatch.setattr(product_path, "set_node_run_rls_context", ownership)
    expected = object()
    runtime = AsyncMock(return_value=expected)
    monkeypatch.setattr(product_path, "_execute_unified_media_node_run", runtime)
    store = object()
    operation = product_path.execute_media_node_run(
        session, node_run_id=run_id, store=store,
        canonical_image_bytes=b"synthetic canonical", already_claimed=True,
    )
    if not ownership_available:
        with pytest.raises(ValidationAppError, match="ownership context"):
            await operation
        runtime.assert_not_awaited()
        return
    assert await operation is expected
    runtime.assert_awaited_once()
    args = runtime.await_args.kwargs
    assert args["run"] is run and args["node"] is node and args["obj_store"] is store
    assert args["node_type"] == node_type
    assert args["prompt"] == "frozen prompt"
    assert args["canonical_image_bytes"] == b"synthetic canonical"
    ownership.assert_awaited_once_with(session, node_run_id=run_id)
