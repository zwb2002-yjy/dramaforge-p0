#!/usr/bin/env python3
"""Configure a ProviderConnection with a real Agnes key and run capability probes.

The API key is read from the AGNES_PROBE_KEY env var (never printed/logged).
This drives the running Docker Compose API; evidence is a JSON report under
--out with no key material.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

BASE = "http://127.0.0.1:8000"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--out", type=Path, default=Path("tmp/provider-probe/probe.json"))
    ap.add_argument("--capability", default="auth_models")
    ap.add_argument("--budget", default="100", help="budget_authorized for paid probes")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    key = os.environ.get("AGNES_PROBE_KEY", "").strip()
    if not key:
        print("AGNES_PROBE_KEY env var must be set", file=sys.stderr)
        return 2
    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)

    report: dict[str, object] = {
        "started_at": datetime.now(UTC).isoformat(),
        "base": base,
        "key_length": len(key),
        "steps": {},
    }

    with httpx.Client(base_url=base, timeout=360.0, follow_redirects=True) as client:
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
                path,
                json=body,
                cookies=cookies,
                headers={"X-CSRF-Token": token, "Content-Type": "application/json"},
            )
            for k, v in r.cookies.items():
                cookies[k] = v
            return r

        def get(path: str) -> httpx.Response:
            return client.get(path, cookies=cookies)

        email = f"probe-{uuid4().hex[:8]}@example.com"
        r = post(
            "/api/v1/auth/register",
            {"email": email, "password": "password123", "display_name": "Probe"},
        )
        if r.status_code not in (200, 201):
            report["steps"]["register"] = {"status": "failed", "http": r.status_code}
            report["finished_at"] = datetime.now(UTC).isoformat()
            (out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        report["steps"]["register"] = {"status": "ok", "email": email}

        r = post("/api/v1/workspaces", {"name": f"ProbeWs-{uuid4().hex[:6]}"})
        if r.status_code not in (200, 201):
            report["steps"]["workspace"] = {
                "status": "failed",
                "http": r.status_code,
                "body": r.text[:200],
            }
            report["finished_at"] = datetime.now(UTC).isoformat()
            (out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        workspace_id = str(r.json()["id"])
        report["steps"]["workspace"] = {"status": "ok", "workspace_id": workspace_id}
        client.headers["X-Workspace-Id"] = workspace_id

        r = post(
            f"/api/v1/workspaces/{workspace_id}/provider-connections",
            {
                "provider_type": "agnes",
                "display_name": "Agnes 中国站",
                "protocol_profile": "agnes_cn_v1",
                "api_key": key,
                "enabled": True,
            },
        )
        if r.status_code not in (200, 201):
            report["steps"]["connection"] = {
                "status": "failed",
                "http": r.status_code,
                "body": r.text[:300],
            }
            report["finished_at"] = datetime.now(UTC).isoformat()
            (out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        conn = r.json()
        connection_id = str(conn["id"])
        report["steps"]["connection"] = {
            "status": "ok",
            "connection_id": connection_id,
            "base_url": conn.get("base_url"),
            "credential_configured": conn.get("credential_configured"),
        }

        # Run the requested capability probe
        r = post(
            f"/api/v1/workspaces/{workspace_id}/provider-connections/{connection_id}/probes",
            {"capability": args.capability, "budget_authorized": args.budget},
        )
        if r.status_code not in (200, 201):
            report["steps"]["probe"] = {
                "status": "failed",
                "http": r.status_code,
                "body": r.text[:400],
            }
        else:
            probe = r.json()
            report["steps"]["probe"] = {
                "probe_id": probe.get("probe_id"),
                "capability": probe.get("capability"),
                "status": probe.get("status"),
                "evidence_level": probe.get("evidence_level"),
                "http_status": probe.get("http_status"),
                "error_code": probe.get("error_code"),
                "tested_at": probe.get("tested_at"),
            }
        # Refresh connection verification status
        cr = get(f"/api/v1/workspaces/{workspace_id}/provider-connections/{connection_id}")
        if cr.status_code == 200:
            report["steps"]["connection_after"] = {
                "verification_status": cr.json().get("verification_status"),
                "verified_at": cr.json().get("verified_at"),
            }

    report["finished_at"] = datetime.now(UTC).isoformat()
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    probe_status = str(report["steps"].get("probe", {}).get("status", "failed"))
    return 0 if probe_status in {"passed", "pending"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
