#!/usr/bin/env python3
"""Run one independent real-Provider professional golden sample.

The script intentionally uses the authenticated professional API rather than
calling a Provider adapter directly. It records only redacted request/result
metadata; credentials, signed URLs, and raw Provider payloads are never written.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

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


def request_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = response.text[:500]
    return json.dumps(body, ensure_ascii=False, default=str)[:1200]


def require_ok(response: httpx.Response, action: str) -> Any:
    if response.is_error:
        raise RuntimeError(f"{action} failed ({response.status_code}): {request_error(response)}")
    return response.json() if response.content else None


def public_operation(operation: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": operation.get("id"),
        "node_run_id": operation.get("node_run_id"),
        "operation_kind": operation.get("operation_kind"),
        "actual_provider": operation.get("actual_provider"),
        "actual_model": operation.get("actual_model"),
        "provider_request_id": operation.get("provider_request_id"),
        "protocol_profile": operation.get("protocol_profile"),
        "status": operation.get("status"),
        "request_fingerprint": operation.get("request_fingerprint"),
        "request_summary": operation.get("request_summary", {}),
        "response_summary": operation.get("response_summary", {}),
        "model_binding_id": operation.get("model_binding_id"),
        "catalog_entry_id": operation.get("catalog_entry_id"),
        "capability_manifest_hash": operation.get("capability_manifest_hash"),
        "execution_path_version": operation.get("execution_path_version"),
        "provider_cost": operation.get("provider_cost"),
        "currency": operation.get("currency"),
        "submitted_at": operation.get("submitted_at"),
        "completed_at": operation.get("completed_at"),
    }


def public_run(run: dict[str, Any]) -> dict[str, Any]:
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
        "model_binding_id": snapshot.get("model_binding_id"),
        "model_profile": snapshot.get("model_profile"),
        "canonical_artifact_id": snapshot.get("canonical_artifact_id"),
    }


def wait_for_nodes(
    client: httpx.Client,
    *,
    project_id: str,
    shot_id: str,
    node_keys: set[str],
    timeout_seconds: int,
    headers: Mapping[str, str],
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_snapshot: dict[str, Any] = {}
    while time.monotonic() < deadline:
        snapshot = require_ok(
            client.get(f"/projects/{project_id}/snapshot", headers=headers),
            "snapshot",
        )
        last_snapshot = snapshot
        runs = [
            run
            for run in snapshot.get("node_runs", [])
            if (run.get("input_snapshot") or {}).get("shot_id") == shot_id
            and run.get("node_key") in node_keys
        ]
        latest: dict[str, dict[str, Any]] = {}
        for run in runs:
            latest.setdefault(str(run.get("node_key")), run)
        if latest and set(latest) >= node_keys and all(
            run.get("status") in {"completed", "cached", "completed_after_cancel", "failed", "blocked"}
            for run in latest.values()
        ):
            return snapshot
        time.sleep(3)
    raise TimeoutError(
        f"timed out waiting for {sorted(node_keys)}; last runs="
        f"{[public_run(run) for run in last_snapshot.get('node_runs', [])]}"
    )


def dispatch_stage(
    client: httpx.Client,
    *,
    project_id: str,
    shot_id: str,
    stage: str,
    prompt: str,
    expected_shot_version: int,
    headers: Mapping[str, str],
    idempotency_key: str,
) -> dict[str, Any]:
    """Preview and dispatch one frozen canonical Workbench execution."""
    payload = {
        "stage": stage,
        "prompt": prompt,
        "semantic_intent": {"intent": stage, "shot_id": shot_id},
        "mode_id": "text_to_image" if stage == "image_keyframe" else "first_frame",
        "references": [],
        "expected_shot_version": expected_shot_version,
    }
    preview = require_ok(
        client.post(
            f"/projects/{project_id}/shots/{shot_id}/execution-plan",
            headers=headers,
            json=payload,
        ),
        f"preview {stage}",
    )
    return require_ok(
        client.post(
            f"/projects/{project_id}/shots/{shot_id}/executions",
            headers={**headers, "Idempotency-Key": idempotency_key},
            json={
                **payload,
                "plan_fingerprint": preview["plan_fingerprint"],
                "accepted_approximations": preview["plan"].get(
                    "accepted_approximations", []
                ),
            },
        ),
        f"dispatch {stage}",
    )


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/api/v1")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    email = os.environ.get("DRAMAFORGE_PROOF_EMAIL", "professional-proof@example.com")
    password = os.environ.get(
        "DRAMAFORGE_PROOF_PASSWORD", "professional-proof-password-2026"
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "proof": "professional-agnes-real-provider-golden-v1",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "source_commit": commit(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO)),
        "paid_provider_calls": None,
        "provider_raw_cost_fields": [],
        "steps": {},
    }

    script = """# Episode 1 - Agnes Golden

## Scene 1 - Studio / day
A single fictional character stands in a quiet studio.

### Shot 1 - medium
Visual: a fictional character looks toward the camera, subtle breathing, stable composition
Dialogue:
Camera: static
"""

    with httpx.Client(
        base_url=args.base_url,
        timeout=60.0,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        bootstrap = require_ok(client.get("/auth/bootstrap-status"), "bootstrap status")
        if bootstrap.get("owner_initialized"):
            require_ok(
                client.post("/auth/login", json={"email": email, "password": password}),
                "login",
            )
        else:
            require_ok(
                client.post(
                    "/auth/register",
                    json={"email": email, "password": password, "display_name": "Professional Proof"},
                ),
                "register",
            )
        csrf = require_ok(client.get("/auth/csrf"), "csrf") ["csrf_token"]
        workspaces = require_ok(client.get("/workspaces"), "workspaces")
        workspace_id = str(workspaces[0]["id"])
        headers = {"X-CSRF-Token": csrf, "X-Workspace-Id": workspace_id}

        project = require_ok(
            client.post(
                "/projects",
                headers=headers,
                json={
                    "workspace_id": workspace_id,
                    "name": f"Agnes Golden {uuid4().hex[:8]}",
                    "aspect_ratio": "9:16",
                    "target_platform": "general",
                },
            ),
            "create project",
        )
        project_id = str(project["id"])
        report.update({"workspace_id": workspace_id, "project_id": project_id})

        imported = require_ok(
            client.post(
                f"/projects/{project_id}/scripts/import",
                headers=headers,
                json={"filename": "agnes-golden.md", "text": script},
            ),
            "import script",
        )
        shot_id = str(imported["shot_ids"][0])
        report["shot_id"] = shot_id
        shots = require_ok(client.get(f"/projects/{project_id}/shots", headers=headers), "list shots")
        shot = next(item for item in shots if str(item["id"]) == shot_id)
        canvas = require_ok(
            client.patch(
                f"/projects/{project_id}/shots/{shot_id}/canvas",
                headers=headers,
                json={
                    "expected_version": shot["version"],
                    "visual_description": shot["visual_description"],
                    "shot_type": shot["shot_type"],
                    "camera_move": shot["camera_move"],
                    "dialogue": shot["dialogue"],
                    "duration_seconds": "5.000",
                    "source": "user",
                },
            ),
            "set shot duration",
        )
        report["steps"]["canvas_duration"] = {
            "duration_seconds": canvas["shot"]["duration_seconds"],
            "canvas_version": canvas["shot"]["version"],
        }

        connections = require_ok(
            client.get(f"/workspaces/{workspace_id}/provider-connections", headers=headers),
            "list provider connections",
        )
        connection = next(
            (item for item in connections if item.get("provider_type") == "agnes" and item.get("enabled")),
            None,
        )
        if connection is None:
            raise RuntimeError("no enabled Agnes connection found")
        connection_id = str(connection["id"])
        bindings = require_ok(
            client.get(
                f"/workspaces/{workspace_id}/provider-connections/{connection_id}/model-bindings",
                headers=headers,
            ),
            "list Agnes bindings",
        )
        selected: dict[str, dict[str, Any]] = {}
        for purpose in ("keyframe", "video"):
            binding = next(
                (
                    item
                    for item in bindings
                    if item.get("purpose") == purpose
                    and item.get("enabled")
                    and item.get("account_verified")
                ),
                None,
            )
            if binding is None:
                raise RuntimeError(f"no verified Agnes binding for {purpose}")
            selected[purpose] = binding
            require_ok(
                client.put(
                    f"/projects/{project_id}/provider-bindings/{purpose}",
                    headers=headers,
                    json={"model_binding_id": binding["id"]},
                ),
                f"bind Agnes {purpose}",
            )
        report["provider"] = {
            "connection_id": connection_id,
            "connection_verification_status": connection.get("verification_status"),
            "bindings": {
                purpose: {
                    "id": binding["id"],
                    "model_id": binding["model_id"],
                    "purpose": binding["purpose"],
                    "account_verified": binding["account_verified"],
                    "quality_gated": binding["quality_gated"],
                    "catalog_entry_id": binding.get("catalog_entry_id"),
                    "capability_manifest_hash": binding.get("capability_manifest_hash"),
                }
                for purpose, binding in selected.items()
            },
        }

        keyframe_start = dispatch_stage(
            client,
            project_id=project_id,
            shot_id=shot_id,
            stage="image_keyframe",
            prompt=shot["visual_description"],
            expected_shot_version=canvas["shot"]["version"],
            headers=headers,
            idempotency_key=f"agnes-golden-keyframe-{shot_id}",
        )
        report["steps"]["keyframe_start"] = {
            "node_run_id": keyframe_start.get("node_run_id"),
        }
        keyframe_snapshot = wait_for_nodes(
            client,
            project_id=project_id,
            shot_id=shot_id,
            node_keys={"keyframe"},
            timeout_seconds=args.timeout,
            headers=headers,
        )
        keyframe_runs = [
            public_run(run)
            for run in keyframe_snapshot.get("node_runs", [])
            if (run.get("input_snapshot") or {}).get("shot_id") == shot_id
            and run.get("node_key") in {"prompt", "keyframe", "identity_review"}
        ]
        report["steps"]["keyframe"] = {"runs": keyframe_runs}
        if any(run["status"] not in {"completed", "cached", "completed_after_cancel"} for run in keyframe_runs):
            raise RuntimeError(f"keyframe stage failed: {keyframe_runs}")

        video_start = dispatch_stage(
            client,
            project_id=project_id,
            shot_id=shot_id,
            stage="video",
            prompt=shot["visual_description"],
            expected_shot_version=canvas["shot"]["version"],
            headers=headers,
            idempotency_key=f"agnes-golden-video-{shot_id}",
        )
        report["steps"]["video_start"] = {
            "node_run_id": video_start.get("node_run_id"),
        }
        final_snapshot = wait_for_nodes(
            client,
            project_id=project_id,
            shot_id=shot_id,
            node_keys={"video"},
            timeout_seconds=args.timeout,
            headers=headers,
        )
        video_runs = [
            public_run(run)
            for run in final_snapshot.get("node_runs", [])
            if (run.get("input_snapshot") or {}).get("shot_id") == shot_id
            and run.get("node_key") == "video"
        ]
        report["steps"]["video"] = {"runs": video_runs}
        if any(run["status"] not in {"completed", "cached", "completed_after_cancel"} for run in video_runs):
            raise RuntimeError(f"video stage failed: {video_runs}")

        report["artifacts"] = [
            {
                "id": item.get("id"),
                "content_hash": item.get("content_hash"),
                "mime_type": item.get("mime_type"),
                "byte_size": item.get("byte_size"),
                "width": item.get("width"),
                "height": item.get("height"),
                "duration_seconds": item.get("duration_seconds"),
                "produced_by_run_id": item.get("produced_by_run_id"),
            }
            for item in final_snapshot.get("artifacts", [])
        ]
        operations = [public_operation(item) for item in final_snapshot.get("provider_operations", [])]
        report["provider_operations"] = operations
        report["provider_raw_cost_fields"] = [
            item.get("response_summary", {}).get("provider_reported_cost")
            for item in operations
            if item.get("response_summary", {}).get("provider_reported_cost") is not None
        ]
        report["paid_provider_calls"] = sum(
            1
            for item in operations
            if item.get("status") in {"submitted", "running", "succeeded", "completed"}
        )
        opencut = require_ok(
            client.get(f"/projects/{project_id}/opencut-manifest", headers=headers),
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
    report["ok"] = True
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        raise
