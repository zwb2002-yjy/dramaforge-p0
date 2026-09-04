"""Canonical Worker-path invariants after legacy execution removal."""

from __future__ import annotations

import inspect

from app.execution.product_path import UNIFIED_PATH_VERSION, execute_media_node_run


def test_unified_path_has_stable_execution_version() -> None:
    assert UNIFIED_PATH_VERSION == "unified-v1"


def test_media_worker_dispatches_image_and_video_to_unified_runtime() -> None:
    source = inspect.getsource(execute_media_node_run)
    assert "_execute_unified_media_node_run" in source
    assert "node_type in {\"keyframe\", \"video\"}" in source
    assert "get_flux_adapter_for_workspace" not in source
    assert "DirectorWorkflow" not in source
    assert "production_batch_id" not in source
    assert "budget_reservation_id" not in source
