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


def test_unknown_free_video_is_revised_with_distinct_request_and_never_replayed(tmp_path):
    requests = []
    shot = {
        "id": "shot-1",
        "project_id": "free-project",
        "scene_id": "scene-1",
        "sort_order": 1,
        "version": 2,
        "visual_description": "original visual",
        "image_prompt": "original image",
        "video_prompt": "original unknown video",
        "formal_keyframe_artifact_id": "keyframe-1",
        "formal_video_artifact_id": None,
    }

    def handler(request):
        requests.append((request.method, request.url.path, request.headers.get("Idempotency-Key")))
        path = request.url.path
        if request.method == "GET" and path.endswith("/shots"):
            return httpx.Response(200, json=[shot])
        if request.method == "GET" and path.endswith("/workbench"):
            return httpx.Response(200, json={"shot": shot})
        if request.method == "PATCH" and path.endswith("/design"):
            body = json.loads(request.content)
            assert body["video_prompt"] == driver.FREE_UNKNOWN_VIDEO_REVISION
            shot.update(version=3, video_prompt=body["video_prompt"])
            return httpx.Response(200, json=shot)
        if request.method == "POST" and path.endswith("/execution-plan"):
            return httpx.Response(
                200,
                json={"plan": {"capability_gaps": []}, "plan_fingerprint": "plan-new"},
            )
        if request.method == "POST" and path.endswith("/executions"):
            assert request.headers["Idempotency-Key"].endswith(":video-revision-1")
            return httpx.Response(200, json={"node_run_id": "replacement-run"})
        if request.method == "GET" and path.endswith("/snapshot"):
            return httpx.Response(
                200,
                json={
                    "node_runs": [
                        {
                            "id": "replacement-run",
                            "status": "completed",
                            "result_artifact_id": "video-new",
                        }
                    ]
                },
            )
        if request.method == "POST" and path.endswith("/formal-video"):
            return httpx.Response(
                200,
                json={
                    "shot_id": "shot-1",
                    "formal_video_artifact_id": "video-new",
                    "version": 4,
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {path}")

    with httpx.Client(
        base_url="https://example.test/api/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        run = driver.Acceptance(client, tmp_path / "state.json", real=True)
        run.state.update(
            projects={"free_assist": {"id": "free-project"}},
            bindings={"video": {"id": "binding-video"}},
            unreconciled_media_submissions=[
                {
                    "project_id": "free-project",
                    "shot_id": "shot-1",
                    "stage": "video",
                    "node_run_id": "unknown-run",
                    "status": "unknown_submission",
                    "cost_status": "unknown",
                    "replay_allowed": False,
                }
            ],
        )
        run.state["steps"]["free_assist:shot-1:video:dispatch"] = {
            "request": {"prompt": "original unknown video"},
            "request_hash": "a" * 64,
            "status": "succeeded",
        }
        run.save()

        run.revise_unknown_free()

    evidence = run.state["unknown_submission_replacement"]
    assert evidence["original_replay_allowed"] is False
    assert evidence["original_cost_status"] == "unknown"
    assert evidence["replacement_request_hash"] != evidence["original_request_hash"]
    assert run.state["assertions"]["unknown_submission_not_replayed"] == "PASS"
    assert not any(key == "r7:test:shot-1:video" for _, _, key in requests if key)


def test_candidate_promotion_preserves_prior_media_source_with_bounded_proof(tmp_path):
    previous = "a" * 40
    candidate = "b" * 40
    proof_path = tmp_path / "candidate-equivalence.json"
    proof_path.write_text(
        json.dumps(
            {
                "previous_candidate": previous,
                "candidate_sha": candidate,
                "changed_paths": [
                    "backend/app/execution/artifact_lineage.py",
                    "backend/tests/integration/test_artifact_lineage_pg.py",
                    "scripts/prove_v1_r7_acceptance.py",
                ],
                "provider_submission_diff_empty": True,
                "full_quality_gate": "PASS",
                "concurrent_artifact_pg_regression": "PASS",
            }
        ),
        encoding="utf-8",
    )
    with httpx.Client() as client:
        run = driver.Acceptance(client, tmp_path / "state.json", real=True)
        run.state["candidate_sha"] = previous
        run.state["assertions"].update(
            {
                "template_auto:formal_media": "PASS",
                "free_assist:formal_media": "PASS",
            }
        )
        run.save()

        run.promote_candidate(candidate, proof_path)

    assert run.state["candidate_sha"] == candidate
    assert run.state["candidate_history"][-1]["candidate_sha"] == previous
    assert run.state["assertions"]["candidate_source_equivalence"] == "PASS"


def test_local_editing_recovery_rejects_unrelated_failure_before_http(tmp_path):
    with httpx.Client() as client:
        run = driver.Acceptance(client, tmp_path / "state.json", real=False)
        run.state["failed_run"] = {
            "id": "failed-run",
            "node_key": "video",
            "error_code": "WORKER_ERROR",
            "error_summary": "unrelated",
        }
        run.save()

        with pytest.raises(RuntimeError, match="not the known concurrent Artifact race"):
            run.recover_local_editing()
