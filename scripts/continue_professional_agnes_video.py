#!/usr/bin/env python3
"""Continue the already-submitted Agnes professional golden sample with video."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[1]


def load_env() -> None:
    path = REPO / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()


def body(response: httpx.Response, action: str) -> Any:
    if response.is_error:
        raise RuntimeError(f"{action} failed ({response.status_code}): {response.text[:1200]}")
    return response.json() if response.content else None


def run_view(run: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(run.get("input_snapshot") or {})
    return {
        "id": run.get("id"),
        "attempt_no": run.get("attempt_no"),
        "status": run.get("status"),
        "node_key": run.get("node_key"),
        "result_artifact_id": run.get("result_artifact_id"),
        "error_code": run.get("error_code"),
        "error_summary": run.get("error_summary"),
        "input_hash": run.get("input_hash"),
        "duration_seconds": snapshot.get("duration_seconds"),
        "execution_branch": snapshot.get("execution_branch"),
        "professional_trial_bootstrap_allowed": snapshot.get(
            "professional_trial_bootstrap_allowed"
        ),
        "model_binding_id": snapshot.get("model_binding_id"),
        "model_profile": snapshot.get("model_profile"),
    }


def operation_view(operation: dict[str, Any]) -> dict[str, Any]:
    return {
        key: operation.get(key)
        for key in (
            "id",
            "node_run_id",
            "operation_kind",
            "actual_provider",
            "actual_model",
            "provider_request_id",
            "protocol_profile",
            "status",
            "request_fingerprint",
            "request_summary",
            "response_summary",
            "model_binding_id",
            "catalog_entry_id",
            "capability_manifest_hash",
            "execution_path_version",
            "provider_cost",
            "currency",
            "submitted_at",
            "completed_at",
        )
    }


def wait_video(
    client: httpx.Client,
    *,
    project_id: str,
    shot_id: str,
    headers: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        snapshot = body(client.get(f"/projects/{project_id}/snapshot", headers=headers), "snapshot")
        runs = [
            run
            for run in snapshot.get("node_runs", [])
            if (run.get("input_snapshot") or {}).get("shot_id") == shot_id
            and run.get("node_key") == "video"
        ]
        if runs and runs[-1].get("status") in {
            "completed",
            "cached",
            "completed_after_cancel",
            "failed",
            "blocked",
        }:
            return snapshot
        time.sleep(3)
    raise TimeoutError("timed out waiting for video NodeRun")


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--shot-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    email = os.environ.get("DRAMAFORGE_PROOF_EMAIL", "professional-proof@example.com")
    password = os.environ.get("DRAMAFORGE_PROOF_PASSWORD", "professional-proof-password-2026")
    report: dict[str, Any] = {
        "schema_version": 1,
        "proof": "professional-agnes-real-provider-golden-v1",
        "continued_at_utc": datetime.now(UTC).isoformat(),
        "source_commit": commit(),
        "project_id": args.project_id,
        "shot_id": args.shot_id,
    }
    with httpx.Client(
        base_url="http://127.0.0.1:8080/api/v1",
        timeout=60.0,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        bootstrap = body(client.get("/auth/bootstrap-status"), "bootstrap status")
        if bootstrap.get("owner_initialized"):
            body(client.post("/auth/login", json={"email": email, "password": password}), "login")
        else:
            body(
                client.post(
                    "/auth/register",
                    json={"email": email, "password": password, "display_name": "Professional Proof"},
                ),
                "register",
            )
        csrf = body(client.get("/auth/csrf"), "csrf")["csrf_token"]
        workspaces = body(client.get("/workspaces"), "workspaces")
        workspace_id = str(workspaces[0]["id"])
        headers = {"X-CSRF-Token": csrf, "X-Workspace-Id": workspace_id}

        initial = body(client.get(f"/projects/{args.project_id}/snapshot", headers=headers), "initial snapshot")
        existing_video = [
            run
            for run in initial.get("node_runs", [])
            if (run.get("input_snapshot") or {}).get("shot_id") == args.shot_id
            and run.get("node_key") == "video"
        ]
        if existing_video:
            raise RuntimeError("video NodeRun already exists; refusing to submit a duplicate")
        keyframe = [
            run
            for run in initial.get("node_runs", [])
            if (run.get("input_snapshot") or {}).get("shot_id") == args.shot_id
            and run.get("node_key") == "keyframe"
        ]
        if not keyframe or keyframe[-1].get("status") not in {"completed", "cached", "completed_after_cancel"}:
            raise RuntimeError(f"keyframe is not complete: {[run_view(run) for run in keyframe]}")

        started = body(
            client.post(
                f"/projects/{args.project_id}/professional/shots/{args.shot_id}/start",
                headers=headers,
                json={"node_keys": ["video"]},
            ),
            "start professional video",
        )
        report["start"] = {"run_ids": started.get("run_ids", []), "job_ids": started.get("job_ids", [])}
        snapshot = wait_video(
            client,
            project_id=args.project_id,
            shot_id=args.shot_id,
            headers=headers,
            timeout_seconds=args.timeout,
        )
        video_runs = [
            run
            for run in snapshot.get("node_runs", [])
            if (run.get("input_snapshot") or {}).get("shot_id") == args.shot_id
            and run.get("node_key") == "video"
        ]
        report["video_runs"] = [run_view(run) for run in video_runs]
        report["artifacts"] = [
            {
                key: artifact.get(key)
                for key in (
                    "id",
                    "content_hash",
                    "mime_type",
                    "byte_size",
                    "width",
                    "height",
                    "duration_seconds",
                    "produced_by_run_id",
                )
            }
            for artifact in snapshot.get("artifacts", [])
        ]
        operations = [operation_view(item) for item in snapshot.get("provider_operations", [])]
        report["provider_operations"] = operations
        report["paid_provider_calls"] = sum(
            1
            for item in operations
            if item.get("status") in {"submitted", "running", "succeeded", "completed"}
        )
        opencut = body(
            client.get(f"/projects/{args.project_id}/opencut-manifest", headers=headers),
            "OpenCut manifest",
        )
        report["opencut"] = {
            "schema_version": opencut.get("schema_version"),
            "adapter": opencut.get("adapter"),
            "timeline": opencut.get("timeline"),
            "track_kinds": [track.get("kind") for track in opencut.get("tracks", [])],
            "shot_count": len(opencut.get("shots", [])),
        }
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    report["ok"] = all(
        run.get("status") in {"completed", "cached", "completed_after_cancel"}
        for run in report["video_runs"]
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
