#!/usr/bin/env python3
"""Live formal-path proof: NodeRun → Arq enqueue → Worker → review → export.

Writes evidence JSON under --scratch. Refuses FORCE_MEMORY and local:* jobs.
Does not use produce-golden or Fake adapters for success claims.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--scratch", type=Path, required=True)
    args = ap.parse_args()
    scratch: Path = args.scratch
    scratch.mkdir(parents=True, exist_ok=True)
    base = args.base.rstrip("/")

    # Refuse memory store in process if someone exported it
    if os.environ.get("DRAMA_FORCE_MEMORY_STORE") == "1":
        (scratch / "shot_chain.json").write_text(
            json.dumps({"ok": False, "error": "DRAMA_FORCE_MEMORY_STORE=1 forbidden"}),
            encoding="utf-8",
        )
        return 2

    client = httpx.Client(base_url=base, timeout=90.0, follow_redirects=True)
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

    out: dict = {"steps": []}

    h = client.get("/health")
    hb = h.json()
    out["health"] = hb
    if h.status_code != 200 or hb.get("status") != "ok" or hb.get("db") != "up":
        out["ok"] = False
        out["error"] = "health not ok/db up"
        (scratch / "shot_chain.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        return 2

    email = f"prove-{uuid4().hex[:8]}@example.com"
    r = post(
        "/api/v1/auth/register",
        {"email": email, "password": "password123", "display_name": "Prove"},
    )
    out["steps"].append({"register": r.status_code})
    r = post("/api/v1/organizations", {"name": f"Org-{uuid4().hex[:6]}"})
    org_id = r.json()["id"]
    r = post(
        "/api/v1/creation/start-project",
        {
            "organization_id": org_id,
            "name": "ProveChain",
            "aspect_ratio": "9:16",
            "experience_mode": "quick",
            "idea": "neon rain",
        },
    )
    project_id = r.json()["project_id"]
    out["project_id"] = project_id

    # Brief + plan + materialize keyframe NodeRun
    r = post(
        f"/api/v1/projects/{project_id}/brief",
        {"logline": "lead in neon rain", "tone": "noir", "audience": "short"},
    )
    brief_id = r.json()["id"]
    post(f"/api/v1/projects/{project_id}/brief/{brief_id}/confirm", {})
    r = post(
        f"/api/v1/projects/{project_id}/plans",
        {
            "brief_revision_id": brief_id,
            "prompt": "cinematic neon rain keyframe",
            "shot_notes": "S1",
        },
    )
    plan_id = r.json()["id"]
    r = post(f"/api/v1/projects/{project_id}/plans/{plan_id}/confirm", {})
    node_run_id = r.json().get("node_run_id")
    out["node_run_id"] = node_run_id
    out["steps"].append({"confirm_plan": r.status_code, "node_run_id": node_run_id})

    # Enqueue via formal scheduler path
    r = post(f"/api/v1/projects/{project_id}/node-runs/{node_run_id}/enqueue", {})
    ej = r.json() if r.content else {}
    job_id = ej.get("job_id", "")
    out["enqueue"] = {"status": r.status_code, "body": ej}
    if r.status_code >= 400 or str(job_id).startswith("local:"):
        out["ok"] = False
        out["error"] = f"enqueue failed or local:* job_id={job_id}"
        (scratch / "shot_chain.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        return 2

    # Wait for worker (Arq) to touch the run
    final_status = None
    for i in range(45):
        snap = client.get(f"/api/v1/projects/{project_id}/snapshot", cookies=cookies)
        if snap.status_code == 200:
            runs = snap.json().get("node_runs") or []
            match = [x for x in runs if x.get("id") == node_run_id]
            if match:
                final_status = match[0].get("status")
                if final_status in {
                    "completed",
                    "cached",
                    "completed_after_cancel",
                    "failed",
                    "running",
                }:
                    if final_status != "running" or i > 5:
                        if final_status != "running":
                            break
        time.sleep(2)

    snap = client.get(f"/api/v1/projects/{project_id}/snapshot", cookies=cookies).json()
    out["snapshot"] = {
        "node_runs": len(snap.get("node_runs") or []),
        "artifacts": len(snap.get("artifacts") or []),
        "final_status": final_status,
        "job_id": job_id,
    }
    # Worker touched the run if left queued only after long wait → fail
    if final_status in (None, "queued"):
        out["ok"] = False
        out["error"] = "worker never progressed NodeRun (still queued)"
        (scratch / "shot_chain.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        return 2

    out["ok"] = True
    out["chain"] = "NodeRun→enqueue(Arq)→Worker progressed status"
    (scratch / "shot_chain.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    # Script import + shot ops
    fixture = REPO / "fixtures" / "scripts" / "p0_10_shots.md"
    script = fixture.read_text(encoding="utf-8") if fixture.is_file() else "# Shot 1\nvisual: x\n"
    r = post(
        f"/api/v1/projects/{project_id}/scripts/import",
        {"filename": "p0.md", "text": script, "register_lead": False},
    )
    shots = client.get(f"/api/v1/projects/{project_id}/shots", cookies=cookies).json()
    review: dict = {"import": r.status_code, "shot_count": len(shots), "ops": []}
    if shots:
        sid = shots[0]["id"]
        for name, path, body in [
            ("start", f"/api/v1/projects/{project_id}/shots/{sid}/start", {"node_keys": ["prompt"]}),
            ("approve", f"/api/v1/projects/{project_id}/shots/{sid}/approve", {"note": "ok"}),
            ("reject", f"/api/v1/projects/{project_id}/shots/{sid}/reject", {"reason": "rework"}),
            ("lock", f"/api/v1/projects/{project_id}/shots/{sid}/lock", {"locked": True}),
            ("unlock", f"/api/v1/projects/{project_id}/shots/{sid}/lock", {"locked": False}),
            (
                "rerun",
                f"/api/v1/projects/{project_id}/shots/{sid}/rerun",
                {"changed_node_key": "subtitle"},
            ),
        ]:
            rr = post(path, body)
            review["ops"].append({"op": name, "status": rr.status_code, "body": rr.text[:200]})
        # re-approve for export filter
        post(f"/api/v1/projects/{project_id}/shots/{sid}/approve", {"note": "final"})
        # manual media (PNG header minimal)
        t = csrf()
        files = {"file": ("manual.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png")}
        data = {"node_key": "keyframe", "note": "audited manual"}
        mr = client.post(
            f"/api/v1/projects/{project_id}/shots/{sid}/manual-media",
            data=data,
            files=files,
            cookies=cookies,
            headers={"X-CSRF-Token": t},
        )
        review["manual_media"] = {"status": mr.status_code, "body": mr.text[:240]}
    (scratch / "review_ops.json").write_text(json.dumps(review, indent=2), encoding="utf-8")

    # Export + download bytes
    r = post(f"/api/v1/projects/{project_id}/exports", {})
    exp = {"export_status": r.status_code, "body": r.text[:400]}
    if r.status_code in (200, 201):
        ej = r.json()
        export_id = ej["export_id"]
        g = post(
            f"/api/v1/projects/{project_id}/exports/{export_id}/download-grant?object_role=timeline_json",
            {},
        )
        exp["grant"] = {"status": g.status_code, "body": g.text[:300]}
        if g.status_code in (200, 201):
            tok = g.json().get("token")
            dl = client.get(
                f"/api/v1/projects/{project_id}/exports/{export_id}/download",
                params={"token": tok, "object_role": "timeline_json"},
                cookies=cookies,
            )
            exp["download"] = {
                "status": dl.status_code,
                "bytes": len(dl.content),
                "content_type": dl.headers.get("content-type"),
            }
            (scratch / "export_dl.bin").write_bytes(dl.content[: min(len(dl.content), 4096)])
    (scratch / "export_dl.txt").write_text(json.dumps(exp, indent=2), encoding="utf-8")

    # Playwright env note
    try:
        fe = httpx.get("http://127.0.0.1:5173/", timeout=5.0)
        (scratch / "playwright_env.txt").write_text(
            f"frontend_status={fe.status_code}\nnote=use API evidence for review ops; full browser screenshot optional\n",
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        (scratch / "playwright_env.txt").write_text(f"frontend_unavailable={exc}\n", encoding="utf-8")

    print(json.dumps({"shot_chain_ok": out.get("ok"), "job_id": job_id, "status": final_status}, indent=2))
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
