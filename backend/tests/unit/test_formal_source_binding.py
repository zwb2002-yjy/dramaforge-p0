"""Formal proof must bind its API and Worker results to the local source commit."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

from prove_p0_mvp_formal import (  # noqa: E402
    DEFAULT_POLL_INTERVAL_SECONDS,
    SYNC_PROVIDER_TIMEOUT_SECONDS,
    latest_shot_node_runs,
    response_run_id_for_node,
    review_status,
    runtime_source_errors,
)


def test_formal_agent_flow_binds_created_workspace_before_project_start() -> None:
    script = (REPO / "scripts" / "prove_p0_mvp_formal.py").read_text(encoding="utf-8")
    workspace_binding = 'client.headers["X-Workspace-Id"] = str(org.json()["id"])'
    assert workspace_binding in script
    assert script.index(workspace_binding) < script.index(
        '"/api/v1/creation/start-project"'
    )


def test_formal_resume_flow_resolves_workspace_before_project_read() -> None:
    script = (REPO / "scripts" / "prove_p0_mvp_formal.py").read_text(encoding="utf-8")
    assert 'client.get("/api/v1/workspaces", cookies=cookies)' in script
    assert '"/api/v1/workspaces/{workspace_id}/projects"' in script
    assert script.index('"/api/v1/workspaces", cookies=cookies') < script.index(
        'f"/api/v1/projects/{project_id}/shots"'
    )
    assert 'client.headers["X-Workspace-Id"] = workspace_id' in script


def test_runtime_source_accepts_one_commit() -> None:
    assert (
        runtime_source_errors(
            expected_commit="abc123",
            health={"source_commit": "abc123"},
            runs=[
                {"id": "run-1", "output_summary": {"source_commit": "abc123"}},
                {"id": "run-2", "output_summary": {"source_commit": "abc123"}},
            ],
        )
        == []
    )


def test_runtime_source_rejects_old_api_and_worker() -> None:
    errors = runtime_source_errors(
        expected_commit="new123",
        health={"source_commit": "old123"},
        runs=[
            {"id": "run-old", "output_summary": {"source_commit": "old123"}},
            {"id": "run-missing", "output_summary": {}},
        ],
    )

    assert errors == [
        "api source_commit=old123 expected=new123",
        "worker run=run-old source_commit=old123 expected=new123",
        "worker run=run-missing source_commit=<missing> expected=new123",
    ]


def test_formal_proof_allows_canonical_provider_budget() -> None:
    assert SYNC_PROVIDER_TIMEOUT_SECONDS >= 330.0


def test_formal_proof_uses_a_bounded_non_busy_poll_interval() -> None:
    assert DEFAULT_POLL_INTERVAL_SECONDS >= 5.0


def test_latest_shot_node_runs_keeps_newest_attempt_for_each_pipeline_node() -> None:
    state = {
        "node_runs": [
            {
                "id": "old",
                "attempt_no": 1,
                "input_snapshot": {"shot_id": "shot-1", "node_key": "keyframe"},
            },
            {
                "id": "latest",
                "attempt_no": 2,
                "input_snapshot": {"shot_id": "shot-1", "node_key": "keyframe"},
            },
            {
                "id": "other-shot",
                "attempt_no": 9,
                "input_snapshot": {"shot_id": "shot-2", "node_key": "keyframe"},
            },
            {
                "id": "not-pipeline",
                "attempt_no": 9,
                "input_snapshot": {"shot_id": "shot-1", "node_key": "other"},
            },
        ]
    }

    latest = latest_shot_node_runs(state, shot_ids=["shot-1"])

    assert latest == {("shot-1", "keyframe"): state["node_runs"][1]}


def test_review_status_preserves_block_and_numeric_score() -> None:
    assert review_status(
        {"output_summary": {"status": "blocked", "face_score": "0.123"}}
    ) == ("blocked", 0.123)
    assert review_status(None) == ("missing", None)


def test_response_run_id_for_node_uses_api_order_and_rejects_mismatches() -> None:
    response = {
        "stale_nodes": ["face_review", "video"],
        "run_ids": ["face-run", "video-run"],
    }
    assert response_run_id_for_node(response, node_key="face_review") == "face-run"

    bad = {"stale_nodes": ["face_review"], "run_ids": []}
    try:
        response_run_id_for_node(bad, node_key="face_review")
    except RuntimeError as exc:
        assert "mismatched" in str(exc)
    else:
        raise AssertionError("expected mismatched re-run response to fail")
