#!/usr/bin/env python3
"""Localized drift re-test (plan §17.5): re-run video for drift-blocked shots.

Targeted follow-up to a frozen-sample proof run: re-runs only the video node
(and downstream drift/composite/continuity) for shots whose drift review was
blocked, so a genuine re-run verdict is recorded without a full 10-shot re-run.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

DONE = {"completed", "cached", "completed_after_cancel"}
TERMINAL = {
    "completed", "cached", "failed", "cancelled",
    "completed_after_cancel", "blocked_budget",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", default="password123")
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--workspace-id", required=True)
    ap.add_argument("--shot-ids", nargs="+", required=True)
    ap.add_argument("--out", type=Path, default=Path("tmp/provider-probe/drift-rerun.json"))
    ap.add_argument("--timeout-seconds", type=int, default=1800)
    ap.add_argument("--poll", type=float, default=5.0)
    args = ap.parse_args()
    base = args.base.rstrip("/")
    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)

    report: dict[str, object] = {
        "started_at": datetime.now(UTC).isoformat(),
        "base": base,
        "project_id": args.project_id,
        "shot_ids": args.shot_ids,
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

        r = post("/api/v1/auth/login", {
            "email": args.email, "password": args.password,
        })
        if r.status_code not in (200, 201):
            report["error"] = f"login {r.status_code}: {r.text[:200]}"
            report["finished_at"] = datetime.now(UTC).isoformat()
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        client.headers["X-Workspace-Id"] = args.workspace_id
        report["steps"]["login"] = {"status": "ok", "email": args.email}

        reworked: list[dict[str, object]] = []
        for shot_id in args.shot_ids:
            kr = post(
                f"/api/v1/projects/{args.project_id}/shots/{shot_id}/rerun",
                {"changed_node_key": "video"},
            )
            reworked.append({"shot": shot_id[:8], "http": kr.status_code})
            if kr.status_code not in {200, 201}:
                report["error"] = f"rerun {shot_id} {kr.status_code}: {kr.text[:200]}"
                break
        report["steps"]["rework"] = reworked

        deadline = time.time() + args.timeout_seconds
        last_snapshot: dict[str, object] = {}
        while time.time() < deadline:
            snap = get(f"/api/v1/projects/{args.project_id}/snapshot")
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
        rows: list[dict[str, object]] = []
        for run in runs:
            shot_id = str((run.get("input_snapshot") or {}).get("shot_id") or "")
            if shot_id not in args.shot_ids:
                continue
            key = str((run.get("input_snapshot") or {}).get("node_key") or "?")
            if key in {"video", "video_drift_review", "composite", "continuity_review"}:
                out_sum = run.get("output_summary") or {}
                rows.append({
                    "shot": shot_id[:8],
                    "node": key,
                    "attempt": run.get("attempt_no"),
                    "status": run.get("status"),
                    "review_status": out_sum.get("status"),
                    "drift_mean": out_sum.get("drift_mean_score"),
                    "error_code": run.get("error_code"),
                })
        report["steps"]["result"] = rows
        report["finished_at"] = datetime.now(UTC).isoformat()
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
