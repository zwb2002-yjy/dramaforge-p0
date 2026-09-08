"""No-network safety checks for the R7 acceptance evidence driver."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "r7_driver", Path(__file__).resolve().parents[3] / "scripts/prove_v1_r7_acceptance.py"
)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def test_evidence_removes_secrets_and_signed_url_queries():
    result = driver.sanitized(
        {
            "password": "hidden",
            "headers": {"X-Api-Key": "hidden", "X-CSRF-Token": "hidden"},
            "url": "https://user:pass@example.com/path?signature=secret#fragment",
            "text": "sk-abcdefghijklmnop",
        }
    )
    encoded = json.dumps(result)
    assert "hidden" not in encoded and "signature" not in encoded and "user:pass" not in encoded
    assert "https://example.com/path" in encoded and "sk-abc" not in encoded


def test_paid_phase_requires_opt_in_before_checkpoint_or_http(tmp_path):
    def forbidden(request):
        raise AssertionError("No HTTP before --real")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        run = driver.Acceptance(client, tmp_path / "state.json", real=False)
        with pytest.raises(RuntimeError, match="--real"):
            run.once("paid", "POST", "https://example.com", {}, paid=True)
        assert run.state["steps"] == {}


def test_successful_step_restores_without_reissuing_request(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "persisted-id"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        run = driver.Acceptance(client, tmp_path / "state.json", real=True)
        first = run.once("paid", "POST", "https://example.com", {}, paid=True)
        reloaded = driver.Acceptance(client, tmp_path / "state.json", real=True)
        assert reloaded.once("paid", "POST", "https://example.com", {}, paid=True) == first
        assert len(requests) == 1


def test_unknown_submission_never_replays(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("controlled unknown")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        run = driver.Acceptance(client, tmp_path / "state.json", real=True)
        with pytest.raises(RuntimeError, match="Unknown outcome"):
            run.once("paid", "POST", "https://example.com", {}, paid=True)
        with pytest.raises(RuntimeError, match="do not replay"):
            run.once("paid", "POST", "https://example.com", {}, paid=True)
        assert len(requests) == 1 and run.state["steps"]["paid"]["status"] == "unknown"


def test_editing_operations_are_applied_to_draft_before_explicit_save():
    timeline = {
        "clips": [
            {"id": "clip-a", "shot_id": "shot-a", "order": 1, "subtitle": "old-a"},
            {"id": "clip-b", "shot_id": "shot-b", "order": 2, "subtitle": "old-b"},
        ],
        "metadata": {},
    }

    result = driver.apply_editing_operations(
        timeline,
        [
            {"operation": "set_clip_subtitle", "clip_id": "shot-a", "subtitle": "adopted"},
            {"operation": "reorder_clips", "clip_ids": ["clip-b", "clip-a"]},
        ],
    )

    assert timeline["clips"][0]["subtitle"] == "old-a"
    assert [clip["id"] for clip in result["clips"]] == ["clip-b", "clip-a"]
    assert [clip["order"] for clip in result["clips"]] == [1, 2]
    assert result["clips"][1]["subtitle"] == "adopted"


def test_editing_operations_fail_closed_for_unknown_target():
    with pytest.raises(RuntimeError, match="not in the saved Timeline"):
        driver.apply_editing_operations(
            {"clips": [{"id": "clip-a", "shot_id": "shot-a"}]},
            [{"operation": "set_clip_subtitle", "clip_id": "missing", "subtitle": "no"}],
        )


def test_expected_negative_response_is_checkpointed_and_not_replayed(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(403, json={"code": "CSRF_FAILED"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        run = driver.Acceptance(client, tmp_path / "state.json", real=False)
        first = run.expect_error_once(
            "csrf", "POST", "https://example.com", {}, expected_statuses={403}
        )
        second = run.expect_error_once(
            "csrf", "POST", "https://example.com", {}, expected_statuses={403}
        )

    assert first == second == {"code": "CSRF_FAILED"}
    assert len(requests) == 1


def test_recovery_proof_requires_same_remote_identity_and_zero_create_delta(tmp_path):
    with httpx.Client() as client:
        run = driver.Acceptance(client, tmp_path / "state.json", real=True)
        run.state["candidate_sha"] = "a" * 40
        run.state["review_repair"] = {"repair_run_id": "run-1"}
        run.save()
        proof = tmp_path / "recovery.json"
        proof.write_text(
            json.dumps(
                {
                    "candidate_sha": "a" * 40,
                    "repair_run_id": "run-1",
                    "provider_operation_count_before_restart": 1,
                    "provider_operation_count_after_completion": 1,
                    "additional_create_count": 0,
                    "remote_id_hash_before": "b" * 64,
                    "remote_id_hash_after": "b" * 64,
                    "worker_stopped": True,
                    "worker_restarted": True,
                    "final_status": "completed",
                }
            ),
            encoding="utf-8",
        )

        run.import_external_proof("recovery", proof)

    assert run.state["assertions"]["real_remote_recovery"] == "PASS"
