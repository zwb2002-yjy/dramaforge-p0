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


def _stub_git(monkeypatch, changed_paths):
    """Return synthetic git output for the two refs used by promotion tests."""

    class _Result:
        returncode = 0
        stdout = "\n".join(changed_paths)

    monkeypatch.setattr(driver.subprocess, "run", lambda *args, **kwargs: _Result())


def test_evidence_removes_secrets_and_signed_url_queries():
    result = driver.sanitized(
        {
            "password": "hidden",
            "headers": {"X-Api-Key": "hidden", "X-CSRF-Token": "hidden"},
            "url": "https://user:pass@example.com/path?signature=secret#fragment",
            "text": "sk-abcdefghijklmnop",
            "env": {
                "MINIO_SECRET_KEY": "hidden",
                "MINIO_ROOT_PASSWORD": "hidden",
                "LITELLM_SALT_KEY": "hidden",
            },
            "authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.c2lnbmF0dXJl",
            "token_usage": {"total_tokens": 88},
        }
    )
    encoded = json.dumps(result)
    assert "hidden" not in encoded and "signature" not in encoded and "user:pass" not in encoded
    assert "https://example.com/path" in encoded and "sk-abc" not in encoded
    assert "eyJhbGci" not in encoded
    # Useful, non-secret counters survive the stricter composite-key filter.
    assert result["token_usage"] == {"total_tokens": 88}


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

        run.import_external_proof(
            "recovery", proof, entry_port=8080, migration_head=driver.repository_migration_head()
        )

    assert run.state["assertions"]["real_remote_recovery"] == "PASS"


def test_external_runtime_proof_binds_the_candidate_migration_head(tmp_path):
    """The runtime proof must match the head this repository actually declares.

    The expected head used to be a pinned revision, so every migration added after
    it made the formal 8080 identity proof permanently unreachable.
    """
    head = driver.repository_migration_head()
    assert len(head) > 0

    with httpx.Client() as client:
        run = driver.Acceptance(client, tmp_path / "state.json", real=True)
        run.state["candidate_sha"] = "a" * 40
        run.save()
        services = {
            name: {"source_commit": "a" * 40, "healthy": True}
            for name in ("api", "dispatcher", "worker_default", "worker_heavy", "frontend")
        }
        proof = tmp_path / "runtime.json"
        body = {
            "candidate_sha": "a" * 40,
            "entry_port": driver.ENTRY_PORT,
            "migration_head": head,
            "services": services,
        }
        proof.write_text(json.dumps(body), encoding="utf-8")
        run.import_external_proof(
            "runtime", proof, entry_port=driver.ENTRY_PORT, migration_head=head
        )
        assert run.state["assertions"]["final_8080_identity"] == "PASS"

        # A proof from a different entry port or migration head is refused.
        mismatches = (
            ("entry_port", driver.ENTRY_PORT + 1),
            ("migration_head", "20260908_0060"),
        )
        for field, wrong in mismatches:
            stale = dict(body, **{field: wrong})
            proof.write_text(json.dumps(stale), encoding="utf-8")
            with pytest.raises(RuntimeError):
                run.import_external_proof(
                    "runtime", proof, entry_port=driver.ENTRY_PORT, migration_head=head
                )


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
                json={
                    "plan": {"capability_gaps": []},
                    "plan_fingerprint": "plan-new",
                    "compiler_contract_preview": {
                        "readiness": "contract_validated",
                        "wire_fingerprint": "d" * 64,
                    },
                },
            )
        if request.method == "POST" and path.endswith("/executions"):
            assert json.loads(request.content)["compiler_wire_fingerprint"] == "d" * 64
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

        decisions = []
        run.record_stage_decision = lambda *args: decisions.append(args)
        run.revise_unknown_free()

    evidence = run.state["unknown_submission_replacement"]
    assert evidence["original_replay_allowed"] is False
    assert evidence["original_cost_status"] == "unknown"
    assert evidence["replacement_request_hash"] != evidence["original_request_hash"]
    assert decisions == [
        (
            "free-revision:shot-1:video",
            "free-project",
            "shot-1",
            "video-new",
            "video_drift",
            "formal_video",
        )
    ]
    assert run.state["assertions"]["unknown_submission_not_replayed"] == "PASS"
    assert not any(key == "r7:test:shot-1:video" for _, _, key in requests if key)


def test_review_submit_uses_staged_repair_api_and_marks_only_step_as_paid(tmp_path):
    calls = []
    with httpx.Client() as client:
        run = driver.Acceptance(client, tmp_path / "state.json", real=True)
        run.state["run_key"] = "test"
        run.state["projects"] = {"template_auto": {"id": "project-1"}}
        run.shots = lambda _project_id: [{"id": "shot-1"}]
        run.shot = lambda _project_id, _shot_id: {"formal_video_artifact_id": "formal-video-1"}
        run.read = lambda _path: {"provider_operations": []}
        run.record_stage_decision = lambda *args, **kwargs: None

        responses = {
            "review:annotation": {"id": "annotation-1"},
            "review:repair-plan": {
                "annotation_count": 1,
                "repair_options": ["rerun_video"],
                "plan_hash": "a" * 64,
            },
            "review:repair-create": {"id": "repair-1"},
            "review:repair-step-plan": {
                "step_ordinal": 1,
                "plan": {"plan_fingerprint": "b" * 64},
                "compiler_contract_preview": {
                    "readiness": "contract_validated",
                    "wire_fingerprint": "d" * 64,
                },
            },
            "review:repair-submit": {"node_run_id": "repair-run-1"},
        }

        def once(name, method, path, payload, *, paid=False, command_key=None):
            calls.append((name, method, path, payload, paid, command_key))
            return responses[name]

        run.once = once
        run.review_submit()

    create = next(call for call in calls if call[0] == "review:repair-create")
    preview = next(call for call in calls if call[0] == "review:repair-step-plan")
    execute = next(call for call in calls if call[0] == "review:repair-submit")
    assert create[2].endswith("/shots/shot-1/repairs")
    assert create[3]["plan_hash"] == "a" * 64
    assert preview[2].endswith("/repairs/repair-1/step-plan")
    assert execute[2].endswith("/repairs/repair-1/steps")
    assert execute[3]["expected_plan_fingerprint"] == "b" * 64
    assert execute[3]["expected_compiler_wire_fingerprint"] == "d" * 64
    assert execute[4] is True
    assert all(call[4] is False for call in calls if call[0] != "review:repair-submit")
    assert run.state["review_repair"]["repair_id"] == "repair-1"
    assert run.state["review_repair"]["repair_run_id"] == "repair-run-1"


def test_candidate_promotion_preserves_prior_media_source_with_bounded_proof(
    tmp_path, monkeypatch
):
    previous = "a" * 40
    candidate = "b" * 40
    changed_paths = [
        "backend/app/execution/artifact_lineage.py",
        "backend/tests/integration/test_artifact_lineage_pg.py",
        "scripts/prove_v1_r7_acceptance.py",
    ]
    _stub_git(monkeypatch, changed_paths)
    proof_path = tmp_path / "candidate-equivalence.json"
    proof_path.write_text(
        json.dumps(
            {
                "previous_candidate": previous,
                "candidate_sha": candidate,
                "changed_paths": changed_paths,
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


def test_candidate_promotion_accepts_only_bounded_formal_composite_fix(tmp_path, monkeypatch):
    previous = "a" * 40
    candidate = "b" * 40
    proof_path = tmp_path / "candidate-equivalence.json"
    changed_paths = [
        "backend/app/execution/composite_media.py",
        "backend/app/execution/experiment_nodes.py",
        "backend/app/execution/local_nodes.py",
        "backend/app/production/final_film.py",
        "backend/tests/unit/test_composite_media.py",
        "backend/tests/unit/test_final_film_timeline.py",
        "backend/tests/unit/test_r7_acceptance_driver.py",
        "scripts/prove_v1_r7_acceptance.py",
    ]
    _stub_git(monkeypatch, changed_paths)
    proof_path.write_text(
        json.dumps(
            {
                "equivalence_kind": "formal_composite_repair_isolation",
                "previous_candidate": previous,
                "candidate_sha": candidate,
                "changed_paths": changed_paths,
                "provider_submission_diff_empty": True,
                "full_quality_gate": "PASS",
                "formal_composite_pin_regression": "PASS",
                "staged_repair_api_regression": "PASS",
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
    assert run.state["candidate_history"][-1]["reason"] == ("formal_composite_repair_isolation")


def test_candidate_promotion_rejects_paths_outside_the_real_diff(tmp_path, monkeypatch):
    previous = "a" * 40
    candidate = "b" * 40
    _stub_git(monkeypatch, ["backend/app/execution/artifact_lineage.py"])
    proof_path = tmp_path / "candidate-equivalence.json"
    proof_path.write_text(
        json.dumps(
            {
                "previous_candidate": previous,
                "candidate_sha": candidate,
                "changed_paths": [
                    "backend/app/execution/artifact_lineage.py",
                    "backend/tests/integration/test_artifact_lineage_pg.py",
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

        with pytest.raises(RuntimeError, match="absent from the real commit diff"):
            run.promote_candidate(candidate, proof_path)

    assert run.state["candidate_sha"] == previous


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


def test_remote_media_operations_include_canonical_keyframe_kind():
    operations = [
        {"actual_provider": "agnes", "operation_kind": "keyframe.generate"},
        {"actual_provider": "agnes", "operation_kind": "video.generate"},
        {"actual_provider": "local_tts", "operation_kind": "voice.generate"},
    ]

    assert (
        driver.Acceptance.remote_media_operations({"provider_operations": operations})
        == (operations[:2])
    )


def test_local_ffprobe_verifies_the_downloaded_bytes(tmp_path):
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg is required to build an independent probe fixture")
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=160x90:r=12",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=22050",
            "-t",
            "0.8",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(clip),
        ],
        check=True,
        capture_output=True,
    )
    probe = driver.local_ffprobe(clip.read_bytes())
    assert probe["video_codec"] == "h264"
    assert probe["audio_codec"] == "aac"
    assert 0.5 <= float(probe["duration_seconds"]) <= 1.5


def test_local_ffprobe_fails_closed_without_the_binary(monkeypatch):
    monkeypatch.setattr(driver.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="ffprobe is required"):
        driver.local_ffprobe(b"not a video")
