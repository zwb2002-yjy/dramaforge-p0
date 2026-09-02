#!/usr/bin/env python3
"""Authenticated one-shot Professional Scene → Shot → Worker smoke proof.

This probe creates an empty project, imports an explicit script, and starts a
selected Shot through the canonical Workbench route. It never calls retired
Creation/Director APIs and never writes credentials or bearer tokens to the
evidence directory.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx


def summarize_download_grant(response: httpx.Response) -> dict[str, object]:
    """Keep an auditable authorization result without persisting its token."""

    summary: dict[str, object] = {"status": response.status_code}
    if response.status_code not in (200, 201):
        return summary
    try:
        body = response.json()
    except ValueError:
        return summary
    summary["granted"] = bool(body.get("token"))
    if body.get("expires_at") is not None:
        summary["expires_at"] = body["expires_at"]
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8080")
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--idea", required=True)
    parser.add_argument("--script-file", type=Path, required=True)
    args = parser.parse_args()
    idea = args.idea.strip()
    script_file = args.script_file.resolve()
    if not idea:
        parser.error("--idea must not be empty")
    if not script_file.is_file():
        parser.error(f"--script-file does not exist: {script_file}")
    args.scratch.mkdir(parents=True, exist_ok=True)

    base = args.base.rstrip("/")
    client = httpx.Client(base_url=base, timeout=60.0, follow_redirects=True, trust_env=False)
    cookies: dict[str, str] = {}

    def csrf() -> str:
        response = client.get("/api/v1/auth/csrf", cookies=cookies)
        response.raise_for_status()
        cookies.update(response.cookies)
        return str(response.json()["csrf_token"])

    def post(path: str, body: dict[str, object] | None = None) -> httpx.Response:
        response = client.post(
            path,
            json=body or {},
            cookies=cookies,
            headers={"X-CSRF-Token": csrf(), "Content-Type": "application/json"},
        )
        cookies.update(response.cookies)
        return response

    out: dict[str, object] = {
        "scope": "single-shot canonical workbench scheduler probe",
        "inputs": {"idea_length": len(idea), "script_file": script_file.name},
        "steps": [],
    }
    try:
        health = client.get("/health")
        health_body = health.json()
        out["health"] = health_body
        if health.status_code != 200 or health_body.get("status") != "ok":
            out.update({"ok": False, "error": "health not ok"})
            return 2

        email = f"prove-{uuid4().hex[:8]}@example.com"
        registered = post(
            "/api/v1/auth/register",
            {"email": email, "password": "password123", "display_name": "Prove"},
        )
        registered.raise_for_status()
        workspace = post("/api/v1/workspaces", {"name": f"Proof-{uuid4().hex[:6]}"})
        workspace.raise_for_status()
        workspace_id = str(workspace.json()["id"])
        scoped = {"X-Workspace-Id": workspace_id}
        client.headers.update(scoped)

        project = post(
            "/api/v1/projects",
            {"workspace_id": workspace_id, "name": "Formal Live Chain Probe", "aspect_ratio": "9:16"},
        )
        project.raise_for_status()
        project_id = str(project.json()["id"])
        out["project_id"] = project_id

        imported = post(
            f"/api/v1/projects/{project_id}/scripts/import",
            {"filename": script_file.name, "text": script_file.read_text(encoding="utf-8")},
        )
        imported.raise_for_status()
        shot_id = str(imported.json()["shot_ids"][0])
        execution_input = {
            "stage": "image_keyframe",
            "prompt": idea,
            "semantic_intent": {"intent": "shot_keyframe", "shot_id": shot_id},
            "mode_id": "text_to_image",
            "references": [],
            "expected_shot_version": 1,
        }
        preview = post(
            f"/api/v1/projects/{project_id}/shots/{shot_id}/execution-plan",
            execution_input,
        )
        preview.raise_for_status()
        started = post(
            f"/api/v1/projects/{project_id}/shots/{shot_id}/executions",
            {**execution_input, "plan_fingerprint": preview.json()["plan_fingerprint"]},
        )
        started.raise_for_status()
        out["steps"] = [
            {"register": registered.status_code},
            {"import_script": imported.status_code},
            {"preview_execution": preview.status_code},
            {"dispatch_execution": started.status_code},
        ]
        out["shot_id"] = shot_id

        deadline = time.monotonic() + 120
        final_status: str | None = None
        while time.monotonic() < deadline:
            snapshot = client.get(f"/api/v1/projects/{project_id}/snapshot", cookies=cookies)
            if snapshot.status_code == 200:
                runs = snapshot.json().get("node_runs") or []
                matching = [run for run in runs if run.get("id") == started.json().get("node_run_id")]
                if matching:
                    final_status = str(matching[0].get("status"))
                    if final_status in {"completed", "cached", "failed"}:
                        break
            time.sleep(2)
        out["snapshot"] = {"final_status": final_status}
        out["ok"] = final_status in {"completed", "cached"}
        (args.scratch / "shot_chain.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return 0 if out["ok"] else 2
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
