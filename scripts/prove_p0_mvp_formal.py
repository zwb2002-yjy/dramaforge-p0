#!/usr/bin/env python3
"""Formal P0 evidence through the real Agent and Worker product APIs.

This script intentionally never calls script import, produce-golden, or
manual-media. A missing text, image, video, voice, queue, or worker provider
is a failed proof, not a reason to create substitute evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from evidence_context import (
    begin_evidence_context,
    default_evidence_dir,
    finish_evidence_context,
    require_ignored_evidence_path,
)

REPO = Path(__file__).resolve().parents[1]
REQUIRED_NODES = (
    "prompt",
    "keyframe",
    "face_review",
    "video",
    "video_drift_review",
    "voice",
    "subtitle",
    "composite",
    "continuity_review",
)
DONE_STATUSES = {"completed", "cached", "completed_after_cancel"}
# The canonical-reference API deliberately permits 330 seconds for a live image
# provider to recover from transient hub failures. The proof client must not
# turn that valid server-side budget into a false negative.
SYNC_PROVIDER_TIMEOUT_SECONDS = 360.0


def runtime_source_errors(
    *,
    expected_commit: str,
    health: dict[str, Any],
    runs: list[dict[str, Any]],
) -> list[str]:
    """Require the proof client, API, and every final Worker result to share one commit."""
    errors: list[str] = []
    api_commit = str(health.get("source_commit") or "")
    if api_commit != expected_commit:
        errors.append(
            f"api source_commit={api_commit or '<missing>'} expected={expected_commit}"
        )
    for run in runs:
        output = run.get("output_summary") or {}
        worker_commit = str(output.get("source_commit") or "")
        if worker_commit != expected_commit:
            errors.append(
                f"worker run={run.get('id') or '<missing>'} "
                f"source_commit={worker_commit or '<missing>'} expected={expected_commit}"
            )
    return errors


def _write_report(scratch: Path, report: dict[str, Any]) -> None:
    (scratch / "multi_shot_chain.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _problem(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    return json.dumps(body, ensure_ascii=False)[:500]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument(
        "--scratch",
        type=Path,
        default=None,
        help="Ignored or external evidence directory; defaults to tmp/p0-evidence/<sha>/formal.",
    )
    parser.add_argument(
        "--worker-tick",
        action="store_true",
        help="Use the explicitly enabled local Worker tick endpoint while polling.",
    )
    parser.add_argument("--worker-token", default="dev-worker-token")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument(
        "--resume-project-id",
        help="Resume a timed-out formal proof from this existing project; never creates media.",
    )
    parser.add_argument(
        "--resume-email",
        help="Email of the formal-proof account that owns --resume-project-id.",
    )
    parser.add_argument(
        "--project-name",
        default="P0 Formal Agent Evidence",
        help="Project name recorded in the proof; it is not a script fixture.",
    )
    parser.add_argument(
        "--idea",
        required=True,
        help="Creative idea sent to the configured text Agent provider.",
    )
    parser.add_argument(
        "--lead-name",
        required=True,
        help="Lead character name used for the canonical reference request.",
    )
    parser.add_argument(
        "--lead-prompt",
        required=True,
        help="Canonical reference prompt; secrets are not written to the report.",
    )
    args = parser.parse_args()
    idea = args.idea.strip()
    lead_name = args.lead_name.strip()
    lead_prompt = args.lead_prompt.strip()
    if not idea or not lead_name or not lead_prompt:
        parser.error("--idea, --lead-name and --lead-prompt must not be empty")
    if bool(args.resume_project_id) != bool(args.resume_email):
        parser.error("--resume-project-id and --resume-email must be supplied together")

    source_context = begin_evidence_context(REPO)
    scratch = args.scratch or default_evidence_dir(
        REPO,
        str(source_context["source_commit"]),
        "formal",
    )
    scratch = require_ignored_evidence_path(REPO, scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": 2,
        **source_context,
        "agent_workflow": True,
        "manual_media_count": 0,
        "required_nodes": list(REQUIRED_NODES),
        "worker_tick": bool(args.worker_tick),
        "resumed": bool(args.resume_project_id),
        "inputs": {
            "project_name": args.project_name.strip(),
            "idea": idea,
            "lead_name": lead_name,
            "lead_prompt_sha256": hashlib.sha256(lead_prompt.encode("utf-8")).hexdigest(),
            "lead_prompt_length": len(lead_prompt),
        },
        "steps": [],
        "ok": False,
    }
    base = args.base.rstrip("/")
    client: httpx.Client | None = None
    cookies: dict[str, str] = {}

    def finish(error: str) -> int:
        report["error"] = error
        report["ok"] = False
        report.update(finish_evidence_context(source_context, REPO))
        _write_report(scratch, report)
        print(json.dumps({"ok": False, "error": error}, ensure_ascii=False, indent=2))
        if client is not None:
            client.close()
        return 2

    if report["dirty"]:
        return finish(
            "formal evidence requires a clean worktree at the exact source commit"
        )

    client = httpx.Client(
        base_url=base,
        timeout=SYNC_PROVIDER_TIMEOUT_SECONDS,
        follow_redirects=True,
    )

    def csrf() -> str:
        assert client is not None
        response = client.get("/api/v1/auth/csrf", cookies=cookies)
        response.raise_for_status()
        cookies.update(response.cookies)
        return str(response.json()["csrf_token"])

    def post(
        path: str,
        body: dict[str, Any] | None = None,
        *,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        assert client is not None
        response = client.post(
            path,
            json=body or {},
            params=params,
            cookies=cookies,
            headers={"X-CSRF-Token": csrf(), "Content-Type": "application/json"},
        )
        cookies.update(response.cookies)
        return response

    def snapshot(project_id: str) -> dict[str, Any]:
        assert client is not None
        response = client.get(f"/api/v1/projects/{project_id}/snapshot", cookies=cookies)
        response.raise_for_status()
        return response.json()

    def tick() -> None:
        if not args.worker_tick:
            return
        assert client is not None
        response = client.post(
            "/api/v1/worker/tick",
            headers={"X-Worker-Token": args.worker_token},
        )
        if response.status_code != 200:
            raise RuntimeError(f"worker tick failed {response.status_code}: {_problem(response)}")

    def wait_for_runs(project_id: str, run_ids: list[str]) -> dict[str, Any]:
        deadline = time.monotonic() + max(1, args.timeout_seconds)
        expected = set(run_ids)
        while time.monotonic() < deadline:
            tick()
            state = snapshot(project_id)
            runs = {str(run["id"]): run for run in state.get("node_runs", [])}
            observed = [runs.get(run_id) for run_id in expected]
            if all(run is not None and run.get("status") in DONE_STATUSES for run in observed):
                return state
            failed = [
                run
                for run in observed
                if run is not None and run.get("status") == "failed"
            ]
            if failed:
                raise RuntimeError(
                    "NodeRun failed: "
                    + json.dumps(
                        [
                            {
                                "id": run["id"],
                                "error_code": run.get("error_code"),
                                "output": run.get("output_summary"),
                            }
                            for run in failed
                        ],
                        ensure_ascii=False,
                    )
                )
            time.sleep(1)
        raise RuntimeError(
            "Timed out waiting for worker artifacts. Start Arq workers or pass "
            "--worker-tick only for a local stack that intentionally exposes it."
        )

    try:
        assert client is not None
        health = client.get("/health")
        report["health"] = health.json() if health.status_code == 200 else {"status": health.status_code}
        if health.status_code != 200 or report["health"].get("db") != "up":
            return finish(f"health/db unavailable: {_problem(health)}")
        api_source_errors = runtime_source_errors(
            expected_commit=str(source_context["source_commit"]),
            health=report["health"],
            runs=[],
        )
        if api_source_errors:
            report["runtime_source"] = {
                "expected_commit": source_context["source_commit"],
                "api_source_commit": report["health"].get("source_commit"),
                "errors": api_source_errors,
            }
            return finish("; ".join(api_source_errors))

        if args.resume_project_id:
            login = client.post(
                "/api/v1/auth/login",
                json={"email": args.resume_email, "password": "password123"},
            )
            cookies.update(login.cookies)
            if login.status_code != 200:
                return finish(f"resume login failed {login.status_code}: {_problem(login)}")
            project_id = args.resume_project_id
            shot_response = client.get(
                f"/api/v1/projects/{project_id}/shots",
                cookies=cookies,
            )
            if shot_response.status_code != 200:
                return finish(
                    f"resume shot list failed {shot_response.status_code}: "
                    f"{_problem(shot_response)}"
                )
            shot_ids = [str(shot.get("id") or "") for shot in shot_response.json()]
            if len(shot_ids) != 10 or not all(shot_ids):
                return finish(
                    f"resume project must expose exactly ten shots, got {len(shot_ids)}"
                )
            state = snapshot(project_id)
            remaining_run_ids = [
                str(run["id"])
                for run in state.get("node_runs", [])
                if str((run.get("input_snapshot") or {}).get("shot_id") or "") in shot_ids
                and str((run.get("input_snapshot") or {}).get("node_key") or "")
                in set(REQUIRED_NODES) - {"keyframe"}
            ]
            if len(remaining_run_ids) != 80:
                return finish(
                    "resume project must contain exactly 80 initial non-keyframe NodeRuns, "
                    f"got {len(remaining_run_ids)}"
                )
            report["project_id"] = project_id
            report["shot_ids"] = shot_ids
            report["steps"].append(
                {
                    "resume": True,
                    "project_id": project_id,
                    "shot_count": len(shot_ids),
                    "downstream_run_count": len(remaining_run_ids),
                }
            )
        else:
            email = f"formal-{uuid4().hex[:10]}@example.com"
            registered = post(
                "/api/v1/auth/register",
                {"email": email, "password": "password123", "display_name": "Formal Proof"},
            )
            if registered.status_code not in {200, 201}:
                return finish(f"register failed {registered.status_code}: {_problem(registered)}")
            org = post("/api/v1/organizations", {"name": f"Formal-{uuid4().hex[:8]}"})
            if org.status_code not in {200, 201}:
                return finish(f"organization failed {org.status_code}: {_problem(org)}")

            created = post(
                "/api/v1/creation/start-project",
                {
                    "organization_id": org.json()["id"],
                    "name": args.project_name.strip(),
                    "aspect_ratio": "9:16",
                    "experience_mode": "workbench",
                    "idea": idea,
                },
            )
            if created.status_code not in {200, 201}:
                return finish(f"start project failed {created.status_code}: {_problem(created)}")
            project_id = str(created.json()["project_id"])
            report["project_id"] = project_id

            brief = post(
                f"/api/v1/projects/{project_id}/brief/generate",
                {
                    "idea": idea,
                    "authorize": True,
                },
            )
            report["steps"].append({"agent_brief": brief.status_code, "body": _problem(brief)})
            if brief.status_code != 200:
                return finish(
                    "Agent Brief unavailable. TEXT_LLM must be configured; "
                    f"response={brief.status_code}: {_problem(brief)}"
                )
            brief_body = brief.json()
            if brief_body.get("source") != "agent":
                return finish("Agent Brief endpoint did not report agent provenance")

            confirmed = post(
                f"/api/v1/projects/{project_id}/brief/{brief_body['id']}/confirm",
                {},
            )
            if confirmed.status_code != 200 or confirmed.json().get("status") != "confirmed":
                return finish(f"confirm brief failed {confirmed.status_code}: {_problem(confirmed)}")

            canonical = post(
                f"/api/v1/projects/{project_id}/characters/lead",
                {
                    "name": lead_name,
                    "locked_prompt": lead_prompt,
                },
            )
            report["steps"].append(
                {"canonical": canonical.status_code, "body": _problem(canonical)}
            )
            if canonical.status_code not in {200, 201}:
                return finish(
                    "Canonical reference unavailable. A live image Provider is required for "
                    f"formal face-review evidence: {_problem(canonical)}"
                )

            plan = post(
                f"/api/v1/projects/{project_id}/plans/generate",
                {"brief_revision_id": brief_body["id"], "authorize": True},
            )
            report["steps"].append({"agent_plan": plan.status_code, "body": _problem(plan)})
            if plan.status_code != 200:
                return finish(
                    "Agent Plan unavailable. TEXT_LLM must be configured; "
                    f"response={plan.status_code}: {_problem(plan)}"
                )
            plan_body = plan.json()
            shots = plan_body.get("plan", {}).get("shots", [])
            if (
                plan_body.get("source") != "agent"
                or not isinstance(shots, list)
                or len(shots) != 10
            ):
                return finish(
                    "Agent Plan must have agent provenance and exactly ten structured shots"
                )
            invalid_identity_flags = [
                shot.get("shot_number")
                for shot in shots
                if not isinstance(shot, dict)
                or not isinstance(shot.get("lead_identity_required"), bool)
            ]
            if invalid_identity_flags:
                return finish(
                    "Agent Plan must set lead_identity_required for every Shot; invalid "
                    f"shots={invalid_identity_flags}"
                )
            report["plan_id"] = plan_body["id"]

            materialized = post(
                f"/api/v1/projects/{project_id}/plans/{plan_body['id']}/confirm",
                {"materialization_ops": ["create_shot_stub", "enqueue_keyframe"]},
            )
            if materialized.status_code not in {200, 201}:
                return finish(
                    f"confirm Agent Plan failed {materialized.status_code}: "
                    f"{_problem(materialized)}"
                )
            materialization = materialized.json()
            shot_ids = [str(value) for value in materialization.get("shot_ids", [])]
            initial_run_ids = [
                str(value) for value in materialization.get("node_run_ids", [])
            ]
            if len(shot_ids) != 10 or len(initial_run_ids) != 10:
                return finish(
                    "Agent Plan confirmation did not materialize ten shots and keyframe runs"
                )
            report["shot_ids"] = shot_ids

            for node_run_id in initial_run_ids:
                enqueued = post(
                    f"/api/v1/projects/{project_id}/node-runs/{node_run_id}/enqueue",
                    {},
                )
                if enqueued.status_code not in {200, 201}:
                    return finish(
                        "initial keyframe enqueue failed "
                        f"{enqueued.status_code}: {_problem(enqueued)}"
                    )
            wait_for_runs(project_id, initial_run_ids)

            remaining_run_ids = []
            for shot_id in shot_ids:
                started = post(f"/api/v1/projects/{project_id}/shots/{shot_id}/start", {})
                report["steps"].append(
                    {"start_shot": shot_id, "status": started.status_code}
                )
                if started.status_code not in {200, 201}:
                    return finish(
                        f"shot start failed {started.status_code}: {_problem(started)}"
                    )
                remaining_run_ids.extend(
                    str(value) for value in started.json().get("run_ids", [])
                )
            if len(remaining_run_ids) != 80:
                return finish(
                    "expected 80 non-keyframe NodeRuns from ten starts, "
                    f"got {len(remaining_run_ids)}"
                )
        wait_for_runs(project_id, remaining_run_ids)

        rejected_shot_id = shot_ids[0]
        rejected = post(
            f"/api/v1/projects/{project_id}/shots/{rejected_shot_id}/reject",
            {"reason": "Formal rerun exercise: revise subtitle timing."},
        )
        if rejected.status_code != 200:
            return finish(f"review reject failed {rejected.status_code}: {_problem(rejected)}")
        rerun = post(
            f"/api/v1/projects/{project_id}/shots/{rejected_shot_id}/rerun",
            {"changed_node_key": "subtitle"},
        )
        if rerun.status_code not in {200, 201}:
            return finish(f"rerun failed {rerun.status_code}: {_problem(rerun)}")
        rerun_ids = [str(value) for value in rerun.json().get("run_ids", [])]
        if not rerun_ids:
            return finish("rerun returned no replacement NodeRuns")
        wait_for_runs(project_id, rerun_ids)

        for shot_id in shot_ids:
            approved = post(
                f"/api/v1/projects/{project_id}/shots/{shot_id}/approve",
                {"note": "formal evidence approval"},
            )
            if approved.status_code != 200:
                return finish(
                    f"shot approval failed {approved.status_code}: {_problem(approved)}"
                )

        exported = post(f"/api/v1/projects/{project_id}/exports", {})
        if exported.status_code not in {200, 201}:
            return finish(f"export failed {exported.status_code}: {_problem(exported)}")
        export = exported.json()

        granted = post(
            f"/api/v1/projects/{project_id}/exports/{export['export_id']}/download-grant",
            {},
            params={"object_role": "package"},
        )
        if granted.status_code not in {200, 201}:
            return finish(f"export grant failed {granted.status_code}: {_problem(granted)}")
        package = client.get(
            f"/api/v1/projects/{project_id}/exports/{export['export_id']}/download",
            cookies=cookies,
            params={"token": granted.json()["token"], "object_role": "package"},
        )
        if package.status_code != 200 or not package.content:
            return finish(f"package download failed {package.status_code}: {_problem(package)}")
        package_hash = hashlib.sha256(package.content).hexdigest()
        zip_names: list[str] = []
        try:
            with zipfile.ZipFile(BytesIO(package.content)) as archive:
                zip_names = archive.namelist()
        except zipfile.BadZipFile as exc:
            return finish(f"export package is not a ZIP: {exc}")

        final_state = snapshot(project_id)
        all_runs = final_state.get("node_runs", [])
        artifacts = {
            str(artifact["id"]): artifact
            for artifact in final_state.get("artifacts", [])
        }
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        manual_runs = 0
        for run in all_runs:
            run_snapshot = run.get("input_snapshot") or {}
            if run_snapshot.get("manual") is True or str(run.get("idempotency_key", "")).startswith("manual:"):
                manual_runs += 1
            shot_id = str(run_snapshot.get("shot_id") or "")
            node_key = str(run_snapshot.get("node_key") or "")
            if shot_id in shot_ids and node_key in REQUIRED_NODES:
                key = (shot_id, node_key)
                if key not in latest or int(run.get("attempt_no", 0)) > int(latest[key].get("attempt_no", 0)):
                    latest[key] = run

        missing: list[str] = []
        bad_lineage: list[str] = []
        final_artifact_ids: set[str] = set()
        final_object_keys: set[str] = set()
        for shot_id in shot_ids:
            for node_key in REQUIRED_NODES:
                run = latest.get((shot_id, node_key))
                if run is None or run.get("status") not in DONE_STATUSES:
                    missing.append(f"{shot_id}:{node_key}")
                    continue
                artifact_id = str(run.get("result_artifact_id") or "")
                artifact = artifacts.get(artifact_id)
                if not artifact or str(artifact.get("produced_by_run_id") or "") != str(run["id"]):
                    bad_lineage.append(f"{shot_id}:{node_key}")
                    continue
                final_artifact_ids.add(artifact_id)
                final_object_keys.add(str(artifact["object_key"]))

        runtime_errors = runtime_source_errors(
            expected_commit=str(source_context["source_commit"]),
            health=report["health"],
            runs=list(latest.values()),
        )
        worker_commits = sorted(
            {
                str((run.get("output_summary") or {}).get("source_commit") or "<missing>")
                for run in latest.values()
            }
        )
        report["runtime_source"] = {
            "expected_commit": source_context["source_commit"],
            "api_source_commit": report["health"].get("source_commit"),
            "worker_source_commits": worker_commits,
            "checked_worker_runs": len(latest),
            "errors": runtime_errors,
        }
        report["lineage"] = {
            "required_run_count": len(shot_ids) * len(REQUIRED_NODES),
            "resolved_latest_runs": len(latest),
            "missing_or_incomplete": missing,
            "bad_lineage": bad_lineage,
            "unique_artifact_ids": len(final_artifact_ids),
            "unique_object_keys": len(final_object_keys),
            "manual_runs": manual_runs,
        }
        report["export"] = {
            "package_hash": export.get("package_hash"),
            "download_hash": package_hash,
            "mp4_object_key": export.get("mp4_object_key"),
            "mp4_hash": export.get("mp4_hash"),
            "timeline_hash": export.get("timeline_hash"),
            "srt_hash": export.get("srt_hash"),
            "zip_names": zip_names,
        }
        report["final"] = {
            "shots": len(shot_ids),
            "node_runs": len(all_runs),
            "artifacts": len(artifacts),
            "failed_runs": len([run for run in all_runs if run.get("status") == "failed"]),
            "per_shot_full": sum(
                all((shot_id, node_key) in latest for node_key in REQUIRED_NODES)
                for shot_id in shot_ids
            ),
            "approve_ok": len(shot_ids),
            "package_hash": export.get("package_hash"),
            "mp4_hash": export.get("mp4_hash"),
            "mp4_object_key": export.get("mp4_object_key"),
        }
        report["manual_media_count"] = manual_runs
        report["ok"] = bool(
            len(shot_ids) == 10
            and manual_runs == 0
            and not missing
            and not bad_lineage
            and not runtime_errors
            and len(final_artifact_ids) == 90
            and len(final_object_keys) == 90
            and report["final"]["failed_runs"] == 0
            and package_hash == export.get("package_hash")
            and export.get("mp4_object_key")
            and export.get("mp4_hash")
            and any(name.endswith(".srt") for name in zip_names)
            and any("timeline" in name for name in zip_names)
            and any(name.startswith("media/") for name in zip_names)
        )
        report.update(finish_evidence_context(source_context, REPO))
        if not report["source_consistent"]:
            report["ok"] = False
            report["error"] = (
                "source commit or worktree cleanliness changed during formal proof"
            )
        _write_report(scratch, report)
        (scratch / "export_hashes.txt").write_text(
            "\n".join(
                [
                    f"package_hash={export.get('package_hash')}",
                    f"download_hash={package_hash}",
                    f"mp4_hash={export.get('mp4_hash')}",
                    f"mp4_object_key={export.get('mp4_object_key')}",
                    f"ok={report['ok']}",
                ]
            ),
            encoding="utf-8",
        )
        print(json.dumps(report["final"] | {"ok": report["ok"]}, ensure_ascii=False, indent=2))
        client.close()
        return 0 if report["ok"] else 2
    except Exception as exc:  # noqa: BLE001
        return finish(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
