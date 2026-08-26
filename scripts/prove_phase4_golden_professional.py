#!/usr/bin/env python3
"""Phase 4 §17 Golden Professional Test (07 §17 / 03 §42).

Drives the NEW workbench execution API through one real minimal vertical slice:

    project -> scene + 2 shots -> image model -> keyframe execution plan
    -> keyframe execution -> formal keyframe -> video execution plan (formal
    keyframe injected as first_frame) -> video execution -> formal video
    -> execution trace

and asserts:

- requested == resolved == binding == actual (model identity chain)
- reference N preserved (first_frame formal keyframe in the plan)
- manifest hash / connection revision / credential revision frozen in the plan
- trace is readable and secret-free
- Negative: a profile bound to an unavailable model fails closed and creates
  NO ProviderOperation (Provider POST = 0)

Real Agnes + DeepSeek calls are authorized (Owner). Evidence is written to a
JSON report; credentials and raw provider payloads are never recorded.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
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


def wait_for_run(
    client: httpx.Client,
    *,
    base: str,
    project_id: str,
    run_id: str,
    headers: dict[str, str],
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        trace = require_ok(
            client.get(
                f"{base}/projects/{project_id}/runs/{run_id}/trace", headers=headers
            ),
            "get run trace",
        )
        last = trace
        status = trace.get("status")
        if status in {"completed", "failed", "blocked", "cancelled"}:
            artifact = trace.get("artifact") or {}
            return {
                "status": status,
                "result_artifact_id": artifact.get("artifact_id"),
                "trace": trace,
            }
        time.sleep(3)
    raise TimeoutError(f"timed out waiting for run {run_id}; last={json.dumps(last)[:500]}")


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/api/v1")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    email = os.environ.get("DRAMAFORGE_PROOF_EMAIL", "golden-p4@example.com")
    password = os.environ.get("DRAMAFORGE_PROOF_PASSWORD", "golden-p4-password-2026")
    report: dict[str, Any] = {
        "schema_version": 1,
        "proof": "phase4-golden-professional-v1",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "source_commit": commit(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO)),
        "paid_provider_calls": 0,
        "steps": [],
        "assertions": {},
        "blockers": [],
    }

    def step(name: str, ok: bool, detail: str = "") -> None:
        report["steps"].append({"name": name, "ok": bool(ok), "detail": detail[:800]})
        print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail[:200]}")

    client = httpx.Client(base_url=base, timeout=60)
    try:
        # 1) auth: cookie session + CSRF + explicit workspace (current API).
        bootstrap = require_ok(client.get("/auth/bootstrap-status"), "bootstrap-status")
        if bootstrap.get("owner_initialized"):
            require_ok(
                client.post("/auth/login", json={"email": email, "password": password}),
                "login",
            )
        else:
            require_ok(
                client.post(
                    "/auth/register",
                    json={"email": email, "password": password, "display_name": "Golden P4"},
                ),
                "register",
            )
        csrf = require_ok(client.get("/auth/csrf"), "csrf")["csrf_token"]
        workspaces = require_ok(client.get("/workspaces"), "workspaces")
        workspace_id = str(workspaces[0]["id"])
        headers = {"X-CSRF-Token": csrf, "X-Workspace-Id": workspace_id}
        step("auth", True, workspace_id)

        # 2) project
        project = require_ok(
            client.post(
                "/projects",
                headers=headers,
                json={
                    "name": f"Golden P4 {uuid4().hex[:6]}",
                    "aspect_ratio": "9:16",
                    "workspace_id": workspace_id,
                },
            ),
            "create project",
        )
        project_id = str(project["id"])
        step("project", True, project_id)

        # 3) models available
        models = require_ok(client.get("/models", headers=headers), "models")
        image_models = [m for m in models if "image.generate" in (m.get("capabilities") or [])]
        video_models = [m for m in models if "video.image_to_video" in (m.get("capabilities") or [])]
        if not image_models or len(video_models) < 2:
            report["blockers"].append(
                f"need >=1 image model and >=2 video models; got {len(image_models)}/{len(video_models)}"
            )
            step("models", False, f"image={len(image_models)} video={len(video_models)}")
            _write_report(args.out, report)
            return 2
        model_a, model_b = video_models[0]["id"], video_models[1]["id"]
        image_model = image_models[0]["id"]
        step("models", True, f"image={image_model} videoA={model_a} videoB={model_b}")

        # 4) set project profile: video = model B (image = image model)
        require_ok(
            client.put(
                f"/projects/{project_id}/model-profile",
                headers=headers,
                json={
                    "bindings": {
                        "visual.keyframe": {"model_id": image_model},
                        "video.shot": {"model_id": model_b},
                    }
                },
            ),
            "set profile",
        )
        step("profile", True, f"video={model_b}")

        # 5) create scene + shot via script import (current API).
        _ = require_ok(
            client.post(
                f"/projects/{project_id}/scripts/import",
                headers=headers,
                json={
                    "filename": "golden-p4.md",
                    "text": (
                        "# Episode 1 - Golden\n\n"
                        "Lead: Lin Xia\n\n"
                        "## Scene 1 - Studio / day\n"
                        "Golden scene.\n\n"
                        "### Shot 1 - medium\n"
                        "Visual: character portrait\n"
                        "Dialogue:\n"
                        "Camera: static\n"
                    ),
                    "register_lead": False,
                },
            ),
            "import script",
        )
        shots = require_ok(client.get(f"/projects/{project_id}/shots", headers=headers), "list shots")
        shot = next((item for item in shots if item["id"]), shots[0])
        shot_id = str(shot["id"])
        step("shot", True, shot_id)

        # 6) keyframe execution plan + execution
        kf_plan = require_ok(
            client.post(
                f"/projects/{project_id}/shots/{shot_id}/execution-plan",
                headers=headers,
                json={
                    "stage": "image_keyframe",
                    "prompt": "Cinematic keyframe, character portrait, 9:16",
                    "semantic_intent": {"intent": "shot_keyframe"},
                    "mode_id": "explicit_binding",
                },
            ),
            "keyframe execution-plan",
        )
        kf_fp = kf_plan["plan_fingerprint"]
        report["assertions"]["keyframe_fingerprint_len"] = len(kf_fp)
        step("keyframe plan", len(kf_fp) == 64, kf_fp[:12])

        kf_exec = require_ok(
            client.post(
                f"/projects/{project_id}/shots/{shot_id}/executions",
                headers={**headers, "Idempotency-Key": f"golden-kf-{uuid4().hex}"},
                json={
                    "stage": "image_keyframe",
                    "prompt": "Cinematic keyframe, character portrait, 9:16",
                    "semantic_intent": {"intent": "shot_keyframe"},
                    "mode_id": "explicit_binding",
                    "plan_fingerprint": kf_fp,
                },
            ),
            "keyframe execution",
        )
        kf_run = wait_for_run(
            client, base=base, project_id=project_id, run_id=kf_exec["node_run_id"],
            headers=headers, timeout_seconds=args.timeout,
        )
        if kf_run.get("status") != "completed":
            report["blockers"].append(f"keyframe run not completed: {kf_run.get('status')}")
            step("keyframe run", False, kf_run.get("status"))
            _write_report(args.out, report)
            return 2
        report["paid_provider_calls"] += 1
        step("keyframe run", True, kf_run.get("result_artifact_id"))

        # 7) formal keyframe
        formal_kf = require_ok(
            client.post(
                f"/projects/{project_id}/shots/{shot_id}/formal-keyframe",
                headers=headers,
                json={"artifact_id": kf_run["result_artifact_id"]},
            ),
            "formal keyframe",
        )
        step("formal keyframe", True, formal_kf["formal_keyframe_artifact_id"])

        # 8) video execution plan (formal keyframe injected as first_frame)
        video_plan = require_ok(
            client.post(
                f"/projects/{project_id}/shots/{shot_id}/execution-plan",
                headers=headers,
                json={
                    "stage": "video",
                    "prompt": "character walks into frame",
                    "semantic_intent": {"intent": "shot_video"},
                    "mode_id": "explicit_binding",
                },
            ),
            "video execution-plan",
        )
        refs = video_plan["plan"]["planned_references"]
        first_frame = [r for r in refs if r.get("purpose") == "first_frame"]
        report["assertions"]["video_first_frame_injected"] = bool(first_frame)
        report["assertions"]["video_first_frame_artifact"] = (
            first_frame[0].get("artifact_id") if first_frame else None
        )
        report["assertions"]["video_first_frame_matches_formal"] = bool(
            first_frame
            and first_frame[0].get("artifact_id") == formal_kf["formal_keyframe_artifact_id"]
        )
        resolved = video_plan["plan"]["resolved_model"]
        report["assertions"]["video_resolved_model"] = resolved.get("resolved_model_id")
        report["assertions"]["video_resolved_is_model_b"] = resolved.get(
            "resolved_model_id"
        ) == model_b
        report["assertions"]["video_manifest_hash_frozen"] = bool(
            resolved.get("manifest_hash")
        )
        report["assertions"]["video_connection_revision"] = video_plan["plan"].get(
            "connection_revision_id"
        )
        report["assertions"]["video_credential_revision"] = video_plan["plan"].get(
            "credential_revision_id"
        )
        step(
            "video plan",
            (
                report["assertions"]["video_first_frame_matches_formal"]
                and report["assertions"]["video_resolved_is_model_b"]
                and report["assertions"]["video_manifest_hash_frozen"]
            ),
            json.dumps({k: v for k, v in report["assertions"].items() if k.startswith("video")}),
        )

        # 9) video execution
        video_fp = video_plan["plan_fingerprint"]
        video_exec = require_ok(
            client.post(
                f"/projects/{project_id}/shots/{shot_id}/executions",
                headers={**headers, "Idempotency-Key": f"golden-video-{uuid4().hex}"},
                json={
                    "stage": "video",
                    "prompt": "character walks into frame",
                    "semantic_intent": {"intent": "shot_video"},
                    "mode_id": "explicit_binding",
                    "plan_fingerprint": video_fp,
                },
            ),
            "video execution",
        )
        video_run = wait_for_run(
            client, base=base, project_id=project_id, run_id=video_exec["node_run_id"],
            headers=headers, timeout_seconds=args.timeout,
        )
        if video_run.get("status") != "completed":
            report["blockers"].append(f"video run not completed: {video_run.get('status')}")
            step("video run", False, video_run.get("status"))
            _write_report(args.out, report)
            return 2
        report["paid_provider_calls"] += 1
        step("video run", True, video_run.get("result_artifact_id"))

        # 10) formal video + trace
        formal_video = require_ok(
            client.post(
                f"/projects/{project_id}/shots/{shot_id}/formal-video",
                headers=headers,
                json={"artifact_id": video_run["result_artifact_id"]},
            ),
            "formal video",
        )
        report["assertions"]["formal_video_set"] = (
            formal_video.get("formal_video_artifact_id") == video_run["result_artifact_id"]
        )
        trace = require_ok(
            client.get(
                f"/projects/{project_id}/runs/{video_exec['node_run_id']}/trace",
                headers=headers,
            ),
            "trace",
        )
        report["assertions"]["trace_actual_model"] = trace.get("actual_model")
        report["assertions"]["trace_actual_is_model_b"] = trace.get("actual_model") == model_b
        report["assertions"]["trace_redacted_present"] = bool(
            trace.get("effective_request_redacted")
        )
        report["assertions"]["trace_secret_free"] = _summary_is_secret_free(trace)
        step(
            "formal video + trace",
            (
                report["assertions"]["trace_actual_is_model_b"]
                and report["assertions"]["trace_redacted_present"]
                and report["assertions"]["trace_secret_free"]
            ),
            json.dumps({k: v for k, v in report["assertions"].items() if k.startswith("trace")}),
        )

        # 11) negative: profile X unavailable -> execution-plan fails, POST=0
        ops_before = _count_ops(client, base, project_id, headers)
        bad_plan = client.post(
            f"/projects/{project_id}/shots/{shot_id}/execution-plan",
            headers=headers,
            json={
                "stage": "image_keyframe",
                "prompt": "unavailable model",
                "semantic_intent": {"intent": "shot_keyframe"},
                "mode_id": "explicit_binding",
                "requested_model_id": "agnes/does-not-exist-xyz",
            },
        )
        ops_after = _count_ops(client, base, project_id, headers)
        report["assertions"]["negative_plan_rejected"] = bad_plan.is_error
        report["assertions"]["negative_post_zero"] = ops_after == ops_before == 0
        step(
            "negative fail-closed",
            report["assertions"]["negative_plan_rejected"]
            and report["assertions"]["negative_post_zero"],
            f"status={bad_plan.status_code} ops={ops_before}->{ops_after}",
        )

        ok = all(s["ok"] for s in report["steps"])
        report["conclusion"] = "PASS" if ok else "FAIL"
        _write_report(args.out, report)
        return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001
        report["blockers"].append(f"{type(exc).__name__}: {exc}")
        report["conclusion"] = "BLOCKED"
        _write_report(args.out, report)
        return 3
    finally:
        client.close()


def _count_ops(
    client: httpx.Client,
    base: str,
    project_id: str,
    headers: dict[str, str],
) -> int:
    """Count provider operations for the project via the snapshot."""
    try:
        snap = require_ok(client.get(f"/projects/{project_id}/snapshot", headers=headers), "snapshot")
        ops = snap.get("provider_operations") or []
        return len(ops)
    except Exception:  # noqa: BLE001
        return -1


def _summary_is_secret_free(value: object) -> bool:
    forbidden = ("api_key", "apikey", "authorization", "ciphertext", "password", "bearer", "secret")
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if any(frag in normalized for frag in forbidden):
                return False
            if not _summary_is_secret_free(child):
                return False
    elif isinstance(value, list):
        return all(_summary_is_secret_free(child) for child in value)
    return True


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"evidence written to {path}")


if __name__ == "__main__":
    sys.exit(main())
