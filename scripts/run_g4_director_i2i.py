"""G4 Director I2I run driver: budget authorization + approval (no spend).

Phase A only: authorizes the $12 TRIAL_BUDGET and records the TRIAL_BUDGET
approval, moving the workflow from awaiting_trial_authorization to
trial_running.  This phase performs NO paid media call.

Phase B (separate invocation): materialize_trial which triggers the real
Provider chain (t2i character_reference $1 -> i2i keyframe $1 -> i2v video
$10) and polls to completion.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import os

REPO = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000"
EMAIL = "dramaforge.owner@example.com"
PASSWORD = os.environ.get("DF_OWNER_PASSWORD", "")  # from env, never committed
WORKSPACE_ID = "c8cdbc7d-cad4-4f8b-83f4-931cf71dd853"  # 黄金样本工作区
PROJECT_ID = "f35e0d08-5ac4-4698-bdc7-48a4705a691b"
COMMIT = "5783e6b141d5d67f3625e442aae9385cee917482"
EVIDENCE_DIR = REPO / "tmp" / "p0-evidence" / COMMIT / "real-provider"


class G4Client:
    def __init__(self) -> None:
        self.client = httpx.Client(base_url=BASE, timeout=120.0, follow_redirects=True)
        self.cookies: dict[str, str] = {}

    def login(self) -> None:
        if not PASSWORD:
            raise RuntimeError("DF_OWNER_PASSWORD env var is required (owner runtime credential)")
        r = self.client.post(
            "/api/v1/auth/login",
            json={"email": EMAIL, "password": PASSWORD},
        )
        r.raise_for_status()
        self.cookies.update(r.cookies)
        print("[login] ok:", r.json()["email"])

    def csrf(self) -> str:
        r = self.client.get("/api/v1/auth/csrf")
        r.raise_for_status()
        self.cookies.update(r.cookies)
        return r.json()["csrf_token"]

    def post(self, path: str, body: dict | None = None) -> httpx.Response:
        t = self.csrf()
        r = self.client.post(
            path,
            json=body or {},
            cookies=self.cookies,
            headers={
                "X-CSRF-Token": t,
                "X-Workspace-Id": WORKSPACE_ID,
                "Content-Type": "application/json",
            },
        )
        self.cookies.update(r.cookies)
        return r

    def get(self, path: str) -> httpx.Response:
        r = self.client.get(path, cookies=self.cookies, headers={"X-Workspace-Id": WORKSPACE_ID})
        self.cookies.update(r.cookies)
        return r


def write_evidence(name: str, payload: dict) -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[evidence] wrote {path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--authorize", action="store_true", help="run phase A: budget auth + approval")
    ap.add_argument("--materialize", action="store_true", help="run phase B: materialize_trial + poll")
    args = ap.parse_args()
    if not (args.authorize or args.materialize):
        ap.error("choose --authorize or --materialize")

    g = G4Client()
    g.login()

    if args.authorize:
        # ---- Phase A: budget authorization (no spend) ----
        auth_key = f"g4-trial-auth-{uuid4().hex[:8]}"
        expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        r = g.post(
            f"/api/v1/projects/{PROJECT_ID}/director/budget-authorizations",
            {
                "authorization_kind": "trial_budget",
                "idempotency_key": auth_key,
                "pricing_snapshot_id": "preflight-2026-08-21",
                "limit_amount": "12",
                "currency": "USD",
                "expires_at": expires,
            },
        )
        print("[authorize] HTTP", r.status_code)
        if r.status_code >= 400:
            print(r.text[:800])
            return 2
        auth = r.json()
        auth_id = auth["id"]
        print("[authorize] id:", auth_id, "status:", auth["status"], "limit:", auth["limit_amount"])

        # ---- Approval: TRIAL_BUDGET (no spend) ----
        appr_key = f"g4-trial-approve-{uuid4().hex[:8]}"
        r2 = g.post(
            f"/api/v1/projects/{PROJECT_ID}/director/approvals",
            {
                "approval_kind": "trial_budget",
                "idempotency_key": appr_key,
                "reason": "G4 single-authorized real Director I2I trial run (user-approved $12 complete TRIAL)",
                "budget_authorization_id": auth_id,
            },
        )
        print("[approve] HTTP", r2.status_code)
        if r2.status_code >= 400:
            print(r2.text[:800])
            return 2
        appr = r2.json()
        print("[approve] kind:", appr["approval"]["approval_kind"])
        print("[workflow] status:", appr["workflow"]["status"], "stage:", appr["workflow"]["current_stage"])

        # ---- Verify workflow state ----
        wf = g.get(f"/api/v1/projects/{PROJECT_ID}/director/workflow").json()
        print("[workflow] final:", wf["status"], wf["current_stage"])
        write_evidence("authorization-record.json", {
            "phase": "authorize+approve",
            "authorization_id": auth_id,
            "authorization_status": auth["status"],
            "approval_kind": appr["approval"]["approval_kind"],
            "workflow_status": wf["status"],
            "workflow_stage": wf["current_stage"],
            "limit_amount": str(auth["limit_amount"]),
            "currency": auth["currency"],
            "pricing_snapshot_id": auth["pricing_snapshot_id"],
            "expires_at": auth["expires_at"],
            "scope": "trial",
            "spend_performed": False,
        })
        print("\nPhase A complete (no spend). Workflow is now TRIAL_RUNNING-ready.")
        print("Next: run with --materialize to trigger the paid Director I2I chain.")
        return 0

    if args.materialize:
        # ---- Phase B: materialize_trial (PAID) ----
        mkey = f"g4-trial-materialize-{uuid4().hex[:8]}"
        print(f"[materialize] idempotency_key={mkey}")
        r = g.post(
            f"/api/v1/projects/{PROJECT_ID}/director/trial/materialize",
            {"idempotency_key": mkey},
        )
        print("[materialize] HTTP", r.status_code)
        if r.status_code >= 400:
            print(r.text[:1200])
            return 2
        body = r.json()
        batch = body["batch"]
        node_runs = body["node_runs"]
        expected_run_ids = {run["id"] for run in node_runs}
        print("[materialize] batch:", batch["id"], batch["status"], batch["batch_kind"])
        print("[materialize] node_runs:", len(node_runs))
        for run in node_runs:
            print("   ", run["id"][:8], run["status"], "reservation:", run["budget_reservation_id"][:8])
        write_evidence("materialize-record.json", {
            "batch_id": batch["id"],
            "batch_kind": batch["batch_kind"],
            "batch_status": batch["status"],
            "node_run_count": len(node_runs),
            "selected_shot_ids": batch.get("selected_shot_ids"),
            "idempotency_key": mkey,
        })

        # ---- Poll for completion ----
        print("\n[poll] waiting for worker to progress node runs (up to 15 min)...")
        final: dict[str, str] = {}
        start = time.time()
        for i in range(180):
            try:
                snap = g.get(f"/api/v1/projects/{PROJECT_ID}/director/workspace-snapshot").json()
            except Exception as exc:
                print(f"[poll] {i}: snapshot error {exc}")
                time.sleep(5)
                continue
            runs = [
                run
                for run in (snap.get("node_runs") or [])
                if run.get("id") in expected_run_ids
            ]
            final = {run["id"]: run.get("status", "?") for run in runs}
            statuses = set(final.values())
            done = (
                set(final) == expected_run_ids
                and statuses <= {"completed", "failed", "cancelled", "completed_after_cancel"}
            )
            print(f"[poll] {i}: {len(runs)} runs -> {sorted(statuses)}")
            if done:
                break
            if time.time() - start > 900:
                print("[poll] TIMEOUT after 15 min")
                break
            time.sleep(5)
        write_evidence("materialize-poll.json", {
            "node_run_statuses": final,
            "poll_seconds": int(time.time() - start),
        })
        print("\nPolling complete. Run statuses:", final)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
