#!/usr/bin/env python3
"""Prove the 10-shot Worker path with independently traceable final Artifacts.

The caller must supply the creative idea and script. Success requires every
final 10 x 9 NodeRun to own a completed Artifact with matching
``produced_by_run_id`` and a unique object key. This script is Worker evidence,
not a substitute for the real Agent-flow proof.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from run_p0_section31_gate import REQUIRED_NODES, evaluate_multishot_snapshot


DONE_STATUSES = {"completed", "cached", "completed_after_cancel"}


def write_report(scratch: Path, report: dict[str, Any]) -> None:
    (scratch / "multi_shot_chain.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument(
        "--idea",
        required=True,
        help="Creative input recorded on the Project; no hidden sample idea is used.",
    )
    parser.add_argument(
        "--script-file",
        type=Path,
        required=True,
        help="Explicit UTF-8 script file containing exactly ten shots.",
    )
    parser.add_argument(
        "--project-name",
        default="Ten Shot Worker Evidence",
        help="Project name recorded in the proof.",
    )
    args = parser.parse_args()

    scratch = args.scratch
    scratch.mkdir(parents=True, exist_ok=True)
    base = args.base.rstrip("/")
    idea = args.idea.strip()
    script_file = args.script_file.resolve()
    project_name = args.project_name.strip() or "Ten Shot Worker Evidence"
    if not idea:
        parser.error("--idea must not be empty")
    if not script_file.is_file():
        parser.error(f"--script-file does not exist: {script_file}")

    shot_count = 10
    node_keys = list(REQUIRED_NODES)
    report: dict[str, Any] = {
        "scope": "ten-shot Worker evidence; not a substitute for Agent evidence",
        "inputs": {
            "project_name": project_name,
            "idea_length": len(idea),
            "script_file": script_file.name,
        },
        "n_requested": shot_count,
        "node_keys": node_keys,
        "steps": [],
        "ok": False,
    }

    client = httpx.Client(base_url=base, timeout=120.0, follow_redirects=True)
    cookies: dict[str, str] = {}

    def csrf() -> str:
        response = client.get("/api/v1/auth/csrf", cookies=cookies)
        response.raise_for_status()
        cookies.update(response.cookies)
        return response.json()["csrf_token"]

    def post(path: str, body: dict[str, Any] | None = None) -> httpx.Response:
        response = client.post(
            path,
            json=body or {},
            cookies=cookies,
            headers={"X-CSRF-Token": csrf(), "Content-Type": "application/json"},
        )
        cookies.update(response.cookies)
        return response

    try:
        health = client.get("/health").json()
        report["health"] = health
        if health.get("db") != "up":
            report["error"] = "db not up"
            write_report(scratch, report)
            return 2

        email = f"ms-{uuid4().hex[:8]}@example.com"
        registered = post(
            "/api/v1/auth/register",
            {"email": email, "password": "password123", "display_name": "Worker proof"},
        )
        if registered.status_code not in (200, 201):
            report["error"] = f"register failed: {registered.status_code}"
            report["steps"].append({"register": registered.status_code, "body": registered.text[:300]})
            write_report(scratch, report)
            return 2

        organization = post(
            "/api/v1/organizations",
            {"name": f"WorkerEvidence-{uuid4().hex[:6]}"},
        )
        if organization.status_code not in (200, 201):
            report["error"] = f"organization failed: {organization.status_code}"
            report["steps"].append(
                {"organization": organization.status_code, "body": organization.text[:300]}
            )
            write_report(scratch, report)
            return 2
        organization_id = organization.json()["id"]

        created = post(
            "/api/v1/creation/start-project",
            {
                "organization_id": organization_id,
                "name": project_name,
                "aspect_ratio": "9:16",
                "experience_mode": "quick",
                "idea": idea,
            },
        )
        if created.status_code not in (200, 201):
            report["error"] = f"project creation failed: {created.status_code}"
            report["steps"].append({"project": created.status_code, "body": created.text[:300]})
            write_report(scratch, report)
            return 2
        project_id = str(created.json()["project_id"])
        report["project_id"] = project_id

        imported = post(
            f"/api/v1/projects/{project_id}/scripts/import",
            {
                "filename": script_file.name,
                "text": script_file.read_text(encoding="utf-8"),
                "register_lead": False,
            },
        )
        report["steps"].append({"import": imported.status_code, "body": imported.text[:300]})
        if imported.status_code not in (200, 201):
            report["error"] = f"script import failed: {imported.status_code}"
            write_report(scratch, report)
            return 2

        shots_response = client.get(f"/api/v1/projects/{project_id}/shots", cookies=cookies)
        shots_response.raise_for_status()
        shots = shots_response.json()
        if len(shots) != shot_count:
            report["error"] = (
                f"script must materialize exactly {shot_count} shots; got {len(shots)}"
            )
            write_report(scratch, report)
            return 2
        report["shot_ids"] = [shot["id"] for shot in shots]

        job_ids: list[str] = []
        run_ids: list[str] = []
        start_failures = 0
        for shot in shots:
            shot_id = str(shot["id"])
            started = post(
                f"/api/v1/projects/{project_id}/shots/{shot_id}/start",
                {"node_keys": node_keys},
            )
            body = started.json() if started.content else {}
            report["steps"].append(
                {"start": shot_id, "status": started.status_code, "body": str(body)[:300]}
            )
            if started.status_code not in (200, 201):
                start_failures += 1
                continue
            run_ids.extend(str(run_id) for run_id in body.get("run_ids") or [])
            shot_job_ids = [str(job_id) for job_id in body.get("job_ids") or []]
            job_ids.extend(shot_job_ids)
            if any(job_id.startswith(("local:", "error:")) for job_id in shot_job_ids):
                report["error"] = f"invalid job id returned for shot {shot_id}"
                write_report(scratch, report)
                return 2

        report["job_ids"] = job_ids
        report["run_ids"] = run_ids
        report["start_failures"] = start_failures

        statuses: dict[str, str] = {}
        for _ in range(120):
            snapshot = client.get(f"/api/v1/projects/{project_id}/snapshot", cookies=cookies)
            snapshot.raise_for_status()
            runs = snapshot.json().get("node_runs") or []
            statuses = {
                str(run["id"]): str(run["status"])
                for run in runs
                if str(run.get("id")) in set(run_ids)
            }
            completed = sum(status in DONE_STATUSES for status in statuses.values())
            failed = sum(status == "failed" for status in statuses.values())
            report["progress"] = {
                "completed": completed,
                "failed": failed,
                "statuses": statuses,
            }
            if len(statuses) == len(run_ids) and completed + failed == len(run_ids):
                break
            time.sleep(2)

        approve_ok = 0
        approve_fail = 0
        for shot in shots:
            shot_id = str(shot["id"])
            approved = post(
                f"/api/v1/projects/{project_id}/shots/{shot_id}/approve",
                {"note": "ten-shot Worker evidence"},
            )
            report["steps"].append(
                {"approve": shot_id, "status": approved.status_code, "body": approved.text[:300]}
            )
            if approved.status_code in (200, 201):
                approve_ok += 1
            else:
                approve_fail += 1

        final_snapshot_response = client.get(
            f"/api/v1/projects/{project_id}/snapshot",
            cookies=cookies,
        )
        final_snapshot_response.raise_for_status()
        final_snapshot = final_snapshot_response.json()
        final_shots_response = client.get(f"/api/v1/projects/{project_id}/shots", cookies=cookies)
        final_shots_response.raise_for_status()
        final_shots = final_shots_response.json()
        integrity = evaluate_multishot_snapshot(
            shots=final_shots,
            runs=final_snapshot.get("node_runs") or [],
            artifacts=final_snapshot.get("artifacts") or [],
        )
        report["evaluation"] = integrity
        completed = sum(status in DONE_STATUSES for status in statuses.values())
        failed = sum(status == "failed" for status in statuses.values())
        report["final"] = {
            "node_runs": len(final_snapshot.get("node_runs") or []),
            "artifacts": len(final_snapshot.get("artifacts") or []),
            "completed": completed,
            "failed": failed,
            "n_shots": len(final_shots),
            "n_jobs": len(job_ids),
            "approve_ok": approve_ok,
            "approve_fail": approve_fail,
            "start_failures": start_failures,
        }
        report["ok"] = (
            start_failures == 0
            and len(final_shots) == shot_count
            and len(job_ids) == shot_count * len(node_keys)
            and len(run_ids) == shot_count * len(node_keys)
            and all(not job_id.startswith(("local:", "error:")) for job_id in job_ids)
            and completed == len(run_ids)
            and failed == 0
            and approve_ok == shot_count
            and approve_fail == 0
            and integrity["independent_90_ok"] is True
        )
        report["chain"] = (
            "import -> start 10x9 nodes -> Outbox+Arq -> Worker -> review -> "
            "independent Artifact lineage"
        )
        write_report(scratch, report)
        (scratch / "shot_chain.json").write_text(
            json.dumps(
                {
                    "ok": report["ok"],
                    "multi": True,
                    "final_status": "completed" if report["ok"] else "incomplete",
                    "node_runs": report["final"]["node_runs"],
                    "artifacts": report["final"]["artifacts"],
                    "completed": completed,
                    "failed": failed,
                    "approve_ok": approve_ok,
                    "independent_90_ok": integrity["independent_90_ok"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(json.dumps(report["final"] | {"ok": report["ok"]}, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 2
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"{type(exc).__name__}: {exc}"
        write_report(scratch, report)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
