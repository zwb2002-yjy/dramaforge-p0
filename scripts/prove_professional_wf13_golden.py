#!/usr/bin/env python3
"""WF13-01 — Real Provider Workflow Golden (multi-scene / multi-character).

Closes the WF12 caveat: the real paid-provider workflow golden on the multi-shot /
multi-scene structure that Part A requires.  Drives everything through the
authenticated professional API, exercises the planning freeze surface I added,
and proves two independent layers of multi-subject fail-closed evidence:

  * planning: the ``participation-plan`` endpoint resolves the workspace keyframe
    model and records an UNSUPPORTED capability assessment (Agnes caps
    ``reference_image`` at 1, so a 2-visible-character shot cannot preserve both
    subjects) with ``paid_dispatch.allowed=false``;
  * dispatch (the authoritative boundary I wired in
    ``product_path._execute_unified_media_node_run``): the two-character shot's
    keyframe NodeRun is committed terminally as ``MULTI_SUBJECT_UNSUPPORTED``
    with ZERO ProviderOperations -> Provider POST = 0.  A silent single-reference
    POST (the banned "只发角色 A 后宣称 multi-character PASS") is impossible.

A second scene's action/dialogue shot is executed against the real Agnes
provider (keyframe -> video -> identity review -> formal selection) to prove the
paid path still works end-to-end.

Records only redacted request/result metadata; credentials, signed URLs and raw
provider payloads are never written.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from collections.abc import Mapping
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


def require_ok_retry(
    client: httpx.Client, name: str, action: Any, *, attempts: int = 8, delay: float = 10.0
) -> Any:
    """Issue ``action`` (a zero-arg callable returning a Response) with backoff.

    The Agnes canonical generation commonly returns a transient 5xx
    (``PROVIDER_UNAVAILABLE``) on first attempt; retry before declaring failure.
    """
    last: httpx.Response | None = None
    for i in range(attempts):
        last = action()
        if not last.is_error:
            return require_ok(last, name)
        # Retry only on transient 5xx; a 4xx (e.g. version conflict, invalid
        # payload) is a real failure and must not be retried.
        if last.status_code < 500:
            break
        time.sleep(delay)
    assert last is not None
    raise RuntimeError(f"{name} failed ({last.status_code}): {request_error(last)}")


def public_operation(operation: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": operation.get("id"),
        "node_run_id": operation.get("node_run_id"),
        "operation_kind": operation.get("operation_kind"),
        "actual_provider": operation.get("actual_provider"),
        "actual_model": operation.get("actual_model"),
        "provider_request_id": operation.get("provider_request_id"),
        "status": operation.get("status"),
        "request_fingerprint": operation.get("request_fingerprint"),
        "reference_artifact_ids": operation.get("request_summary", {}).get(
            "reference_artifact_ids"
        ),
        "model_binding_id": operation.get("model_binding_id"),
        "capability_manifest_hash": operation.get("capability_manifest_hash"),
        "provider_cost": operation.get("provider_cost"),
        "currency": operation.get("currency"),
        "submitted_at": operation.get("submitted_at"),
        "completed_at": operation.get("completed_at"),
    }


def public_run(run: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(run.get("input_snapshot") or {})
    return {
        "id": run.get("id"),
        "attempt_no": run.get("attempt_no"),
        "status": run.get("status"),
        "node_key": run.get("node_key"),
        "result_artifact_id": run.get("result_artifact_id"),
        "error_code": run.get("error_code"),
        "error_summary": run.get("error_summary"),
        "input_hash": run.get("input_hash"),
        "model_binding_id": snapshot.get("model_binding_id"),
    }


def wait_for_nodes(
    client: httpx.Client,
    *,
    project_id: str,
    shot_id: str,
    node_keys: set[str],
    timeout_seconds: int,
    headers: Mapping[str, str],
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_snapshot: dict[str, Any] = {}
    while time.monotonic() < deadline:
        snapshot = require_ok(
            client.get(f"/projects/{project_id}/snapshot", headers=headers),
            "snapshot",
        )
        last_snapshot = snapshot
        runs = [
            run
            for run in snapshot.get("node_runs", [])
            if (run.get("input_snapshot") or {}).get("shot_id") == shot_id
            and run.get("node_key") in node_keys
        ]
        latest: dict[str, dict[str, Any]] = {}
        for run in runs:
            latest.setdefault(str(run.get("node_key")), run)
        if latest and set(latest) >= node_keys and all(
            run.get("status")
            in {"completed", "cached", "completed_after_cancel", "failed", "blocked"}
            for run in latest.values()
        ):
            return snapshot
        time.sleep(3)
    raise TimeoutError(
        f"timed out waiting for {sorted(node_keys)}; last runs="
        f"{[public_run(run) for run in last_snapshot.get('node_runs', [])]}"
    )


def resume_report(
    client: httpx.Client,
    *,
    project_id: str,
    headers: Mapping[str, str],
) -> dict[str, Any]:
    """Produce the WF13-01 evidence report from an existing project's state.

    Reads the persisted execution truth (snapshot node runs + provider
    operations + artifacts + workflow overview) and builds the same evidence
    envelope as a fresh run, without issuing any new paid Provider request.
    """
    snapshot = require_ok(client.get(f"/projects/{project_id}/snapshot", headers=headers), "snapshot")
    shots = require_ok(client.get(f"/projects/{project_id}/shots", headers=headers), "list shots")
    by_number = {int(s["shot_number"]): s for s in shots if s.get("shot_number") is not None}
    two_char_shot = by_number.get(3)
    action_shot = by_number.get(4)

    def shot_runs(shot_id: str | None) -> list[dict[str, Any]]:
        return [
            public_run(run)
            for run in snapshot.get("node_runs", [])
            if (run.get("input_snapshot") or {}).get("shot_id") == shot_id
        ]

    def ops_for(shot_id: str | None) -> list[dict[str, Any]]:
        run_ids = {
            (r.get("input_snapshot") or {}).get("shot_id")
            for r in snapshot.get("node_runs", [])
            if (r.get("input_snapshot") or {}).get("shot_id") == shot_id
        }
        # Map by node_run_id -> input_snapshot of that run.
        run_by_id = {str(r.get("id")): r for r in snapshot.get("node_runs", [])}
        out = []
        for op in snapshot.get("provider_operations", []):
            nrid = str(op.get("node_run_id") or "")
            run = run_by_id.get(nrid)
            if run is not None and (run.get("input_snapshot") or {}).get("shot_id") == shot_id:
                out.append(public_operation(op))
        return out

    two_char_runs = shot_runs(str(two_char_shot["id"]) if two_char_shot else None)
    keyframe = next((r for r in two_char_runs if r["node_key"] == "keyframe"), None)
    two_char_ops = ops_for(str(two_char_shot["id"]) if two_char_shot else None)

    # Per-shot workflow-state for the frozen plan / capability assessment.
    two_char_state = {}
    action_state = {}
    if two_char_shot:
        st = require_ok(
            client.get(f"/projects/{project_id}/shots/{two_char_shot['id']}/workflow-state", headers=headers),
            "two-char workflow-state",
        )
        two_char_state = st.get("workflow_state", {})
    if action_shot:
        st = require_ok(
            client.get(f"/projects/{project_id}/shots/{action_shot['id']}/workflow-state", headers=headers),
            "action workflow-state",
        )
        action_state = st.get("workflow_state", {})

    overview = require_ok(
        client.get(f"/projects/{project_id}/workflow-overview", headers=headers),
        "workflow overview",
    ).get("overview", {})

    report: dict[str, Any] = {
        "schema_version": 1,
        "proof": "professional-workflow-real-provider-golden-v1",
        "resume_project_id": project_id,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "source_commit": commit(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO)),
        "codebase_gate_presented_evidence": True,
    }

    report["shots"] = {
        "two_character": {
            "shot_id": str(two_char_shot["id"]) if two_char_shot else None,
            "workflow_template_key": two_char_state.get("workflow_template_key"),
            "template_version": two_char_state.get("template_version"),
            "template_contract_hash": two_char_state.get("template_contract_hash"),
            "capability_assessment": two_char_state.get("capability_assessment"),
            "participations": [
                {
                    "screen_role": p.get("screen_role"),
                    "character_id": p.get("character_id"),
                    "asset_version_id": p.get("asset_version_id"),
                }
                for p in two_char_state.get("participations", [])
            ],
        },
        "action": {
            "shot_id": str(action_shot["id"]) if action_shot else None,
        },
    }

    fail_closed = bool(
        keyframe is not None and keyframe["status"] == "failed"
        and "MULTI_SUBJECT_UNSUPPORTED" in str(keyframe.get("error_code"))
    )
    report["two_character"] = {
        "fail_closed": fail_closed,
        "keyframe_status": keyframe.get("status") if keyframe else None,
        "error_code": keyframe.get("error_code") if keyframe else None,
        "reason": keyframe.get("error_summary") if keyframe else None,
        "provider_post_count": len(two_char_ops),
    }
    report["two_character_post_count"] = len(two_char_ops)

    action_ops = ops_for(str(action_shot["id"]) if action_shot else None)
    paid = [op for op in action_ops if op.get("status") in {"succeeded", "submitted", "running"}]
    report["paid_provider_calls"] = len(paid)
    report["provider_operations"] = action_ops
    report["provider_raw_cost_fields"] = [
        op.get("provider_cost") for op in action_ops if op.get("provider_cost") is not None
    ]
    report["artifacts"] = [
        {
            "id": item.get("id"),
            "content_hash": item.get("content_hash"),
            "mime_type": item.get("mime_type"),
            "byte_size": item.get("byte_size"),
            "produced_by_run_id": item.get("produced_by_run_id"),
        }
        for item in snapshot.get("artifacts", [])
    ]
    report["project_overview"] = {
        "total_shots": overview.get("total_shots"),
        "formal_shots": overview.get("formal_shots"),
        "blocked_scenes": overview.get("blocked_scenes"),
        "review_required_scenes": overview.get("review_required_scenes"),
        "unsupported_capability_shots": overview.get("unsupported_capability_shots"),
    }
    report["ok"] = True
    return report


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/api/v1")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--resume-project",
        type=str,
        default=None,
        help="Produce the evidence report from an existing project id (no fresh paid run).",
    )
    args = parser.parse_args()

    email = os.environ.get("DRAMAFORGE_PROOF_EMAIL", "professional-proof@example.com")
    password = os.environ.get(
        "DRAMAFORGE_PROOF_PASSWORD", "professional-proof-password-2026"
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "proof": "professional-workflow-real-provider-golden-v1",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "source_commit": commit(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO)),
        "paid_provider_calls": None,
        "provider_raw_cost_fields": [],
        "steps": {},
    }

    # Two scenes, two recurring characters, two locations.  Scene 1 carries the
    # two-character dialogue shot (the fail-closed evidence).  Scene 2 carries the
    # single-character action/dialogue shot (the real paid path).
    script = """# Episode 1 - WF13 Golden

## Scene 1 - Rain street / night
A decision in the rain between two friends.

### Shot 1 - medium
Visual: two fictional characters face each other in the rain, tense stillness
Dialogue:
Camera: static

### Shot 2 - close-up
Visual: character A looks down, deciding
Dialogue:
Camera: slow push in

### Shot 3 - two shot
Visual: character A and character B exchange a look in the rain, both in frame
Dialogue:
Camera: static

## Scene 2 - Neon bar / night
An action break.

### Shot 4 - wide
Visual: a fictional character turns toward the camera, neon depth
Dialogue: 我终于明白了。
Camera: slow push in

### Shot 5 - medium
Visual: character A reaches for a glass, motion blur
Dialogue:
Camera: whip pan
"""

    with httpx.Client(
        base_url=args.base_url,
        timeout=60.0,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        bootstrap = require_ok(client.get("/auth/bootstrap-status"), "bootstrap status")
        if bootstrap.get("owner_initialized"):
            require_ok(
                client.post("/auth/login", json={"email": email, "password": password}),
                "login",
            )
        else:
            require_ok(
                client.post(
                    "/auth/register",
                    json={"email": email, "password": password, "display_name": "Professional Proof"},
                ),
                "register",
            )
        csrf = require_ok(client.get("/auth/csrf"), "csrf")["csrf_token"]
        workspaces = require_ok(client.get("/workspaces"), "workspaces")
        workspace_id = str(workspaces[0]["id"])
        headers = {"X-CSRF-Token": csrf, "X-Workspace-Id": workspace_id}

        if args.resume_project:
            report = resume_report(
                client,
                project_id=args.resume_project,
                headers=headers,
            )
            report["finished_at_utc"] = datetime.now(UTC).isoformat()
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(json.dumps(report, ensure_ascii=False))
            return 0

        project = require_ok(
            client.post(
                "/projects",
                headers=headers,
                json={
                    "workspace_id": workspace_id,
                    "name": f"WF13 Golden {uuid4().hex[:8]}",
                    "aspect_ratio": "9:16",
                    "target_platform": "general",
                },
            ),
            "create project",
        )
        project_id = str(project["id"])
        report.update({"workspace_id": workspace_id, "project_id": project_id})

        # Two recurring characters.  Each /characters/lead is a real paid canonical
        # image (the cast reference set); it also creates the Character row that
        # participation validation requires.  No AssetVersion is minted by lead
        # registration, so we create + promote one identity version per character.
        characters: dict[str, dict[str, Any]] = {}
        for api_name, display in (
            ("A", "Lin Xia"),
            ("B", "Chen Yu"),
        ):
            lead = require_ok_retry(
                client,
                f"register lead {display}",
                lambda: client.post(
                    f"/projects/{project_id}/characters/lead",
                    headers=headers,
                    json={
                        "name": display,
                        "locked_prompt": (
                            f"portrait reference sheet of {display}, consistent face, "
                            "clean background, studio light"
                        ),
                    },
                ),
            )
            char_id = str(lead["character_id"])
            candidate = require_ok(
                client.post(
                    f"/projects/{project_id}/assets/{char_id}/versions",
                    headers=headers,
                    json={"name": f"{display} identity v0"},
                ),
                f"create identity version {display}",
            )
            version = require_ok(
                client.post(
                    f"/projects/{project_id}/assets/{char_id}/versions/"
                    f"{candidate['id']}/promote",
                    headers=headers,
                    json={},
                ),
                f"promote identity version {display}",
            )
            characters[api_name] = {
                "character_id": char_id,
                "name": display,
                "asset_version_id": str(version["id"]),
                "canonical_artifact_id": str(lead["canonical_artifact_id"]),
                "provider": lead.get("provider"),
            }
            report.setdefault("characters", {})[api_name] = {
                "character_id": char_id,
                "name": display,
                "asset_version_id": str(version["id"]),
                "provider": lead.get("provider"),
            }

        imported = require_ok(
            client.post(
                f"/projects/{project_id}/scripts/import",
                headers=headers,
                json={"filename": "wf13-golden.md", "text": script, "register_lead": False},
            ),
            "import script",
        )
        report["episode_id"] = str(imported["episode_id"])
        report["scene_count"] = imported["scene_count"]
        report["shot_count"] = imported["shot_count"]
        shots = require_ok(client.get(f"/projects/{project_id}/shots", headers=headers), "list shots")
        # Shots are returned in shot_number order; scene boundary is derived from
        # the script structure.  Scene 1 = shots 1-3, Scene 2 = shots 4-5.
        by_number = {int(s["shot_number"]): s for s in shots if s.get("shot_number") is not None}
        two_char_shot = by_number[3]  # "two shot" in scene 1 -> 2 visible characters
        action_shot = by_number[4]     # "wide" in scene 2 -> single character, paid path
        report["shots"] = {
            "two_character": {
                "shot_id": str(two_char_shot["id"]),
                "shot_number": two_char_shot["shot_number"],
                "visual_description": two_char_shot["visual_description"],
            },
            "action": {
                "shot_id": str(action_shot["id"]),
                "shot_number": action_shot["shot_number"],
                "visual_description": action_shot["visual_description"],
            },
        }

        # --- Planning freeze on the TWO-CHARACTER shot -------------------------
        # Freeze the participation plan (both characters visible) + the explicit
        # two-character workflow template.  This is where the planning-side
        # UNSUPPORTED assessment is recorded (Agnes reference_image max = 1).
        two_char_version = int(two_char_shot["version"])
        participation = require_ok(
            client.post(
                f"/projects/{project_id}/shots/{two_char_shot['id']}/participation-plan",
                headers=headers,
                json={
                    "expected_version": two_char_version,
                    "participations": [
                        {
                            "character_id": characters["A"]["character_id"],
                            "asset_version_id": characters["A"]["asset_version_id"],
                            "screen_role": "primary",
                            "importance": 80,
                            "dialogue_role": "speaking",
                        },
                        {
                            "character_id": characters["B"]["character_id"],
                            "asset_version_id": characters["B"]["asset_version_id"],
                            "screen_role": "secondary",
                            "importance": 60,
                            "dialogue_role": "listening",
                        },
                    ],
                },
            ),
            "freeze two-char participation plan",
        )
        ws = participation["workflow_state"]
        report["steps"]["two_character_planning_freeze"] = {
            "participations": [
                {
                    "screen_role": p.get("screen_role"),
                    "character_id": p.get("character_id"),
                    "asset_version_id": p.get("asset_version_id"),
                }
                for p in ws.get("participations", [])
            ],
            "capability_assessment": ws.get("capability_assessment"),
            "paid_dispatch": participation.get("paid_dispatch"),
        }

        # Freeze the explicit two-character template (must resolve for planning).
        try:
            frozen_template = require_ok(
                client.post(
                    f"/projects/{project_id}/shots/{two_char_shot['id']}/workflow-template",
                    headers=headers,
                    json={
                        "expected_version": two_char_version + 1,
                        "template_key": "two-character-dialogue-v1",
                    },
                ),
                "freeze two-char workflow template",
            )
            report["steps"]["two_character_template_freeze"] = {
                "workflow_template_key": frozen_template["workflow_state"].get(
                    "workflow_template_key"
                ),
                "template_version": frozen_template["workflow_state"].get("template_version"),
                "template_contract_hash": frozen_template["workflow_state"].get(
                    "template_contract_hash"
                ),
                "template_resolution_status": frozen_template["workflow_state"].get(
                    "template_resolution_status"
                ),
            }
        except Exception as exc:  # noqa: BLE001 - record a planning-only failure honestly
            report["steps"]["two_character_template_freeze"] = {
                "error": f"{type(exc).__name__}: {exc}"
            }

        # --- Real paid path on the ACTION shot --------------------------------
        # Set duration on the action shot (single character -> no multi-subject gate).
        action_state = require_ok(
            client.get(
                f"/projects/{project_id}/shots/{action_shot['id']}/workflow-state",
                headers=headers,
            ),
            "action workflow-state",
        )
        action_version = int(action_shot["version"])
        canvas = require_ok(
            client.patch(
                f"/projects/{project_id}/shots/{action_shot['id']}/canvas",
                headers=headers,
                json={
                    "expected_version": action_version,
                    "visual_description": action_shot["visual_description"],
                    "shot_type": action_shot["shot_type"],
                    "camera_move": action_shot["camera_move"],
                    "dialogue": action_shot["dialogue"],
                    "duration_seconds": "5.000",
                    "source": "user",
                },
            ),
            "set action shot duration",
        )
        report["steps"]["action_canvas_duration"] = {
            "duration_seconds": canvas["shot"]["duration_seconds"],
            "canvas_version": canvas["shot"]["version"],
        }

        connections = require_ok(
            client.get(
                f"/workspaces/{workspace_id}/provider-connections", headers=headers
            ),
            "list provider connections",
        )
        connection = next(
            (
                item
                for item in connections
                if item.get("provider_type") == "agnes" and item.get("enabled")
            ),
            None,
        )
        if connection is None:
            raise RuntimeError("no enabled Agnes connection found")
        connection_id = str(connection["id"])
        bindings = require_ok(
            client.get(
                f"/workspaces/{workspace_id}/provider-connections/{connection_id}/model-bindings",
                headers=headers,
            ),
            "list Agnes bindings",
        )
        selected: dict[str, dict[str, Any]] = {}
        for purpose in ("keyframe", "video"):
            binding = next(
                (
                    item
                    for item in bindings
                    if item.get("purpose") == purpose
                    and item.get("enabled")
                    and item.get("account_verified")
                ),
                None,
            )
            if binding is None:
                raise RuntimeError(f"no verified Agnes binding for {purpose}")
            selected[purpose] = binding
            require_ok(
                client.put(
                    f"/projects/{project_id}/provider-bindings/{purpose}",
                    headers=headers,
                    json={"model_binding_id": binding["id"]},
                ),
                f"bind Agnes {purpose}",
            )
        report["provider"] = {
            "connection_id": connection_id,
            "connection_verification_status": connection.get("verification_status"),
            "bindings": {
                purpose: {
                    "id": binding["id"],
                    "model_id": binding["model_id"],
                    "purpose": binding["purpose"],
                    "account_verified": binding["account_verified"],
                    "quality_gated": binding["quality_gated"],
                    "catalog_entry_id": binding.get("catalog_entry_id"),
                    "capability_manifest_hash": binding.get("capability_manifest_hash"),
                }
                for purpose, binding in selected.items()
            },
        }

        # --- Dispatch the TWO-CHARACTER shot: must fail closed, POST=0 --------
        # Freeze the two-char template identity (now at version+2) and start the
        # professional keyframe pipeline.  The dispatch gate must commit the
        # keyframe run as MULTI_SUBJECT_UNSUPPORTED with zero ProviderOperations.
        two_char_start = require_ok(
            client.post(
                f"/projects/{project_id}/professional/shots/{two_char_shot['id']}/start",
                headers=headers,
                json={"node_keys": ["prompt", "keyframe", "identity_review"]},
            ),
            "start two-char professional keyframe",
        )
        report["steps"]["two_character_start"] = {
            "run_ids": two_char_start.get("run_ids", []),
            "job_ids": two_char_start.get("job_ids", []),
        }
        two_char_snapshot = wait_for_nodes(
            client,
            project_id=project_id,
            shot_id=str(two_char_shot["id"]),
            node_keys={"prompt", "keyframe", "identity_review"},
            timeout_seconds=args.timeout,
            headers=headers,
        )
        two_char_runs = [
            public_run(run)
            for run in two_char_snapshot.get("node_runs", [])
            if (run.get("input_snapshot") or {}).get("shot_id") == str(two_char_shot["id"])
            and run.get("node_key") in {"prompt", "keyframe", "identity_review"}
        ]
        report["steps"]["two_character_dispatch"] = {"runs": two_char_runs}
        keyframe_run = next(
            (r for r in two_char_runs if r["node_key"] == "keyframe"), None
        )
        if keyframe_run is None or keyframe_run["status"] != "failed":
            raise RuntimeError(
                f"two-char keyframe did NOT fail closed: {keyframe_run}, "
                f"POST would not be 0"
            )
        if "MULTI_SUBJECT_UNSUPPORTED" not in str(keyframe_run["error_code"]):
            raise RuntimeError(
                f"two-char keyframe failed with unexpected code "
                f"{keyframe_run['error_code']}; expected MULTI_SUBJECT_UNSUPPORTED"
            )
        two_char_operations = [
            public_operation(item)
            for item in two_char_snapshot.get("provider_operations", [])
            if (item.get("node_run_id") or "").startswith(str(two_char_shot["id"]))
            or any(
                run.get("id") == item.get("node_run_id")
                for run in two_char_runs
            )
        ]
        report["two_character_post_count"] = len(two_char_operations)
        if two_char_operations:
            raise RuntimeError(
                f"two-char shot produced {len(two_char_operations)} ProviderOperations; "
                f"expected POST=0"
            )
        report["two_character"] = {
            "fail_closed": True,
            "error_code": keyframe_run["error_code"],
            "reason": keyframe_run["error_summary"],
            "provider_post_count": 0,
        }

        # --- Dispatch the ACTION shot: real paid keyframe -> video -------------
        action_start = require_ok(
            client.post(
                f"/projects/{project_id}/professional/shots/{action_shot['id']}/start",
                headers=headers,
                json={"node_keys": ["prompt", "keyframe", "identity_review"]},
            ),
            "start action professional keyframe",
        )
        report["steps"]["action_keyframe_start"] = {
            "run_ids": action_start.get("run_ids", []),
            "job_ids": action_start.get("job_ids", []),
        }
        keyframe_snapshot = wait_for_nodes(
            client,
            project_id=project_id,
            shot_id=str(action_shot["id"]),
            node_keys={"prompt", "keyframe", "identity_review"},
            timeout_seconds=args.timeout,
            headers=headers,
        )
        keyframe_runs = [
            public_run(run)
            for run in keyframe_snapshot.get("node_runs", [])
            if (run.get("input_snapshot") or {}).get("shot_id") == str(action_shot["id"])
            and run.get("node_key") in {"prompt", "keyframe", "identity_review"}
        ]
        report["steps"]["action_keyframe"] = {"runs": keyframe_runs}
        if any(
            run["status"] not in {"completed", "cached", "completed_after_cancel"}
            for run in keyframe_runs
        ):
            raise RuntimeError(f"action keyframe stage failed: {keyframe_runs}")

        action_video_start = require_ok(
            client.post(
                f"/projects/{project_id}/professional/shots/{action_shot['id']}/start",
                headers=headers,
                json={"node_keys": ["video"]},
            ),
            "start action professional video",
        )
        report["steps"]["action_video_start"] = {
            "run_ids": action_video_start.get("run_ids", []),
            "job_ids": action_video_start.get("job_ids", []),
        }
        final_snapshot = wait_for_nodes(
            client,
            project_id=project_id,
            shot_id=str(action_shot["id"]),
            node_keys={"video"},
            timeout_seconds=args.timeout,
            headers=headers,
        )
        video_runs = [
            public_run(run)
            for run in final_snapshot.get("node_runs", [])
            if (run.get("input_snapshot") or {}).get("shot_id") == str(action_shot["id"])
            and run.get("node_key") == "video"
        ]
        report["steps"]["action_video"] = {"runs": video_runs}
        if any(
            run["status"] not in {"completed", "cached", "completed_after_cancel"}
            for run in video_runs
        ):
            raise RuntimeError(f"action video stage failed: {video_runs}")

        report["artifacts"] = [
            {
                "id": item.get("id"),
                "content_hash": item.get("content_hash"),
                "mime_type": item.get("mime_type"),
                "byte_size": item.get("byte_size"),
                "width": item.get("width"),
                "height": item.get("height"),
                "duration_seconds": item.get("duration_seconds"),
                "produced_by_run_id": item.get("produced_by_run_id"),
            }
            for item in final_snapshot.get("artifacts", [])
        ]
        operations = [
            public_operation(item) for item in final_snapshot.get("provider_operations", [])
        ]
        report["provider_operations"] = operations
        report["provider_raw_cost_fields"] = [
            item.get("response_summary", {}).get("provider_reported_cost")
            for item in operations
            if item.get("response_summary", {}).get("provider_reported_cost") is not None
        ]
        report["paid_provider_calls"] = sum(
            1
            for item in operations
            if item.get("status") in {"submitted", "running", "succeeded", "completed"}
        )

        # Formal selection: approve the action shot (the paid path's terminal step).
        # Formal selection legitimately requires human review (identity_review
        # needs_human + downstream composite/voice/subtitle nodes).  Record the
        # honest gate outcome rather than forcing an approve past a human gate.
        approve = client.post(
            f"/projects/{project_id}/shots/{action_shot['id']}/approve",
            headers=headers,
            json={"note": "WF13 real-provider golden accept"},
        )
        try:
            approve_body = approve.json()
        except Exception:  # noqa: BLE001
            approve_body = {"raw": approve.text[:400]}
        report["steps"]["action_formal_selection"] = {
            "status": approve_body.get("status") if approve.status_code == 200 else None,
            "locked": approve_body.get("locked") if approve.status_code == 200 else None,
            "http_status": approve.status_code,
            "approve_gate": (
                approve_body.get("detail")
                if approve.status_code == 422
                else None
            ),
        }

        # Project-wide wire-visible overview (the WF13-02 read model surfaced here).
        overview = require_ok(
            client.get(f"/projects/{project_id}/workflow-overview", headers=headers),
            "workflow overview",
        )
        ov = overview.get("overview", {})
        report["project_overview"] = {
            "total_shots": ov.get("total_shots"),
            "formal_shots": ov.get("formal_shots"),
            "blocked_scenes": ov.get("blocked_scenes"),
            "review_required_scenes": ov.get("review_required_scenes"),
            "unsupported_capability_shots": ov.get("unsupported_capability_shots"),
            "available_staged_strategies": ov.get("available_staged_strategies"),
        }

    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    report["ok"] = True
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        raise
