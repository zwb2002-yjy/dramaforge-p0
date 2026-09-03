#!/usr/bin/env python3
"""Current-HEAD V1 Golden: real Provider -> Formal -> EditSession -> Export.

This proof uses the authenticated professional API.  It creates one
Template + AUTO project and one Free + ASSIST project, imports the same
canonical script into both, runs the real Provider chain on the Template
project, marks each produced keyframe/video Formal, builds one OpenCut
EditSession, and exports a final timeline manifest.  It records only redacted
request/result metadata; credentials, signed URLs and raw Provider payloads
are never written.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import shutil
import subprocess
import sys
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


def public_operation(operation: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": operation.get("id"),
        "node_run_id": operation.get("node_run_id"),
        "operation_kind": operation.get("operation_kind"),
        "actual_provider": operation.get("actual_provider"),
        "actual_model": operation.get("actual_model"),
        "provider_request_id": operation.get("provider_request_id"),
        "protocol_profile": operation.get("protocol_profile"),
        "status": operation.get("status"),
        "request_fingerprint": operation.get("request_fingerprint"),
        "request_summary": operation.get("request_summary", {}),
        "response_summary": operation.get("response_summary", {}),
        "model_binding_id": operation.get("model_binding_id"),
        "catalog_entry_id": operation.get("catalog_entry_id"),
        "capability_manifest_hash": operation.get("capability_manifest_hash"),
        "connection_id": operation.get("connection_id"),
        "provider_connection_revision_id": operation.get("provider_connection_revision_id"),
        "credential_revision_id": operation.get("credential_revision_id"),
        "execution_path_version": operation.get("execution_path_version"),
        "provider_cost": operation.get("provider_cost"),
        "currency": operation.get("currency"),
        "submitted_at": operation.get("submitted_at"),
        "completed_at": operation.get("completed_at"),
    }


def public_run(run: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(run.get("input_snapshot") or {})
    identity = snapshot.get("execution_identity")
    frozen_identity = dict(identity) if isinstance(identity, dict) else {}
    return {
        "id": run.get("id"),
        "attempt_no": run.get("attempt_no"),
        "status": run.get("status"),
        "node_key": run.get("node_key"),
        "result_artifact_id": run.get("result_artifact_id"),
        "error_code": run.get("error_code"),
        "error_summary": run.get("error_summary"),
        "input_hash": run.get("input_hash"),
        "duration_seconds": snapshot.get("duration_seconds"),
        "execution_branch": snapshot.get("execution_branch"),
        "model_binding_id": snapshot.get("model_binding_id"),
        "model_profile": snapshot.get("model_profile"),
        "canonical_artifact_id": snapshot.get("canonical_artifact_id"),
        "connection_revision_id": frozen_identity.get("connection_revision_id"),
        "credential_revision_id": frozen_identity.get("credential_revision_id"),
        "execution_model_resolution": snapshot.get("execution_model_resolution"),
        "request_fingerprint": run.get("input_hash"),
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
    terminal_success = {"completed", "cached", "completed_after_cancel"}
    terminal_failure = {"failed", "blocked", "cancelled"}
    deadline = time.monotonic() + timeout_seconds
    last_snapshot: dict[str, Any] = {}
    while time.monotonic() < deadline:
        snapshot = require_ok(
            client.get(f"/projects/{project_id}/snapshot", headers=headers),
            "snapshot",
        )
        last_snapshot = snapshot
        runs = []
        for run in snapshot.get("node_runs", []):
            run_snapshot = run.get("input_snapshot") or {}
            if run_snapshot.get("shot_id") != shot_id or run.get("node_key") not in node_keys:
                continue
            if run_snapshot.get("experiment_id") is not None:
                continue
            if run_snapshot.get("execution_branch") not in (None, "formal"):
                continue
            runs.append(run)
        latest: dict[str, dict[str, Any]] = {}
        for run in runs:
            key = str(run.get("node_key"))
            current = latest.get(key)
            if current is None or (
                int(run.get("attempt_no") or 0),
                str(run.get("id") or ""),
            ) > (
                int(current.get("attempt_no") or 0),
                str(current.get("id") or ""),
            ):
                latest[key] = run
        if latest and set(latest) >= node_keys and all(
            run.get("status") in {*terminal_success, *terminal_failure}
            for run in latest.values()
        ):
            failures = [public_run(run) for run in latest.values() if run.get("status") in terminal_failure]
            if failures:
                raise RuntimeError(
                    "node failed: " + json.dumps(failures, ensure_ascii=False, default=str)
                )
            if all(run.get("status") in terminal_success for run in latest.values()):
                return snapshot
        time.sleep(3)
    raise TimeoutError(
        f"timed out waiting for {sorted(node_keys)}; last runs="
        f"{[public_run(run) for run in last_snapshot.get('node_runs', [])]}"
    )


def wait_for_project_node_keys(
    client: httpx.Client,
    *,
    project_id: str,
    shot_ids: list[str],
    node_keys: set[str],
    timeout_seconds: int,
    headers: Mapping[str, str],
) -> dict[str, Any]:
    expected = {(shot_id, node_key) for shot_id in shot_ids for node_key in node_keys}
    deadline = time.monotonic() + timeout_seconds
    last_snapshot: dict[str, Any] = {}
    while time.monotonic() < deadline:
        snapshot = require_ok(
            client.get(f"/projects/{project_id}/snapshot", headers=headers),
            "snapshot",
        )
        last_snapshot = snapshot
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for run in snapshot.get("node_runs", []):
            shot_id = str((run.get("input_snapshot") or {}).get("shot_id") or "")
            key = str((run.get("input_snapshot") or {}).get("node_key") or "")
            identity = (shot_id, key)
            run_snapshot = run.get("input_snapshot") or {}
            if run_snapshot.get("experiment_id") is not None:
                continue
            if run_snapshot.get("execution_branch") not in (None, "formal"):
                continue
            if identity in expected:
                current = latest.get(identity)
                if current is None or (
                    int(run.get("attempt_no") or 0),
                    run.get("created_at") or "",
                    str(run.get("id") or ""),
                ) > (
                    int(current.get("attempt_no") or 0),
                    current.get("created_at") or "",
                    str(current.get("id") or ""),
                ):
                    latest[identity] = run
        if len(latest) == len(expected):
            failures = [
                public_run(run)
                for run in latest.values()
                if run.get("status")
                not in {"completed", "cached", "completed_after_cancel"}
            ]
            if failures:
                raise RuntimeError(
                    "tail node failed: " + json.dumps(failures, ensure_ascii=False, default=str)
                )
            return snapshot
        time.sleep(3)
    raise TimeoutError(
        f"timed out waiting for {sorted(expected)}; last runs="
        f"{[public_run(run) for run in last_snapshot.get('node_runs', [])]}"
    )


def dispatch_stage(
    client: httpx.Client,
    *,
    project_id: str,
    shot_id: str,
    stage: str,
    prompt: str,
    expected_shot_version: int,
    headers: Mapping[str, str],
    idempotency_key: str,
) -> dict[str, Any]:
    """Preview and dispatch one frozen canonical Workbench execution."""
    payload = {
        "stage": stage,
        "prompt": prompt,
        "semantic_intent": {"intent": stage, "shot_id": shot_id},
        "mode_id": "text_to_image" if stage == "image_keyframe" else "first_frame",
        "references": [],
        "expected_shot_version": expected_shot_version,
    }
    preview = require_ok(
        client.post(
            f"/projects/{project_id}/shots/{shot_id}/execution-plan",
            headers=headers,
            json=payload,
        ),
        f"preview {stage}",
    )
    return require_ok(
        client.post(
            f"/projects/{project_id}/shots/{shot_id}/executions",
            headers={**headers, "Idempotency-Key": idempotency_key},
            json={
                **payload,
                "plan_fingerprint": preview["plan_fingerprint"],
                "accepted_approximations": preview["plan"].get(
                    "accepted_approximations", []
                ),
            },
        ),
        f"dispatch {stage}",
    )


def mark_formal(
    client: httpx.Client,
    *,
    project_id: str,
    shot_id: str,
    stage: str,
    artifact_id: str,
    expected_shot_version: int,
    headers: Mapping[str, str],
) -> dict[str, Any]:
    return require_ok(
        client.post(
            f"/projects/{project_id}/shots/{shot_id}/formal-{stage}",
            headers=headers,
            json={
                "artifact_id": artifact_id,
                "expected_shot_version": expected_shot_version,
            },
        ),
        f"formal {stage}",
    )


def create_project(
    client: httpx.Client,
    *,
    workspace_id: str,
    headers: Mapping[str, str],
    name: str,
    start_type: str,
    template_key: str | None,
    director_autonomy: str,
) -> dict[str, Any]:
    return require_ok(
        client.post(
            "/projects",
            headers=headers,
            json={
                "workspace_id": workspace_id,
                "name": name,
                "aspect_ratio": "9:16",
                "target_platform": "general",
                "start_type": start_type,
                "template_key": template_key,
                "template_version": "1" if template_key else None,
                "director_autonomy": director_autonomy,
            },
        ),
        "create project",
    )


def collect_negative_checks(
    client: httpx.Client,
    *,
    project_id: str,
    headers: Mapping[str, str],
) -> dict[str, Any]:
    """Fail-closed probes with controlled inputs; never submit a paid request."""
    shots = require_ok(client.get(f"/projects/{project_id}/shots", headers=headers), "list shots")
    shot = next(iter(shots), None)
    if shot is None:
        raise RuntimeError("negative checks require at least one shot")
    shot_id = str(shot["id"])
    scene_id = str(shot.get("scene_id") or "")
    snapshot_before = require_ok(
        client.get(f"/projects/{project_id}/snapshot", headers=headers), "snapshot before"
    )
    before_runs = len(snapshot_before.get("node_runs", []))

    stale = client.post(
        f"/projects/{project_id}/shots/{shot_id}/recommendation",
        headers=headers,
        json={
            "scene_id": scene_id,
            "shot_id": shot_id,
            "expected_shot_version": int(shot["version"]) + 1000,
        },
    )
    stale_body: dict[str, Any] = {}
    try:
        stale_body = stale.json()
    except Exception:  # noqa: BLE001
        stale_body = {"raw": stale.text[:300]}

    preview_payload = {
        "stage": "image_keyframe",
        "prompt": "controlled fail-closed preview probe",
        "semantic_intent": {"intent": "shot_keyframe", "probe": True},
        "mode_id": "text_to_image",
        "references": [],
        "expected_shot_version": int(shot["version"]),
    }
    preview_one = require_ok(
        client.post(
            f"/projects/{project_id}/shots/{shot_id}/execution-plan",
            headers=headers,
            json=preview_payload,
        ),
        "preview one",
    )
    preview_two = require_ok(
        client.post(
            f"/projects/{project_id}/shots/{shot_id}/execution-plan",
            headers=headers,
            json=preview_payload,
        ),
        "preview two",
    )
    mismatch = client.post(
        f"/projects/{project_id}/shots/{shot_id}/executions",
        headers=headers,
        json={
            **preview_payload,
            "plan_fingerprint": "0" * 64,
            "accepted_approximations": [],
        },
    )
    mismatch_body: dict[str, Any] = {}
    try:
        mismatch_body = mismatch.json()
    except Exception:  # noqa: BLE001
        mismatch_body = {"raw": mismatch.text[:300]}
    snapshot_after = require_ok(
        client.get(f"/projects/{project_id}/snapshot", headers=headers), "snapshot after"
    )
    after_runs = len(snapshot_after.get("node_runs", []))
    if after_runs != before_runs:
        raise RuntimeError("fail-closed probes unexpectedly created a NodeRun")
    return {
        "stale_recommendation": {
            "http_status": stale.status_code,
            "code": stale_body.get("code"),
            "detail": stale_body.get("detail"),
        },
        "plan_preview_deterministic": {
            "same_fingerprint": preview_one.get("plan_fingerprint")
            == preview_two.get("plan_fingerprint"),
            "fingerprint_length": len(preview_one.get("plan_fingerprint") or ""),
        },
        "fingerprint_mismatch_execution": {
            "http_status": mismatch.status_code,
            "code": mismatch_body.get("code"),
            "detail": mismatch_body.get("detail"),
        },
        "no_node_run_created_by_negative_probes": after_runs == before_runs,
    }


def run_resilience_evidence() -> dict[str, Any]:
    """Run the controlled runtime resilience tests offline (no paid Provider)."""
    files = [
        "tests/unit/test_runtime.py",
        "tests/unit/test_litellm_text_bridge.py",
        "tests/unit/test_v3_core_types.py",
        "tests/unit/test_execution_identity.py",
        "tests/unit/test_connection_revisions.py",
        "tests/unit/test_ark_compiler.py",
    ]
    # The production image intentionally omits the dev test entry points, but
    # the exact quality image provides them through its locked uv environment.
    command = [sys.executable, "-m", "pytest", *files, "-q"]
    if shutil.which("pytest") is None and shutil.which("uv") is not None:
        command = ["uv", "run", "--extra", "dev", "pytest", *files, "-q"]
    completed = subprocess.run(
        command,
        cwd=REPO / "backend",
        capture_output=True,
        text=True,
    )
    tail = (completed.stdout or "").strip().splitlines()[-6:]
    errors = (completed.stderr or "").strip().splitlines()[-6:]
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "command": command,
        "summary": tail,
        "stderr_tail": errors,
        "coverage": [
            "timeout -> retry/resume",
            "submit_unknown no blind retry",
            "credential/connection revision identity freeze",
        ],
    }


SCRIPT = """# Episode 1 - Current Head Golden

## Scene 1 - Rooftop / night
One fictional character stands alone on a rooftop and delivers a restrained
emotional monologue to the camera.

### Shot 1 - closeup
Visual: a fictional woman looks away, takes a quiet breath, then lifts her gaze toward the camera, subtle micro-expression, stable composition
Dialogue: 够了。
Camera: static

### Shot 2 - medium
Visual: she turns toward the city lights, one hand tightening, wind moving her hair, real cinematic skin texture
Dialogue: 我明白。
Camera: slow_push

### Shot 3 - closeup
Visual: she faces the camera again, tears in her eyes, chin steady, voice becoming calm, studio-realistic portrait
Dialogue: 我自己来。
Camera: static
"""


def _latest_completed_run(snapshot: dict[str, Any], *, shot_id: str, node_key: str) -> dict[str, Any]:
    candidates = [
        run
        for run in snapshot.get("node_runs", [])
        if ((run.get("input_snapshot") or {}).get("shot_id") == shot_id)
        and (run.get("input_snapshot") or {}).get("experiment_id") is None
        and ((run.get("input_snapshot") or {}).get("execution_branch") in (None, "formal"))
        and run.get("node_key") == node_key
        and run.get("status") in {"completed", "cached", "completed_after_cancel"}
    ]
    if not candidates:
        raise RuntimeError(f"shot {shot_id} {node_key} did not complete")
    return max(
        candidates,
        key=lambda run: (int(run.get("attempt_no") or 0), str(run.get("id") or "")),
    )


def _public_artifacts(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id"),
            "content_hash": item.get("content_hash"),
            "mime_type": item.get("mime_type"),
            "byte_size": item.get("byte_size"),
            "storage_state": item.get("storage_state"),
            "width": item.get("width"),
            "height": item.get("height"),
            "duration_seconds": item.get("duration_seconds"),
            "produced_by_run_id": item.get("produced_by_run_id"),
        }
        for item in snapshot.get("artifacts", [])
    ]


def _public_tail(snapshot: dict[str, Any], shot_ids: list[str]) -> dict[str, Any]:
    expected_keys = {
        "video_drift_review",
        "voice",
        "subtitle",
        "composite",
        "continuity_review",
    }
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for run in snapshot.get("node_runs", []):
        run_snapshot = run.get("input_snapshot") or {}
        if run_snapshot.get("experiment_id") is not None:
            continue
        if run_snapshot.get("execution_branch") not in (None, "formal"):
            continue
        identity = (str(run_snapshot.get("shot_id") or ""), str(run.get("node_key") or ""))
        if identity[0] not in shot_ids or identity[1] not in expected_keys:
            continue
        current = latest.get(identity)
        if current is None or (
            int(run.get("attempt_no") or 0),
            str(run.get("id") or ""),
        ) > (
            int(current.get("attempt_no") or 0),
            str(current.get("id") or ""),
        ):
            latest[identity] = run
    expected_count = len(shot_ids) * len(expected_keys)
    if len(latest) != expected_count:
        raise RuntimeError(f"Final Film tail has {len(latest)} latest runs; expected {expected_count}")
    failures = [public_run(run) for run in latest.values() if run.get("status") not in {"completed", "cached", "completed_after_cancel"}]
    if failures:
        raise RuntimeError("Final Film tail failed: " + json.dumps(failures, ensure_ascii=False, default=str))
    return {
        "runs": [public_run(run) for run in sorted(latest.values(), key=lambda item: (str((item.get("input_snapshot") or {}).get("shot_id")), str(item.get("node_key"))))],
        "latest_identity_count": len(latest),
        "expected_identity_count": expected_count,
        "all_terminal_success": True,
    }


def _render_final_film_concurrently(
    client: httpx.Client,
    *,
    project_id: str,
    session_id: str,
    timeline_version: int,
    headers: Mapping[str, str],
    idempotency_key: str,
) -> list[dict[str, Any]]:
    payload = {
        "edit_session_id": session_id,
        "expected_timeline_version": timeline_version,
        "name": "V1 Current-Head Final Film",
    }
    base_url = str(client.base_url)
    cookies = httpx.Cookies(client.cookies)

    def submit(_: int) -> dict[str, Any]:
        with httpx.Client(
            base_url=base_url,
            cookies=httpx.Cookies(cookies),
            timeout=900.0,
            follow_redirects=True,
            trust_env=False,
        ) as concurrent_client:
            return require_ok(
                concurrent_client.post(
                    f"/projects/{project_id}/final-film/render",
                    headers={**headers, "Idempotency-Key": idempotency_key},
                    json=payload,
                ),
                "concurrent Final Film render",
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        return list(executor.map(submit, (1, 2)))


def run_full_project_chain(
    client: httpx.Client,
    *,
    project: dict[str, Any],
    headers: Mapping[str, str],
    timeout: int,
    label: str,
    imported: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project_id = str(project["id"])
    if imported is None:
        imported = require_ok(
            client.post(
                f"/projects/{project_id}/scripts/import",
                headers=headers,
                json={"filename": f"{label}-current-head-golden.md", "text": SCRIPT},
            ),
            f"import {label} script",
        )
    shot_ids = [str(shot_id) for shot_id in imported["shot_ids"]]
    if not shot_ids:
        raise RuntimeError(f"{label} script import produced no shots")
    shots = require_ok(client.get(f"/projects/{project_id}/shots", headers=headers), f"list {label} shots")
    by_id = {str(item["id"]): item for item in shots}
    shot_evidence: list[dict[str, Any]] = []
    for index, shot_id in enumerate(shot_ids, start=1):
        shot = by_id.get(shot_id)
        if shot is None:
            raise RuntimeError(f"{label} shot {shot_id} not found")
        canvas = require_ok(
            client.patch(
                f"/projects/{project_id}/shots/{shot_id}/canvas",
                headers=headers,
                json={
                    "expected_version": shot["version"],
                    "visual_description": shot["visual_description"],
                    "shot_type": shot["shot_type"],
                    "camera_move": shot["camera_move"],
                    "dialogue": shot["dialogue"],
                    "duration_seconds": "5.000",
                    "source": "user",
                },
            ),
            f"set {label} shot duration",
        )
        canvas_version = canvas["shot"]["version"]
        dispatch_stage(
            client,
            project_id=project_id,
            shot_id=shot_id,
            stage="image_keyframe",
            prompt=shot["visual_description"],
            expected_shot_version=canvas_version,
            headers=headers,
            idempotency_key=f"v1-golden-keyframe-{project_id}-{shot_id}",
        )
        keyframe_snapshot = wait_for_nodes(
            client,
            project_id=project_id,
            shot_id=shot_id,
            node_keys={"keyframe"},
            timeout_seconds=timeout,
            headers=headers,
        )
        keyframe_run = _latest_completed_run(keyframe_snapshot, shot_id=shot_id, node_key="keyframe")
        formal_keyframe = mark_formal(
            client,
            project_id=project_id,
            shot_id=shot_id,
            stage="keyframe",
            artifact_id=str(keyframe_run["result_artifact_id"]),
            expected_shot_version=canvas_version,
            headers=headers,
        )
        dispatch_stage(
            client,
            project_id=project_id,
            shot_id=shot_id,
            stage="video",
            prompt=shot["visual_description"],
            expected_shot_version=formal_keyframe["version"],
            headers=headers,
            idempotency_key=f"v1-golden-video-{project_id}-{shot_id}",
        )
        video_snapshot = wait_for_nodes(
            client,
            project_id=project_id,
            shot_id=shot_id,
            node_keys={"video"},
            timeout_seconds=timeout,
            headers=headers,
        )
        video_run = _latest_completed_run(video_snapshot, shot_id=shot_id, node_key="video")
        formal_video = mark_formal(
            client,
            project_id=project_id,
            shot_id=shot_id,
            stage="video",
            artifact_id=str(video_run["result_artifact_id"]),
            expected_shot_version=formal_keyframe["version"],
            headers=headers,
        )
        shot_evidence.append(
            {
                "shot_id": shot_id,
                "order": index,
                "keyframe_run_id": str(keyframe_run["id"]),
                "keyframe_artifact_id": str(keyframe_run["result_artifact_id"]),
                "formal_keyframe_version": formal_keyframe["version"],
                "video_run_id": str(video_run["id"]),
                "video_artifact_id": str(video_run["result_artifact_id"]),
                "formal_video_version": formal_video["version"],
            }
        )

    opencut = require_ok(
        client.get(f"/projects/{project_id}/opencut-manifest", headers=headers),
        f"{label} OpenCut manifest",
    )
    edit_session = require_ok(
        client.post(
            f"/projects/{project_id}/edit-sessions",
            headers=headers,
            json={"name": f"V1 {label} Current-Head Final Cut"},
        ),
        f"create {label} edit session",
    )
    edit_export = require_ok(
        client.get(
            f"/projects/{project_id}/edit-sessions/{edit_session['id']}/export",
            headers=headers,
        ),
        f"export {label} edit session",
    )
    prepare = require_ok(
        client.post(
            f"/projects/{project_id}/final-film/prepare",
            headers=headers,
            json={
                "edit_session_id": edit_session["id"],
                "expected_timeline_version": edit_session["version"],
            },
        ),
        f"prepare {label} Final Film tail",
    )
    tail_snapshot = wait_for_project_node_keys(
        client,
        project_id=project_id,
        shot_ids=shot_ids,
        node_keys={
            "video_drift_review",
            "voice",
            "subtitle",
            "composite",
            "continuity_review",
        },
        timeout_seconds=timeout,
        headers=headers,
    )
    tail_evidence = _public_tail(tail_snapshot, shot_ids)
    idempotency_key = f"frozen-final-film-{project_id}-{edit_session['id']}-{edit_session['version']}"
    render_results = _render_final_film_concurrently(
        client,
        project_id=project_id,
        session_id=str(edit_session["id"]),
        timeline_version=int(edit_session["version"]),
        headers=headers,
        idempotency_key=idempotency_key,
    )
    first_render = render_results[0]
    idempotency = {
        "same_export_id": all(item.get("export_id") == first_render.get("export_id") for item in render_results),
        "same_artifact_id": all(item.get("artifact_id") == first_render.get("artifact_id") for item in render_results),
        "request_count": len(render_results),
        "concurrent": True,
        "export_id": first_render.get("export_id"),
        "artifact_id": first_render.get("artifact_id"),
    }
    if not idempotency["same_export_id"] or not idempotency["same_artifact_id"]:
        raise RuntimeError(f"{label} Final Film idempotency failed: {idempotency}")
    final_snapshot = require_ok(
        client.get(f"/projects/{project_id}/snapshot", headers=headers),
        f"final {label} snapshot",
    )
    artifact_by_id = {str(item.get("id")): item for item in final_snapshot.get("artifacts", [])}
    final_artifact = artifact_by_id.get(str(first_render.get("artifact_id")))
    if final_artifact is None:
        raise RuntimeError(f"{label} Final Film Artifact is missing from the project snapshot")
    if final_artifact.get("produced_by_run_id") != first_render.get("node_run_id"):
        raise RuntimeError(f"{label} Final Film Artifact has incomplete NodeRun lineage")
    probe = first_render.get("ffprobe") or {}
    assertions = probe.get("assertions") if isinstance(probe, dict) else None
    if not isinstance(assertions, dict) or not all(assertions.values()):
        raise RuntimeError(f"{label} Final Film media assertions failed: {assertions}")
    duration = float(first_render.get("duration_seconds") or 0)
    if not 15 <= duration <= 30:
        raise RuntimeError(f"{label} Final Film duration is outside 15-30 seconds: {duration}")
    if first_render.get("mime_type") != "video/mp4" or not first_render.get("content_hash") or int(first_render.get("byte_size") or 0) <= 0 or first_render.get("storage_state") != "available":
        raise RuntimeError(f"{label} Final Film Artifact metadata is incomplete")
    formal_references = first_render.get("formal_references")
    if not isinstance(formal_references, list) or len(formal_references) != len(shot_ids):
        raise RuntimeError(f"{label} Final Film Formal reference lineage is incomplete")
    media_freeze = [
        {
            "shot_id": (run.get("input_snapshot") or {}).get("shot_id"),
            "node_key": (run.get("input_snapshot") or {}).get("node_key"),
            "source_commit": (run.get("input_snapshot") or {}).get("source_commit"),
            "model_binding_id": (run.get("input_snapshot") or {}).get("model_binding_id"),
            "connection_revision_id": (
                (run.get("input_snapshot") or {}).get("execution_identity") or {}
            ).get("connection_revision_id"),
            "credential_revision_id": (
                (run.get("input_snapshot") or {}).get("execution_identity") or {}
            ).get("credential_revision_id"),
            "input_hash": run.get("input_hash"),
            "status": run.get("status"),
        }
        for run in final_snapshot.get("node_runs", [])
        if (run.get("input_snapshot") or {}).get("node_key") in {"keyframe", "video"}
        and (run.get("input_snapshot") or {}).get("shot_id") in shot_ids
        and (run.get("input_snapshot") or {}).get("experiment_id") is None
        and (run.get("input_snapshot") or {}).get("execution_branch") in (None, "formal")
        and run.get("status") in {"completed", "cached", "completed_after_cancel"}
    ]
    if len(media_freeze) != len(shot_ids) * 2 or any(
        not item["connection_revision_id"] or not item["credential_revision_id"] for item in media_freeze
    ):
        raise RuntimeError(f"{label} media execution identity is not fully frozen")
    operations = [public_operation(item) for item in final_snapshot.get("provider_operations", [])]
    paid_operations = [
        item
        for item in operations
        if item.get("actual_provider") not in {"local_tts", "local_ffmpeg", "local"}
    ]
    if len(paid_operations) != len(shot_ids) * 2 or any(item.get("status") != "succeeded" for item in paid_operations):
        raise RuntimeError(f"{label} paid Provider operations are incomplete")
    return {
        "project_id": project_id,
        "profile": project.get("creative_profile"),
        "shot_ids": shot_ids,
        "steps": {"shots": shot_evidence},
        "artifacts": _public_artifacts(final_snapshot),
        "provider_operations": operations,
        "paid_provider_calls": len(paid_operations),
        "provider_raw_cost_fields": [
            item.get("response_summary", {}).get("provider_reported_cost")
            for item in operations
            if item.get("response_summary", {}).get("provider_reported_cost") is not None
        ],
        "opencut": {
            "schema_version": opencut.get("schema_version"),
            "adapter": opencut.get("adapter"),
            "timeline": opencut.get("timeline"),
            "track_kinds": [track.get("kind") for track in opencut.get("tracks", [])],
            "shot_count": len(opencut.get("shots", [])),
            "video_clip_count": sum(
                1
                for track in opencut.get("tracks", [])
                for clip in track.get("clips", [])
                if clip.get("track_kind") == "video"
            ),
        },
        "final_film": {
            "project_id": project_id,
            "edit_session_id": edit_session["id"],
            "session_version": edit_session["version"],
            "timeline_clip_count": len(edit_session["timeline"]["clips"]),
            "timeline_clips": edit_session["timeline"]["clips"],
            "production_lineage": edit_session["production_lineage"],
            "export": edit_export,
        },
        "final_film_prepare": {
            "node_run_ids": prepare.get("node_run_ids", []),
            "shot_ids": prepare.get("shot_ids", []),
            "status": prepare.get("status"),
        },
        "final_film_tail": tail_evidence,
        "final_film_artifact": first_render,
        "final_film_idempotency": idempotency,
        "media_identity_freeze": media_freeze,
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/api/v1")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--negative-checks", action="store_true")
    parser.add_argument("--resilience-checks", action="store_true")
    args = parser.parse_args()
    email = os.environ.get("DRAMAFORGE_PROOF_EMAIL", "professional-proof@example.com")
    password = os.environ.get("DRAMAFORGE_PROOF_PASSWORD", "professional-proof-password-2026")
    report: dict[str, Any] = {
        "schema_version": 2,
        "proof": "dramaforge-v1-current-head-golden",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "source_commit": commit(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO)),
        "paid_provider_calls": 0,
        "provider_raw_cost_fields": [],
        "projects": {},
    }
    try:
        with httpx.Client(
            base_url=args.base_url,
            timeout=60.0,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            bootstrap = require_ok(client.get("/auth/bootstrap-status"), "bootstrap status")
            if bootstrap.get("owner_initialized"):
                require_ok(client.post("/auth/login", json={"email": email, "password": password}), "login")
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
            template_project = create_project(
                client,
                workspace_id=workspace_id,
                headers=headers,
                name=f"Template AUTO Golden {uuid4().hex[:8]}",
                start_type="TEMPLATE",
                template_key="single_monologue_v1",
                director_autonomy="AUTO",
            )
            free_project = create_project(
                client,
                workspace_id=workspace_id,
                headers=headers,
                name=f"Free ASSIST Golden {uuid4().hex[:8]}",
                start_type="FREE",
                template_key=None,
                director_autonomy="ASSIST",
            )
            projects = {"template_auto": template_project, "free_assist": free_project}
            connections = require_ok(
                client.get(f"/workspaces/{workspace_id}/provider-connections", headers=headers),
                "list provider connections",
            )
            connection = next(
                (item for item in connections if item.get("provider_type") == "agnes" and item.get("enabled")),
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
                for project in projects.values():
                    require_ok(
                        client.put(
                            f"/projects/{project['id']}/provider-bindings/{purpose}",
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
            if args.dry_run:
                report["dry_run"] = True
                report["projects"] = {
                    label: {"project_id": str(project["id"]), "profile": project["creative_profile"], "full_real_chain": False}
                    for label, project in projects.items()
                }
                report["ok"] = True
            else:
                # Import both paths before any execution so negative probes prove
                # that preview/stale rejection does not materialize a NodeRun.
                imported_by_label: dict[str, dict[str, Any]] = {}
                for label, project in projects.items():
                    imported_by_label[label] = require_ok(
                        client.post(
                            f"/projects/{project['id']}/scripts/import",
                            headers=headers,
                            json={"filename": f"{label}-current-head-golden.md", "text": SCRIPT},
                        ),
                        f"import {label} script",
                    )
                peer_imported = imported_by_label["free_assist"]
                if args.negative_checks:
                    report["negative_checks"] = collect_negative_checks(
                        client,
                        project_id=str(free_project["id"]),
                        headers=headers,
                    )
                if args.resilience_checks:
                    report["resilience_evidence"] = run_resilience_evidence()
                if args.negative_checks and not report["negative_checks"]["no_node_run_created_by_negative_probes"]:
                    raise RuntimeError("negative probes created a NodeRun")
                if args.resilience_checks and not report["resilience_evidence"]["ok"]:
                    raise RuntimeError("runtime resilience evidence failed")
                for label, project in projects.items():
                    result = run_full_project_chain(
                        client,
                        project=project,
                        headers=headers,
                        timeout=args.timeout,
                        label=label,
                        imported=imported_by_label[label],
                    )
                    result["full_real_chain"] = True
                    report["projects"][label] = result
                    report["paid_provider_calls"] += int(result["paid_provider_calls"])
                    report["provider_raw_cost_fields"].extend(result["provider_raw_cost_fields"])
                if set(report["projects"]) != {"template_auto", "free_assist"}:
                    raise RuntimeError("both required Golden paths did not complete")
                if len(report["projects"]["template_auto"]["shot_ids"]) != len(report["projects"]["free_assist"]["shot_ids"]):
                    raise RuntimeError("dual paths did not use equal shot counts")
                report["free_assist_imported_shot_ids"] = [str(item) for item in peer_imported["shot_ids"]]
                report["ok"] = True
    except Exception as exc:  # noqa: BLE001 - write a truthful failing evidence artifact
        report["ok"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    _write_report(args.out, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        raise
