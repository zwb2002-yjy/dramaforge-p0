"""S3 runtime invariants and S5 export package local tests."""

from __future__ import annotations

from uuid import uuid4

from app.delivery.export_local import build_export_package
from app.execution.runtime_invariants import RuntimeState, cancel_run, run_node


def test_cache_hit_zero_provider_cost() -> None:
    state = RuntimeState(budget_remaining=10.0)
    first = run_node(state, node_key="keyframe", input_hash="abc", cost=2.0)
    assert first.status == "completed"
    assert first.provider_ops == 1
    second = run_node(state, node_key="keyframe", input_hash="abc", cost=2.0)
    assert second.status == "cached"
    assert second.provider_ops == 0
    assert second.cost == 0.0
    assert second.artifact_id == first.artifact_id
    assert state.budget_remaining == 8.0


def test_budget_block_and_cancel() -> None:
    state = RuntimeState(budget_remaining=1.0)
    blocked = run_node(state, node_key="video", input_hash="v1", cost=5.0)
    assert blocked.status == "blocked_budget"
    ok = run_node(state, node_key="subtitle", input_hash="s1", cost=0.5)
    assert ok.status == "completed"
    assert cancel_run(state, ok.id) == "completed_after_cancel"


def test_export_package_hashes_stable() -> None:
    pid = uuid4()
    shots = [{"id": "1", "subtitle": "Hello"}, {"id": "2", "subtitle": "World"}]
    a = build_export_package(project_id=pid, shots=shots)
    b = build_export_package(project_id=pid, shots=shots)
    assert a.timeline_hash == b.timeline_hash
    assert a.srt_hash == b.srt_hash
    assert "timeline-p0-v1" in a.timeline_json
    assert "Hello" in a.srt
