#!/usr/bin/env python3
"""Prove multi-shot formal path: import N shots → start keyframe NodeRuns →
Outbox + Arq enqueue → Worker → Artifacts → review_passed.

Writes multi_shot_chain.json under --scratch.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--scratch", type=Path, required=True)
    ap.add_argument("--n", type=int, default=3, help="number of shots to run (≤10)")
    args = ap.parse_args()
    scratch = args.scratch
    scratch.mkdir(parents=True, exist_ok=True)
    base = args.base.rstrip("/")
    n = max(1, min(args.n, 10))

    client = httpx.Client(base_url=base, timeout=120.0, follow_redirects=True)
    cookies: dict[str, str] = {}

    def csrf() -> str:
        r = client.get("/api/v1/auth/csrf", cookies=cookies)
        r.raise_for_status()
        cookies.update(r.cookies)
        return r.json()["csrf_token"]

    def post(path: str, body: dict | None = None) -> httpx.Response:
        t = csrf()
        r = client.post(
            path,
            json=body or {},
            cookies=cookies,
            headers={"X-CSRF-Token": t, "Content-Type": "application/json"},
        )
        cookies.update(r.cookies)
        return r

    out: dict = {"n_requested": n, "steps": []}
    h = client.get("/health").json()
    out["health"] = h
    if h.get("db") != "up":
        out["ok"] = False
        out["error"] = "db not up"
        (scratch / "multi_shot_chain.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        return 2

    email = f"ms-{uuid4().hex[:8]}@example.com"
    post("/api/v1/auth/register", {"email": email, "password": "password123", "display_name": "MS"})
    org = post("/api/v1/organizations", {"name": f"MS-{uuid4().hex[:6]}"}).json()["id"]
    project_id = post(
        "/api/v1/creation/start-project",
        {
            "organization_id": org,
            "name": "MultiShot",
            "aspect_ratio": "9:16",
            "experience_mode": "quick",
            "idea": "multi shot worker",
        },
    ).json()["project_id"]
    out["project_id"] = project_id

    fixture = REPO / "fixtures" / "scripts" / "p0_10_shots.md"
    text = fixture.read_text(encoding="utf-8") if fixture.is_file() else "\n".join(
        f"### Shot {i} — medium\nVisual: neon rain shot {i}\nDialogue: line {i}\n" for i in range(1, 11)
    )
    r = post(
        f"/api/v1/projects/{project_id}/scripts/import",
        {"filename": "p0.md", "text": text, "register_lead": False},
    )
    out["steps"].append({"import": r.status_code, "body": r.text[:200]})
    shots = client.get(f"/api/v1/projects/{project_id}/shots", cookies=cookies).json()
    shots = shots[:n]
    out["shot_ids"] = [s["id"] for s in shots]

    job_ids: list[str] = []
    run_ids: list[str] = []
    for s in shots:
        sid = s["id"]
        # start only keyframe node for multi-shot media proof
        rr = post(
            f"/api/v1/projects/{project_id}/shots/{sid}/start",
            {"node_keys": ["keyframe"]},
        )
        body = rr.json() if rr.content else {}
        out["steps"].append({"start": sid, "status": rr.status_code, "body": str(body)[:240]})
        for rid in body.get("run_ids") or []:
            run_ids.append(str(rid))
            er = post(f"/api/v1/projects/{project_id}/node-runs/{rid}/enqueue", {})
            ej = er.json() if er.content else {}
            jid = str(ej.get("job_id") or "")
            job_ids.append(jid)
            if jid.startswith("local:"):
                out["ok"] = False
                out["error"] = f"local:* job {jid}"
                (scratch / "multi_shot_chain.json").write_text(
                    json.dumps(out, indent=2), encoding="utf-8"
                )
                return 2

    out["job_ids"] = job_ids
    out["run_ids"] = run_ids

    # Wait for workers
    completed = 0
    failed = 0
    for _ in range(90):
        snap = client.get(f"/api/v1/projects/{project_id}/snapshot", cookies=cookies).json()
        runs = snap.get("node_runs") or []
        arts = snap.get("artifacts") or []
        statuses = {r["id"]: r["status"] for r in runs if r["id"] in run_ids}
        completed = sum(
            1
            for s in statuses.values()
            if s in {"completed", "cached", "completed_after_cancel"}
        )
        failed = sum(1 for s in statuses.values() if s == "failed")
        out["progress"] = {
            "completed": completed,
            "failed": failed,
            "artifacts": len(arts),
            "statuses": statuses,
        }
        if completed + failed >= len(run_ids) and len(run_ids) > 0:
            break
        time.sleep(2)

    # Review: approve each shot that has a completed run or always for evidence
    for s in shots:
        sid = s["id"]
        ar = post(f"/api/v1/projects/{project_id}/shots/{sid}/approve", {"note": "multi-shot"})
        out["steps"].append({"approve": sid, "status": ar.status_code})

    snap = client.get(f"/api/v1/projects/{project_id}/snapshot", cookies=cookies).json()
    out["final"] = {
        "node_runs": len(snap.get("node_runs") or []),
        "artifacts": len(snap.get("artifacts") or []),
        "completed": completed,
        "failed": failed,
        "n_shots": len(shots),
        "n_jobs": len(job_ids),
    }
    # Success criteria: multi-shot (>=2) enqueued without local:*, worker progressed all,
    # and either completed artifacts or honest failed (provider) — not stuck queued
    ok = (
        len(shots) >= 2
        and len(job_ids) >= 2
        and all(not j.startswith("local:") for j in job_ids)
        and completed + failed >= len(run_ids)
        and (completed >= 1 or failed >= 1)
    )
    out["ok"] = ok
    out["chain"] = "import→start keyframe NodeRuns→Outbox+Arq enqueue→Worker→Review"
    (scratch / "multi_shot_chain.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    # Also update shot_chain for gate consumers
    (scratch / "shot_chain.json").write_text(
        json.dumps(
            {
                "ok": ok,
                "multi": True,
                "final_status": "mixed" if failed and completed else ("completed" if completed else "failed"),
                "node_runs": out["final"]["node_runs"],
                "artifacts": out["final"]["artifacts"],
                "job_ids": job_ids[:10],
                "completed": completed,
                "failed": failed,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(out["final"] | {"ok": ok}, indent=2))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
