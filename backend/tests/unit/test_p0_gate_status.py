from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

from run_p0_section31_gate import (  # noqa: E402
    REQUIRED_NODES,
    Check,
    evaluate_multishot_snapshot,
    record_check,
)


def _complete_shot_snapshot(n: int = 10) -> tuple[list[dict], list[dict], list[dict]]:
    shots: list[dict] = []
    runs: list[dict] = []
    artifacts: list[dict] = []
    for shot_index in range(n):
        shot_id = f"shot-{shot_index}"
        shots.append({"id": shot_id, "status": "review_passed"})
        for node_index, node_key in enumerate(REQUIRED_NODES):
            run_id = f"run-{shot_index}-{node_index}"
            artifact_id = f"artifact-{shot_index}-{node_index}"
            runs.append(
                {
                    "id": run_id,
                    "attempt_no": 1,
                    "status": "completed",
                    "result_artifact_id": artifact_id,
                    "input_snapshot": {"shot_id": shot_id, "node_key": node_key},
                }
            )
            artifacts.append(
                {
                    "id": artifact_id,
                    "object_key": f"projects/test/{shot_id}/{node_key}/{artifact_id}",
                    "produced_by_run_id": run_id,
                }
            )
    return shots, runs, artifacts


def test_fail_cannot_be_overwritten_by_later_pass() -> None:
    checks: list[Check] = []
    record_check(checks, Check("3.1.5", "queue", "FAIL", "dispatch failed"))
    record_check(checks, Check("3.1.5", "queue", "PASS", "retry passed"))

    assert checks == [Check("3.1.5", "queue", "FAIL", "dispatch failed")]


def test_blocked_outweighs_pass_but_fail_outweighs_blocked() -> None:
    checks = [Check("3.1.10", "ten shots", "PASS", "snapshot loaded")]
    record_check(
        checks,
        Check("3.1.10", "ten shots", "BLOCKED", "formal proof unavailable"),
    )
    record_check(checks, Check("3.1.10", "ten shots", "FAIL", "proof mismatch"))

    assert checks == [Check("3.1.10", "ten shots", "FAIL", "proof mismatch")]


def test_unknown_gate_status_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported gate status"):
        record_check([], Check("x", "bad", "UNKNOWN", "invalid"))


def test_multishot_snapshot_requires_ninety_independent_artifacts() -> None:
    shots, runs, artifacts = _complete_shot_snapshot()

    result = evaluate_multishot_snapshot(
        shots=shots,
        runs=runs,
        artifacts=artifacts,
    )

    assert result["qualifying_shots"] == 10
    assert result["reviewed_qualifying_shots"] == 10
    assert result["unique_artifact_ids"] == 90
    assert result["unique_object_keys"] == 90
    assert result["independent_90_ok"] is True


def test_multishot_snapshot_rejects_reused_object_key() -> None:
    shots, runs, artifacts = _complete_shot_snapshot()
    artifacts[-1]["object_key"] = artifacts[0]["object_key"]

    result = evaluate_multishot_snapshot(
        shots=shots,
        runs=runs,
        artifacts=artifacts,
    )

    assert result["unique_artifact_ids"] == 90
    assert result["unique_object_keys"] == 89
    assert result["independent_90_ok"] is False


def test_multishot_snapshot_rejects_wrong_producer_lineage() -> None:
    shots, runs, artifacts = _complete_shot_snapshot()
    artifacts[0]["produced_by_run_id"] = "a-different-run"

    result = evaluate_multishot_snapshot(
        shots=shots,
        runs=runs,
        artifacts=artifacts,
    )

    assert result["qualifying_shots"] == 9
    assert result["bad_lineage"] == ["shot-0:prompt"]
    assert result["independent_90_ok"] is False


def test_multishot_snapshot_rejects_object_reuse_in_an_eleventh_shot() -> None:
    shots, runs, artifacts = _complete_shot_snapshot(11)
    artifacts[-1]["object_key"] = artifacts[0]["object_key"]

    result = evaluate_multishot_snapshot(
        shots=shots,
        runs=runs,
        artifacts=artifacts,
    )

    assert result["reviewed_qualifying_shots"] == 11
    assert result["expected_unique_outputs"] == 99
    assert result["unique_object_keys"] == 98
    assert result["independent_90_ok"] is False
