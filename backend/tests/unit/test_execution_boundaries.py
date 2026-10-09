"""Execution seams keep compilation, dispatch and paid submission separate."""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution import product_path
from app.execution.run_state import ExecuteNodeResult

EXECUTION = Path(__file__).resolve().parents[2] / "app" / "execution"


def test_worker_result_facade_preserves_type_identity() -> None:
    assert product_path.ExecuteNodeResult is ExecuteNodeResult


def test_preparation_does_not_submit_or_poll_provider_tasks() -> None:
    tree = ast.parse((EXECUTION / "media_submission.py").read_text(encoding="utf-8"))
    network_operations = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not network_operations.intersection({"submit_image", "submit_video", "poll", "cancel"})


def test_execution_implementation_does_not_import_worker_facade() -> None:
    for name in (
        "media_io",
        "artifact_inputs",
        "run_state",
        "local_nodes",
        "media_submission",
        "provider_execution",
    ):
        tree = ast.parse((EXECUTION / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "app.execution.product_path", name
            elif isinstance(node, ast.Import):
                assert all(alias.name != "app.execution.product_path" for alias in node.names), name
