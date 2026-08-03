#!/usr/bin/env python3
"""Drive the frozen P0 sample through the real product chain (image + video).

Flow: register user/workspace/project -> register canonical (live I2I) ->
import fixtures/scripts/p0_10_shots.md -> start each shot -> wait for the
worker to run keyframe / face / video (Agnes I2V via Data URI) -> report.

The API key comes from the gitignored .env (AGNES_API_KEY); nothing is logged.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

REPO = Path(__file__).resolve().parents[1]
DONE = {"completed", "cached", "completed_after_cancel"}
TERMINAL = {
    "completed", "cached", "failed", "cancelled",
    "completed_after_cancel", "blocked_budget",
}
REQUIRED = {
    "prompt", "keyframe", "face_review", "video", "video_drift_review",
    "voice", "subtitle", "composite", "continuity_review",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--script", type=Path, default=REPO / "fixtures/scripts/p0_10_shots.md")
    ap.add_argument("--out", type=Path, default=REPO / "tmp/provider-probe/frozen-sample.json")
    ap.add_argument("--timeout-seconds", type=int, default=3000)
    ap.add_argument("--poll", type=float, default=5.0)
    ap.add_argument("--lead-name", default="Lin Xia")
    ap.add_argument("--lead-prompt", default=(
        "Portrait reference sheet of Lin Xia, Chinese female lead, consistent "
        "recognizable face, clean studio background, soft light, front view"
    ))
    args = ap.parse_args()
    script_text = args.script.read_text(encoding="utf-8")
    base = args.base.rstrip("/")
    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)

    report: dict[str, object] = {
        "started_at": datetime.now(UTC).isoformat(),
        "base": base,
        "script": str(args.script),
        "script_chars": len(script_text),
        "steps": {},
    }

    with httpx.Client(base_url=base, timeout=300.0, follow_redirects=True) as client:
        cookies: dict[str, str] = {}

        def csrf() -> str:
            r = client.get("/api/v1/auth/csrf", cookies=cookies)
            r.raise_for_status()
            for k, v in r.cookies.items():
                cookies[k] = v
            return str(r.json()["csrf_token"])

        def post(path: str, body: dict[str, object]) -> httpx.Response:
            token = csrf()
            r = client.post(
                path, json=body, cookies=cookies,
                headers={"X-CSRF-Token": token, "Content-Type": "application/json"},
            )
            for k, v in r.cookies.items():
                cookies[k] = v
            return r

        def get(path: str) -> httpx.Response:
            return client.get(path, cookies=cookies)

        email = f"frozen-{uuid4().hex[:8]}@example.com"
        r = post(
            "/api/v1/auth/register",
            {"email": email, "password": "password123", "display_name": "Frozen"},
        )
        if r.status_code not in (200, 201):
            report["steps"]["register"] = {"status": "failed", "http": r.status_code}
            report["error"] = f"register {r.status_code}"
            report["finished_at"] = datetime.now(UTC).isoformat()
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        report["steps"]["register"] = {"status": "ok", "email": email}

        r = post("/api/v1/workspaces", {"name": f"FrozenWs-{uuid4().hex[:6]}"})
        if r.status_code not in (200, 201):
            report["error"] = f"workspace {r.status_code}"
            report["finished_at"] = datetime.now(UTC).isoformat()
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return 1
        workspace_id = str(r.json()["id"])
        client.headers["X-Workspace-Id"] = workspace_id
        report["steps"]["workspace"] = {"status": "ok", "workspace_id": workspace_id}

        r = post("/api/v1/creation/start-project", {
            "workspace_id": workspace_id,
            "name": "P0 Frozen Sample",
            "aspect_ratio": "9:16",
            "experience_mode": "quick",
            "idea": "A hero walks into neon rain and follows a dangerous clue through one night.",
        })
        if r.status_code not in (200, 201):
            report["error"] = f"start-project {r.status_code}: {r.text[:200]}"
            report["finished_at"] = datetime.now(UTC).isoformat()
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        project_id = str(r.json()["project_id"])
        report["steps"]["project"] = {"status": "ok", "project_id": project_id}

        # Register lead canonical via the live image Provider (Agnes I2I/T2I).
        canonical = post(f"/api/v1/projects/{project_id}/characters/lead", {
            "name": args.lead_name,
            "locked_prompt": args.lead_prompt,
        })
        report["steps"]["canonical"] = {"http": canonical.status_code}
        if canonical.status_code not in (200, 201):
            report["error"] = f"canonical {canonical.status_code}: {canonical.text[:300]}"
            report["finished_at"] = datetime.now(UTC).isoformat()
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        canon = canonical.json()
        report["steps"]["canonical"]["canonical_object_key"] = canon.get("canonical_object_key")

        # Import the frozen 10-shot script.
        r = post(f"/api/v1/projects/{project_id}/scripts/import", {
            "filename": args.script.name,
            "text": script_text,
            "register_lead": False,
        })
        if r.status_code not in (200, 201):
            report["error"] = f"script import {r.status_code}: {r.text[:300]}"
            report["finished_at"] = datetime.now(UTC).isoformat()
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        shot_ids = [str(s) for s in r.json().get("shot_ids", [])]
        report["steps"]["script_import"] = {"status": "ok", "shot_count": len(shot_ids)}
        if len(shot_ids) != 10:
            report["error"] = f"expected 10 shots, got {len(shot_ids)}"
            report["finished_at"] = datetime.now(UTC).isoformat()
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        # Start each shot (materialize graph + queue all 9 nodes).
        run_ids: list[str] = []
        for shot_id in shot_ids:
            r = post(f"/api/v1/projects/{project_id}/shots/{shot_id}/start", {})
            if r.status_code not in (200, 201):
                report["error"] = f"shot start {shot_id} {r.status_code}: {r.text[:200]}"
                report["finished_at"] = datetime.now(UTC).isoformat()
                out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 1
            run_ids.extend(str(v) for v in r.json().get("run_ids", []))
        report["steps"]["start"] = {"status": "ok", "run_ids": len(run_ids)}

        # Wait for all runs to reach a terminal state.
        deadline = time.time() + args.timeout_seconds
        last_snapshot: dict[str, object] = {}
        while time.time() < deadline:
            snap = get(f"/api/v1/projects/{project_id}/snapshot")
            if snap.status_code != 200:
                report["error"] = f"snapshot {snap.status_code}"
                break
            last_snapshot = snap.json()
            runs = last_snapshot.get("node_runs", [])
            if not runs:
                time.sleep(args.poll)
                continue
            pending = [r for r in runs if r.get("status") not in TERMINAL]
            if not pending:
                break
            time.sleep(args.poll)

        runs = last_snapshot.get("node_runs", []) if last_snapshot else []
        face_rows: list[dict[str, object]] = []
        node_summary: dict[str, dict[str, int]] = {}
        for run in runs:
            snap_in = run.get("input_snapshot") or {}
            key = str(snap_in.get("node_key") or "?")
            status = str(run.get("status") or "?")
            node_summary.setdefault(key, {})
            node_summary[key][status] = node_summary[key].get(status, 0) + 1
            if key == "face_review" and status in DONE:
                out_sum = run.get("output_summary") or {}
                face_rows.append({
                    "shot": str(snap_in.get("shot_id") or ""),
                    "attempt": run.get("attempt_no"),
                    "status": out_sum.get("face_review"),
                    "score": out_sum.get("face_score"),
                    "probe_hash": (out_sum.get("probe_content_hash") or "")[:16],
                })

        passed = [f for f in face_rows if f.get("status") == "passed"]
        blocked = [f for f in face_rows if f.get("status") == "blocked"]
        failed_kf = {
            str((r.get("input_snapshot") or {}).get("shot_id") or "")
            for r in runs
            if (r.get("input_snapshot") or {}).get("node_key") == "keyframe"
            and r.get("status") == "failed"
        }

        # Bounded rework (plan §12.2, max 3): a blocked lead face OR a failed
        # keyframe (intermittent Agnes content-filter 400) triggers a keyframe
        # re-run, which invalidates downstream (face/video/drift) and re-queues
        # them. After all rework, wait once more so re-run videos complete.
        max_reworks = 3
        rework_shots = {str(f["shot"] or "") for f in blocked if f.get("shot")} | failed_kf
        for shot_id in sorted(rework_shots):
            if not shot_id:
                continue
            for candidate in range(1, max_reworks + 1):
                report["steps"].setdefault("rework", []).append(
                    {"shot": shot_id[:8], "candidate": candidate}
                )
                kr = post(
                    f"/api/v1/projects/{project_id}/shots/{shot_id}/rerun",
                    {"changed_node_key": "keyframe"},
                )
                if kr.status_code not in {200, 201}:
                    break
                deadline = time.time() + args.timeout_seconds
                while time.time() < deadline:
                    snap = get(f"/api/v1/projects/{project_id}/snapshot")
                    if snap.status_code != 200:
                        break
                    runs_now = snap.json().get("node_runs", [])
                    shot_runs = [
                        r for r in runs_now
                        if str((r.get("input_snapshot") or {}).get("shot_id") or "") == shot_id
                    ]
                    if shot_runs and all(r.get("status") in TERMINAL for r in shot_runs):
                        break
                    time.sleep(args.poll)

        # Final wait: let re-queued downstream (video/drift/composite/continuity)
        # reach a terminal state after rework.
        deadline = time.time() + args.timeout_seconds
        while time.time() < deadline:
            snap = get(f"/api/v1/projects/{project_id}/snapshot")
            if snap.status_code != 200:
                break
            last_snapshot = snap.json()
            runs = last_snapshot.get("node_runs", [])
            pending = [r for r in runs if r.get("status") not in TERMINAL]
            if not pending:
                break
            time.sleep(args.poll)

        face_rows = []
        node_summary = {}
        for run in runs:
            snap_in = run.get("input_snapshot") or {}
            key = str(snap_in.get("node_key") or "?")
            status = str(run.get("status") or "?")
            node_summary.setdefault(key, {})
            node_summary[key][status] = node_summary[key].get(status, 0) + 1
            if key == "face_review" and status in DONE:
                out_sum = run.get("output_summary") or {}
                face_rows.append({
                    "shot": str(snap_in.get("shot_id") or ""),
                    "attempt": run.get("attempt_no"),
                    "status": out_sum.get("face_review"),
                    "score": out_sum.get("face_score"),
                    "probe_hash": (out_sum.get("probe_content_hash") or "")[:16],
                })

        passed = [f for f in face_rows if f.get("status") == "passed"]
        blocked = [f for f in face_rows if f.get("status") == "blocked"]
        report["steps"]["result"] = {
            "node_summary": node_summary,
            "face_review": face_rows,
            "face_passed": len(passed),
            "face_blocked": len(blocked),
        }
        video_ok = node_summary.get("video", {}).get("completed", 0) >= 10
        face_ok = len(passed) >= 1
        report["summary"] = {
            "image_chain_ok": bool(passed),
            "video_chain_ok": video_ok,
            "note": (
                "frozen p0_10_shots.md driven through real product chain; "
                "video uses Agnes I2V Data URI"
            ),
        }
        report["finished_at"] = datetime.now(UTC).isoformat()
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if (video_ok and face_ok) else 2


if __name__ == "__main__":
    raise SystemExit(main())
