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
        if h.status_code == 200 and body.get("status") == "ok" and db == "up":
            add("INFRA-1", "API /health + DB up", "PASS", json.dumps(body, ensure_ascii=False))
        else:
            add(
                "INFRA-1",
                "API /health + DB up",
                "FAIL",
                f"require status=ok and db=up; got status={h.status_code} body={body}",
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
        elif r.status_code == 422 and (
            "PROVIDER_NOT_CONFIGURED" in r.text
            or "provider_not_configured" in r.text
            or "canonical" in r.text.lower()
        ):
            add(
                "3.1.9",
                "主角 canonical Reference",
                "BLOCKED",
                f"explicit fail-closed (not silent fake): {r.status_code} {r.text[:240]}",
            )
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

    # --- Attempt remaining §3.1 checks (no static BLOCKED list without evaluation) ---
    # 3.1.5 Outbox/Redis: probe dispatch endpoint if project exists
    if project_id:
        try:
            r = post(f"/api/v1/projects/{project_id}/dispatch", {})
            if r.status_code in (200, 201):
                add("3.1.5", "Outbox/Arq dispatch 可调用", "PASS", r.text[:200])
            elif r.status_code == 422 and "QUEUE" in r.text.upper():
                add("3.1.5", "Outbox/Arq/lease 恢复与幂等", "BLOCKED", f"queue unavailable: {r.text[:200]}")
            else:
                add("3.1.5", "Outbox/Arq dispatch", "FAIL", f"{r.status_code} {r.text[:200]}")
        except Exception as exc:  # noqa: BLE001
            add("3.1.5", "Outbox/Arq dispatch", "BLOCKED", str(exc))

        # 3.1.10 / 3.1.12 — require real multi-shot evidence, not produce-golden
        try:
            r = client.get(f"/api/v1/projects/{project_id}/snapshot", cookies=cookies)
            if r.status_code == 200:
                snap = r.json()
                n_runs = len(snap.get("node_runs") or [])
                n_arts = len(snap.get("artifacts") or [])
                if n_runs >= 10 and n_arts >= 1:
                    add(
                        "3.1.10",
                        "10 Shot 经 Graph 可审计结果",
                        "PASS",
                        f"runs={n_runs} artifacts={n_arts}",
                    )
                else:
                    add(
                        "3.1.10",
                        "10 Shot 经 Graph 全节点可审计结果",
                        "BLOCKED",
                        f"insufficient evidence runs={n_runs} arts={n_arts} (no produce-golden)",
                    )
            else:
                add("3.1.10", "10 Shot 快照", "FAIL", f"{r.status_code}")
        except Exception as exc:  # noqa: BLE001
            add("3.1.10", "10 Shot 快照", "BLOCKED", str(exc))

        # 3.1.18 export attempt
        try:
            r = post(f"/api/v1/projects/{project_id}/exports", {})
            if r.status_code in (200, 201):
                add("3.1.18", "导出 timeline/SRT/package", "PASS", r.text[:240])
            else:
                add(
                    "3.1.18",
                    "MP4/SRT/素材包/timeline 可追溯导出",
                    "BLOCKED" if r.status_code == 422 else "FAIL",
                    f"{r.status_code} {r.text[:240]}",
                )
        except Exception as exc:  # noqa: BLE001
            add("3.1.18", "导出", "BLOCKED", str(exc))

    # 3.1.11 InsightFace — inspect shipped module status (not hash-as-acceptance)
    try:
        sys.path.insert(0, str(REPO / "backend"))
        from app.consistency.image_embed import insightface_status  # type: ignore

        st = insightface_status()
        if st.get("available") and st.get("backend") == "insightface+onnx":
            add("3.1.11", "InsightFace 512-d 可用", "PASS", json.dumps(st))
        else:
            add(
                "3.1.11",
                "InsightFace 512-d 与校准阈值",
                "BLOCKED",
                f"not InsightFace acceptance: {st}",
            )
    except Exception as exc:  # noqa: BLE001
        add("3.1.11", "InsightFace 512-d", "BLOCKED", str(exc))

    # Explicit remaining clauses when not already evaluated
    optional_attempt = [
        ("3.1.4", "AgentRun 1:N ProviderOperation 全链路聚合"),
        ("3.1.12", "剧情连续性四层检查"),
        ("3.1.13", "字幕局部失效仅正确下游"),
        ("3.1.14", "缓存命中 NodeRun(cached) 零成本"),
        ("3.1.15", "单飞 ProviderOperation"),
        ("3.1.16", "预算不足/取消竞态"),
        ("3.1.17", "SSE Last-Event-ID 恢复"),
    ]
    seen = {c.id for c in checks}
    for cid, title in optional_attempt:
        if cid not in seen:
            add(cid, title, "BLOCKED", "no live evidence in this gate run")

    # UI shell presence
    try:
        fe = httpx.get("http://127.0.0.1:5173/", timeout=5.0)
        add("UI-1", "前端可打开", "PASS" if fe.status_code == 200 else "FAIL", f"status={fe.status_code}")
    except Exception as exc:  # noqa: BLE001
        add("UI-1", "前端可打开", "FAIL", str(exc))

    passed = sum(1 for c in checks if c.status == "PASS")
    failed = sum(1 for c in checks if c.status == "FAIL")
    blocked_n = sum(1 for c in checks if c.status == "BLOCKED")
    total = len(checks)
    # Full P0 MVP only when every check PASS and health db=up was PASS
    p0_mvp = failed == 0 and blocked_n == 0 and passed == total and total > 0
    reason = (
        "all checks PASS"
        if p0_mvp
        else f"§3.1 incomplete: pass={passed} fail={failed} blocked={blocked_n} (功能候选版 only until Docker/S5)"
    )
    report = {
        "generated_at": _now(),
        "base": base,
        "summary": {
            "pass": passed,
            "fail": failed,
            "blocked": blocked_n,
            "total": total,
            "p0_mvp_complete": p0_mvp,
            "reason": reason,
            "product_label": "P0 功能候选版" if not p0_mvp else "P0 MVP 完成",
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
        f"SUMMARY pass={passed} fail={failed} blocked={blocked_n} p0_mvp_complete={p0_mvp}",
        file=sys.stderr,
    )
    # Any FAIL or BLOCKED fails the command
    return 0 if p0_mvp else 2


if __name__ == "__main__":
    raise SystemExit(main())
