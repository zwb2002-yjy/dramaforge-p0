#!/usr/bin/env python3
"""Honest P0 §3.1 gate probe — reports PASS/FAIL per freeze clause.

Does NOT use produce-golden as evidence of product completion.
Does NOT claim MVP complete when any required item fails.
Exit 0 only if all runnable checks pass; otherwise exit 2.

Usage:
  python scripts/run_p0_section31_gate.py [--base http://127.0.0.1:8010] [--out path]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

REPO = Path(__file__).resolve().parents[1]


@dataclass
class Check:
    id: str
    title: str
    status: str  # PASS | FAIL | SKIP | BLOCKED
    detail: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    base = args.base.rstrip("/")
    checks: list[Check] = []

    def add(cid: str, title: str, status: str, detail: str) -> None:
        checks.append(Check(cid, title, status, detail))

    client = httpx.Client(base_url=base, timeout=60.0, follow_redirects=True)
    cookies: dict[str, str] = {}

    def csrf() -> str:
        r = client.get("/api/v1/auth/csrf", cookies=cookies)
        r.raise_for_status()
        # capture cookies
        for k, v in r.cookies.items():
            cookies[k] = v
        return r.json()["csrf_token"]

    def post(path: str, body: dict[str, Any] | None = None) -> httpx.Response:
        token = csrf()
        r = client.post(
            path,
            json=body or {},
            cookies=cookies,
            headers={"X-CSRF-Token": token, "Content-Type": "application/json"},
        )
        for k, v in r.cookies.items():
            cookies[k] = v
        return r

    # --- infrastructure ---
    try:
        h = client.get("/health")
        body = h.json() if h.content else {}
        db = body.get("db")
        if h.status_code == 200 and body.get("status") == "ok" and db in (None, "up"):
            add("INFRA-1", "API /health + DB up", "PASS", json.dumps(body, ensure_ascii=False))
        else:
            add(
                "INFRA-1",
                "API /health + DB up",
                "FAIL",
                f"status={h.status_code} body={body}",
            )
    except Exception as exc:  # noqa: BLE001
        add("INFRA-1", "API /health + DB up", "FAIL", str(exc))

    # --- §3.1 clauses (runnable subset + explicit blockers) ---
    email = f"gate-{uuid4().hex[:8]}@example.com"
    password = "password123"
    project_id: str | None = None

    try:
        r = post(
            "/api/v1/auth/register",
            {"email": email, "password": password, "display_name": "Gate"},
        )
        if r.status_code in (200, 201):
            add("3.1.1a", "注册用户", "PASS", email)
        else:
            add("3.1.1a", "注册用户", "FAIL", f"{r.status_code} {r.text[:200]}")
            raise RuntimeError("register failed")

        r = post("/api/v1/organizations", {"name": f"GateOrg-{uuid4().hex[:6]}"})
        if r.status_code not in (200, 201):
            add("3.1.1b", "创建组织", "FAIL", f"{r.status_code} {r.text[:200]}")
            raise RuntimeError("org failed")
        org_id = r.json()["id"]
        add("3.1.1b", "创建组织", "PASS", org_id)

        r = post(
            "/api/v1/creation/start-project",
            {
                "organization_id": org_id,
                "name": f"GateProj-{uuid4().hex[:6]}",
                "aspect_ratio": "9:16",
                "experience_mode": "quick",
                "idea": "霓虹雨夜短剧验收",
            },
        )
        if r.status_code not in (200, 201):
            add("3.1.2", "start_project 正式 Project + Brief", "FAIL", f"{r.status_code} {r.text[:300]}")
            raise RuntimeError("start_project failed")
        data = r.json()
        project_id = data["project_id"]
        text_ops = data.get("text_provider_operations", -1)
        if text_ops == 0:
            add(
                "3.1.2",
                "start_project 正式 Project；未经授权文本 Provider 次数为 0",
                "PASS",
                f"project={project_id} text_ops={text_ops}",
            )
        else:
            add(
                "3.1.2",
                "start_project 不得隐式文本 Provider",
                "FAIL",
                f"text_provider_operations={text_ops}",
            )

        # Manual brief (no platform key abuse)
        r = post(
            f"/api/v1/projects/{project_id}/brief",
            {"logline": "女主在霓虹雨夜发现跟踪者", "tone": "cinematic", "audience": "short-drama"},
        )
        if r.status_code not in (200, 201):
            add("3.1.7", "无 Key 手工 Brief", "FAIL", f"{r.status_code} {r.text[:200]}")
            raise RuntimeError("manual brief failed")
        rev_id = r.json()["id"]
        r = post(f"/api/v1/projects/{project_id}/brief/{rev_id}/confirm", {})
        if r.status_code != 200 or r.json().get("status") != "confirmed":
            add("3.1.3", "Brief 确认", "FAIL", r.text[:200])
            raise RuntimeError("confirm brief failed")
        add("3.1.3", "Brief 手工修订 + 确认", "PASS", rev_id)
        add("3.1.7", "无平台 Key 时可手工 Brief/Plan 路径存在", "PASS", "manual brief ok")

        r = post(
            f"/api/v1/projects/{project_id}/plans",
            {
                "brief_revision_id": rev_id,
                "plan": {"prompt": "cinematic neon rain keyframe 9:16, lead silhouette"},
            },
        )
        if r.status_code not in (200, 201):
            add("3.1.6", "手工 Plan", "FAIL", f"{r.status_code} {r.text[:200]}")
            raise RuntimeError("plan failed")
        plan_id = r.json()["id"]
        r = post(
            f"/api/v1/projects/{project_id}/plans/{plan_id}/confirm",
            {"materialization_ops": ["create_shot_stub", "enqueue_keyframe"]},
        )
        if r.status_code not in (200, 201):
            add("3.1.6", "confirm_plan 白名单物化", "FAIL", f"{r.status_code} {r.text[:300]}")
        else:
            node_run_id = r.json().get("node_run_id")
            add("3.1.6", "confirm_plan 白名单物化 + NodeRun", "PASS", f"node_run={node_run_id}")

        # Lead character
        r = post(
            f"/api/v1/projects/{project_id}/characters/lead",
            {"name": "林夏", "locked_prompt": "consistent face lead portrait"},
        )
        if r.status_code in (200, 201):
            add("3.1.9", "主角 canonical Reference", "PASS", r.json().get("canonical_object_key", "")[:80])
        else:
            add("3.1.9", "主角 canonical Reference", "FAIL", f"{r.status_code} {r.text[:240]}")

        # Script import 10 shots
        fixture = REPO / "fixtures" / "scripts" / "p0_10_shots.md"
        if fixture.is_file():
            text = fixture.read_text(encoding="utf-8")
            r = post(
                f"/api/v1/projects/{project_id}/scripts/import",
                {"filename": "p0_10_shots.md", "text": text, "register_lead": True},
            )
            if r.status_code in (200, 201) and r.json().get("shot_count", 0) >= 10:
                add(
                    "3.1.8",
                    "导入剧本 ≥10 Shot",
                    "PASS",
                    f"shots={r.json().get('shot_count')}",
                )
            else:
                add("3.1.8", "导入剧本 ≥10 Shot", "FAIL", f"{r.status_code} {r.text[:240]}")
        else:
            add("3.1.8", "导入剧本 ≥10 Shot", "FAIL", f"missing fixture {fixture}")

        # Snapshot / shots list
        r = client.get(f"/api/v1/projects/{project_id}/shots", cookies=cookies)
        if r.status_code == 200:
            n = len(r.json())
            add("3.1.8b", "Shot 列表可读", "PASS" if n >= 1 else "FAIL", f"count={n}")
        else:
            add("3.1.8b", "Shot 列表可读", "FAIL", f"{r.status_code}")

    except Exception as exc:  # noqa: BLE001
        if not any(c.id.startswith("3.1") and c.status == "FAIL" for c in checks):
            add("FLOW", "引导路径异常中止", "FAIL", str(exc))

    # Explicitly not claimed without full product evidence
    blocked = [
        ("3.1.4", "AgentRun 1:N ProviderOperation 全链路聚合", "需专用 Agent 运行时演练证据"),
        ("3.1.5", "Outbox/Arq/lease 恢复与幂等", "需 Redis+Worker 非功能演练"),
        ("3.1.10", "10 Shot 经 Graph 全节点可审计结果", "禁止用 produce-golden 假路径替代"),
        ("3.1.11", "InsightFace 512-d 与校准阈值", "S0-A 未通过"),
        ("3.1.12", "剧情连续性四层检查", "S4 产品路径未完成验收"),
        ("3.1.13", "字幕局部失效仅正确下游", "S4 缓存演练未作为产品 Gate 留证"),
        ("3.1.14", "缓存命中 NodeRun(cached) 零成本", "需独立演练"),
        ("3.1.15", "单飞 ProviderOperation", "需并发演练"),
        ("3.1.16", "预算不足/取消竞态", "需预算演练"),
        ("3.1.17", "SSE Last-Event-ID 恢复", "需 SSE 演练"),
        ("3.1.18", "MP4/SRT/素材包/timeline 可追溯导出", "需 S5 真交付证据"),
    ]
    for cid, title, why in blocked:
        add(cid, title, "BLOCKED", why)

    # UI shell presence (optional HTTP)
    try:
        fe = httpx.get("http://127.0.0.1:5173/", timeout=5.0)
        add("UI-1", "前端可打开", "PASS" if fe.status_code == 200 else "FAIL", f"status={fe.status_code}")
    except Exception as exc:  # noqa: BLE001
        add("UI-1", "前端可打开", "FAIL", str(exc))

    passed = sum(1 for c in checks if c.status == "PASS")
    failed = sum(1 for c in checks if c.status == "FAIL")
    blocked_n = sum(1 for c in checks if c.status == "BLOCKED")
    report = {
        "generated_at": _now(),
        "base": base,
        "summary": {
            "pass": passed,
            "fail": failed,
            "blocked": blocked_n,
            "total": len(checks),
            "p0_mvp_complete": False,
            "reason": "§3.1 未全 PASS；含 BLOCKED 与/或 FAIL",
        },
        "checks": [asdict(c) for c in checks],
    }

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    out = args.out
    if out is None:
        out = REPO / "docs" / "acceptance" / f"p0_section31_gate_{int(time.time())}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    latest = REPO / "docs" / "acceptance" / "p0_section31_gate_latest.json"
    latest.write_text(text, encoding="utf-8")
    print(f"\nWROTE {out}", file=sys.stderr)
    print(
        f"SUMMARY pass={passed} fail={failed} blocked={blocked_n} p0_mvp_complete=false",
        file=sys.stderr,
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
