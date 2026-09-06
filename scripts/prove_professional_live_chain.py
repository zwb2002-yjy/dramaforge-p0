#!/usr/bin/env python3
"""Authenticated professional-workbench live-stack proof without paid Provider calls."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

REPO = Path(__file__).resolve().parents[1]


def _sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/api/v1")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args()
    email = os.environ.get("DRAMAFORGE_PROOF_EMAIL", "professional-proof@example.com")
    password = os.environ.get(
        "DRAMAFORGE_PROOF_PASSWORD", "professional-proof-password-2026"
    )
    report: dict[str, object] = {
        "schema_version": 1,
        "proof": "professional-workbench-live-v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source_commit": _sha(),
        "dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO)
        ),
        "paid_provider_calls": 0,
    }
    with httpx.Client(
        base_url=args.base_url, timeout=30.0, follow_redirects=True
    ) as client:
        bootstrap = client.get("/auth/bootstrap-status").json()
        if bootstrap["owner_initialized"]:
            response = client.post(
                "/auth/login", json={"email": email, "password": password}
            )
        else:
            response = client.post(
                "/auth/register",
                json={
                    "email": email,
                    "password": password,
                    "display_name": "Professional Proof",
                },
            )
        response.raise_for_status()
        csrf = client.get("/auth/csrf").json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}
        workspaces = client.get("/workspaces").json()
        workspace_id = workspaces[0]["id"]
        scoped = {**headers, "X-Workspace-Id": workspace_id}
        project = client.post(
            "/projects",
            headers=scoped,
            json={
                "workspace_id": workspace_id,
                "name": f"Professional proof {uuid4().hex[:6]}",
                "aspect_ratio": "16:9",
                "target_platform": "general",
            },
        )
        project.raise_for_status()
        project_id = project.json()["id"]
        imported = client.post(
            f"/projects/{project_id}/scripts/import",
            headers=scoped,
            json={
                "filename": "professional-proof.md",
                "text": (
                    "# Episode 1 - Professional proof\n\n"
                    "## Scene 1 - Rain street / night\nA decision in the rain.\n\n"
                    "### Shot 1 - medium\nVisual: lead turns toward camera in the rain\n"
                    "Dialogue: 我终于明白了。\nCamera: slow push in\n"
                ),
            },
        )
        imported.raise_for_status()
        shot_id = imported.json()["shot_ids"][0]
        shot = client.get(f"/projects/{project_id}/shots", headers=scoped).json()[0]
        asset = client.post(
            f"/projects/{project_id}/assets",
            headers=scoped,
            json={
                "kind": "character",
                "name": "林夏",
                "description": "短发、黑色雨衣、克制表演",
                "metadata": {"tags": ["主角", "雨夜"]},
                "status": "active",
            },
        )
        asset.raise_for_status()
        asset_id = asset.json()["id"]
        asset_v2 = client.patch(
            f"/projects/{project_id}/assets/{asset_id}",
            headers=scoped,
            json={
                "expected_version": 1,
                "kind": "character",
                "name": "林夏",
                "description": "短发、黑色雨衣、克制表演、45度参考",
                "metadata": {"tags": ["主角", "雨夜", "45度"]},
                "status": "active",
            },
        )
        asset_v2.raise_for_status()
        proposal = client.post(
            f"/projects/{project_id}/shots/{shot_id}/change-proposals",
            headers=scoped,
            json={
                "idempotency_key": "proof-shot-change-1",
                "summary": "引用正式角色资产",
                "expected_version": shot["version"],
                "replacement_payload": {
                    "visual_description": f"{shot['visual_description']}\\n@林夏[用途:身份;版本:v2]"
                },
                "affected_node_keys": ["video"],
                "reusable_artifact_ids": [asset_id],
            },
        )
        proposal.raise_for_status()
        canvas = client.patch(
            f"/projects/{project_id}/shots/{shot_id}/canvas",
            headers=scoped,
            json={
                "expected_version": shot["version"],
                "visual_description": f"{shot['visual_description']}\\n@林夏[用途:身份;版本:v2]",
                "shot_type": shot["shot_type"],
                "camera_move": shot["camera_move"],
                "dialogue": shot["dialogue"],
                "source": "user",
            },
        )
        canvas.raise_for_status()
        confirmed = client.post(
            f"/projects/{project_id}/shots/{shot_id}/change-proposals/{proposal.json()['proposal']['id']}/confirm",
            params={"revision_id": canvas.json()["revision_id"]},
            headers=scoped,
            json={},
        )
        confirmed.raise_for_status()
        board = client.put(
            f"/projects/{project_id}/shots/{shot_id}/director-board",
            headers=scoped,
            json={
                "mode": "rough_3d",
                "camera": {"summary": "50mm slow push in"},
                "characters": [
                    {
                        "blocking": "x=.35 y=.55",
                        "pose": "turn toward camera",
                        "expression": "restrained",
                        "gaze": "toward camera",
                    }
                ],
                "scene": {"description": "rain street, neon depth"},
            },
        )
        board.raise_for_status()
        experiment = client.post(
            f"/projects/{project_id}/experiments",
            headers=scoped,
            json={
                "idempotency_key": "proof-model-experiment-1",
                "name": "转头身份稳定实验",
                "source_shot_id": shot_id,
                "selected_model": "provider/model-b",
                "parameters": {"purpose": "identity_turn"},
            },
        )
        experiment.raise_for_status()
        decision = client.post(
            f"/projects/{project_id}/experiments/{experiment.json()['id']}/decision",
            headers=scoped,
            json={"decision": "accepted"},
        )
        decision.raise_for_status()
        annotation = client.post(
            f"/projects/{project_id}/shots/{shot_id}/annotations",
            headers=scoped,
            json={
                "time_start": "1.200",
                "time_end": "2.500",
                "note": "转头区间需要检查身份漂移",
                "severity": "warning",
            },
        )
        annotation.raise_for_status()
        opencut = client.get(f"/projects/{project_id}/opencut-manifest", headers=scoped)
        opencut.raise_for_status()
        report.update(
            {
                "ok": True,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "shot_id": shot_id,
                "asset_version": asset_v2.json()["version"],
                "canvas_version": canvas.json()["shot"]["version"],
                "proposal_status": confirmed.json()["status"],
                "director_board_mode": board.json()["mode"],
                "experiment_status": decision.json()["status"],
                "annotation_range": [
                    annotation.json()["time_start"],
                    annotation.json()["time_end"],
                ],
                "opencut_schema": opencut.json()["schema_version"],
                "opencut_shot_count": len(opencut.json()["shots"]),
            }
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

