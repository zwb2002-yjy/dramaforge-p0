#!/usr/bin/env python3
"""Prove the audited manual-media 10-shot path through the real HTTP API.

This is intentionally separate from live Agent/Provider evidence. It proves
that an operator can complete every frozen Shot node with an audited upload,
approve all ten Shots, and receive reproducible timeline/SRT/package/MP4
exports without silently invoking a Fake or paid Provider.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

REPO = Path(__file__).resolve().parents[1]
NODE_KEYS = (
    "prompt",
    "keyframe",
    "identity_review",
    "video",
    "video_drift_review",
    "voice",
    "subtitle",
    "composite",
    "continuity_review",
)
DONE_STATUSES = {"completed", "cached", "completed_after_cancel"}

# A valid 1x1 PNG is sufficient for audited operator input and lets the export
# service exercise its image-frame FFmpeg fallback without fabricating a video.
PNG_TEMPLATE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
MP4_TEMPLATE = base64.b64decode(
    "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAMUbW9vdgAAAGxtdmhkAAAAAAAAAAAAAAAAAAAD6AAAA+gAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAj90cmFrAAAAXHRra2QAAAADAAAAAAAAAAAAAAABAAAAAAAAA+gAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAABAAAAAQAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAPoAAAAAAABAAAAAAG3bWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAABAAAAAQABVxAAAAAAALWhkbHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAABYm1pbmYAAAAUdm1oZAAAAAEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAASJzdGJsAAAAvnN0c2QAAAAAAAAAAQAAAK5hdmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAABAAEABIAAAASAAAAAAAAAABFExhdmM2MC4zLjEwMCBsaWJ4MjY0AAAAAAAAAAAAAAAAGP//AAAANGF2Y0MBZAAK/+EAF2dkAAqs2V7ARAAAAwAEAAADAAg8SJZYAQAGaOvjyyLA/fj4AAAAABBwYXNwAAAAAQAAAAEAAAAUYnJ0dAAAAAAAABW4AAAVuAAAABhzdHRzAAAAAAAAAAEAAAABAABAAAAAABxzdHNjAAAAAAAAAAEAAAABAAAAAQAAAAEAAAAUc3RzegAAAAAAAAK3AAAAAQAAABRzdGNvAAAAAAAAAAEAAANEAAAAYXVkdGEAAABZbWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAbWRpcmFwcGwAAAAAAAAAAAAAAAAsaWxzdAAAACSpdG9vAAAAHGRhdGEAAAABAAAAAExhdmY2MC4zLjEwMAAAAAhmcmVlAAACv21kYXQAAAKfBgX//5vcRem95tlIt5Ys2CDZI+7veDI2NCAtIGNvcmUgMTQ4IC0gSC4yNjQvTVBFRy00IEFWQyBjb2RlYyAtIENvcHlsZWZ0IDIwMDMtMjAxNiAtIGh0dHA6Ly93d3cudmlkZW9sYW4ub3JnL3gyNjQuaHRtbCAtIG9wdGlvbnM6IGNhYmFjPTEgcmVmPTMgZGVibG9jaz0xOjA6MCBhbmFseXNlPTB4MzoweDExMyBtZT1oZXggc3VibWU9NyBwc3k9MSBwc3lfcmQ9MS4wMDowLjAwIG1peGVkX3JlZj0xIG1lX3JhbmdlPTE2IGNocm9tYV9tZT0xIHRyZWxsaXM9MSA4eGRjdD0xIGNxbT0wIGRlYWR6b25lPTIxLDExIGZhc3RfcHNraXA9MSBjaHJvbWFfcXBfb2Zmc2V0PS0yIHRocmVhZHM9MSBsb29rYWhlYWRfdGhyZWFkcz0xIHNsaWNlZF90aHJlYWRzPTAgbnI9MCBkZWNpbWF0ZT0xIGludGVybGFjZWQ9MCBibHVyYXlfY29tcGF0PTAgY29uc3RyYWluZWRfaW50cmE9MCBiZnJhbWVzPTMgYl9weXJhbWlkPTIgYl9hZGFwdD0xIGJfYmlhcz0wIGRpcmVjdD0wIHdlaWdodGI9MSBvcGVuX2dvcD0wIHdlaWdodHA9MiBrZXlpbnQ9MjUwIGtleWludF9taW49MSBzY2VuZWN1dD00MCBpbnRyYV9yZWZyZXNoPTAgcmNfbG9va2FoZWFkPTQwIHJjPWNyZiBtYnRyZWU9MSBjcmY9MjMuMCBxY29tcGE9MC42MCBxcG1pbj0wIHFwbWF4PTY5IHFwc3RlcD00IGlwX3JhdGlvPTEuNDAgYXE9MToxLjAwAIAAAAAQZYiEABX//vfJ78Cm69vfgQ=="
)


def _problem(response: httpx.Response) -> str:
    return f"{response.status_code} {response.text[:300]}"


def _png_bytes(seed: str) -> bytes:
    """Add a valid PNG text chunk so every image Artifact has a unique hash."""
    payload = b"Comment\0" + seed.encode("ascii")
    chunk = (
        struct.pack(">I", len(payload))
        + b"tEXt"
        + payload
        + struct.pack(">I", __import__("zlib").crc32(b"tEXt" + payload) & 0xFFFFFFFF)
    )
    marker = b"\x00\x00\x00\x00IEND"
    index = PNG_TEMPLATE.rfind(marker)
    if index < 0:
        raise RuntimeError("PNG template has no IEND chunk")
    return PNG_TEMPLATE[:index] + chunk + PNG_TEMPLATE[index:]


def _upload_payload(node_key: str, seed: str) -> tuple[str, bytes, str]:
    if node_key in {"prompt", "keyframe", "identity_review"}:
        return f"{node_key}.png", _png_bytes(seed), "image/png"
    if node_key in {"video", "composite"}:
        return f"{node_key}.mp4", MP4_TEMPLATE + seed.encode("ascii"), "video/mp4"
    if node_key == "voice":
        return f"{node_key}.wav", f"manual-wav:{seed}".encode("ascii"), "audio/wav"
    if node_key == "subtitle":
        return (
            f"{node_key}.srt",
            f"1\n00:00:00,000 --> 00:00:02,000\nManual {seed}\n".encode("utf-8"),
            "application/x-subrip",
        )
    if node_key == "continuity_review":
        return (
            f"{node_key}.json",
            json.dumps({"status": "passed", "seed": seed}, sort_keys=True).encode(),
            "application/json",
        )
    if node_key == "video_drift_review":
        return (
            f"{node_key}.json",
            json.dumps({"status": "passed", "seed": seed}, sort_keys=True).encode(),
            "application/json",
        )
    raise ValueError(f"unsupported node key: {node_key}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--script-file", type=Path, required=True)
    parser.add_argument("--idea", required=True)
    args = parser.parse_args()
    script_file = args.script_file.resolve()
    if not script_file.is_file():
        parser.error(f"script file does not exist: {script_file}")
    args.out.mkdir(parents=True, exist_ok=True)

    client = httpx.Client(base_url=args.base.rstrip("/"), timeout=120.0)
    cookies: dict[str, str] = {}
    report: dict[str, Any] = {
        "scope": "audited manual media 10-shot product path",
        "provider_calls": 0,
        "manual_media": True,
        "node_keys": list(NODE_KEYS),
        "ok": False,
    }

    def csrf() -> str:
        response = client.get("/api/v1/auth/csrf", cookies=cookies)
        response.raise_for_status()
        cookies.update(response.cookies)
        return str(response.json()["csrf_token"])

    def post(
        path: str,
        body: dict[str, Any] | None = None,
        *,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        response = client.post(
            path,
            json=body or {},
            params=params,
            cookies=cookies,
            headers={"X-CSRF-Token": csrf(), "Content-Type": "application/json"},
        )
        cookies.update(response.cookies)
        return response

    def upload(project_id: str, shot_id: str, node_key: str) -> httpx.Response:
        token = csrf()
        note = f"P0 manual evidence {shot_id[:8]} {node_key}"
        filename, data, mime = _upload_payload(node_key, f"{shot_id}:{node_key}")
        return client.post(
            f"/api/v1/projects/{project_id}/shots/{shot_id}/manual-media",
            data={"node_key": node_key, "note": note},
            files={"file": (filename, data, mime)},
            cookies=cookies,
            headers={"X-CSRF-Token": token},
        )

    try:
        health = client.get("/health")
        health.raise_for_status()
        report["health"] = health.json()
        email = f"manual-{uuid4().hex[:10]}@example.com"
        registered = post(
            "/api/v1/auth/register",
            {"email": email, "password": "password123", "display_name": "Manual Proof"},
        )
        if registered.status_code not in (200, 201):
            raise RuntimeError(f"register failed: {_problem(registered)}")
        workspace = post("/api/v1/workspaces", {"name": f"Manual-{uuid4().hex[:8]}"})
        if workspace.status_code not in (200, 201):
            raise RuntimeError(f"workspace failed: {_problem(workspace)}")
        workspace_id = str(workspace.json()["id"])
        client.headers["X-Workspace-Id"] = workspace_id

        created = post(
            "/api/v1/creation/start-project",
            {
                "workspace_id": workspace_id,
                "name": f"P0 Manual Evidence {uuid4().hex[:6]}",
                "aspect_ratio": "9:16",
                "experience_mode": "workbench",
                "idea": args.idea,
            },
        )
        if created.status_code not in (200, 201):
            raise RuntimeError(f"project failed: {_problem(created)}")
        project_id = str(created.json()["project_id"])
        imported = post(
            f"/api/v1/projects/{project_id}/scripts/import",
            {
                "filename": script_file.name,
                "text": script_file.read_text(encoding="utf-8"),
                "register_lead": False,
            },
        )
        if imported.status_code not in (200, 201):
            raise RuntimeError(f"script import failed: {_problem(imported)}")
        shots_response = client.get(f"/api/v1/projects/{project_id}/shots", cookies=cookies)
        shots_response.raise_for_status()
        shots = shots_response.json()
        if len(shots) != 10:
            raise RuntimeError(f"expected 10 shots, got {len(shots)}")

        uploads: list[dict[str, Any]] = []
        for shot in shots:
            shot_id = str(shot["id"])
            for node_key in NODE_KEYS:
                response = upload(project_id, shot_id, node_key)
                if response.status_code not in (200, 201):
                    raise RuntimeError(
                        f"manual upload failed shot={shot_id} node={node_key}: {_problem(response)}"
                    )
                body = response.json()
                uploads.append(
                    {
                        "shot_id": shot_id,
                        "node_key": node_key,
                        "artifact_id": body["artifact_id"],
                        "object_key": body["object_key"],
                        "content_hash": body["content_hash"],
                    }
                )

        approvals: list[str] = []
        for shot in shots:
            shot_id = str(shot["id"])
            approved = post(
                f"/api/v1/projects/{project_id}/shots/{shot_id}/approve",
                {"note": "audited manual P0 evidence"},
            )
            if approved.status_code != 200:
                raise RuntimeError(f"approve failed shot={shot_id}: {_problem(approved)}")
            approvals.append(shot_id)

        exported = post(f"/api/v1/projects/{project_id}/exports", {})
        if exported.status_code not in (200, 201):
            raise RuntimeError(f"export failed: {_problem(exported)}")
        export = exported.json()
        grant = post(
            f"/api/v1/projects/{project_id}/exports/{export['export_id']}/download-grant",
            {},
            params={"object_role": "package"},
        )
        if grant.status_code not in (200, 201):
            raise RuntimeError(f"download grant failed: {_problem(grant)}")
        token = str(grant.json()["token"])
        package = client.get(
            f"/api/v1/projects/{project_id}/exports/{export['export_id']}/download",
            params={"token": token, "object_role": "package"},
            cookies=cookies,
        )
        if package.status_code != 200 or not package.content:
            raise RuntimeError(f"package download failed: {_problem(package)}")
        package_hash = hashlib.sha256(package.content).hexdigest()
        with zipfile.ZipFile(BytesIO(package.content)) as archive:
            names = archive.namelist()
        snapshot = client.get(f"/api/v1/projects/{project_id}/snapshot", cookies=cookies)
        snapshot.raise_for_status()
        state = snapshot.json()
        runs = state.get("node_runs") or []
        artifacts = state.get("artifacts") or []
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for run in runs:
            snap = run.get("input_snapshot") or {}
            key = (str(snap.get("shot_id") or ""), str(snap.get("node_key") or ""))
            if key[0] and key[1] in NODE_KEYS:
                latest[key] = run
        lineage_ok = True
        artifact_ids: set[str] = set()
        object_keys: set[str] = set()
        artifacts_by_id = {str(a["id"]): a for a in artifacts}
        for shot in shots:
            for node_key in NODE_KEYS:
                run = latest.get((str(shot["id"]), node_key))
                artifact = artifacts_by_id.get(str((run or {}).get("result_artifact_id") or ""))
                if run is None or run.get("status") not in DONE_STATUSES or artifact is None:
                    lineage_ok = False
                    continue
                if str(artifact.get("produced_by_run_id")) != str(run.get("id")):
                    lineage_ok = False
                artifact_ids.add(str(artifact["id"]))
                object_keys.add(str(artifact["object_key"]))
        report.update(
            {
                "project_id": project_id,
                "shot_count": len(shots),
                "uploads": len(uploads),
                "approvals": len(approvals),
                "node_runs": len(runs),
                "artifacts": len(artifacts),
                "lineage_artifacts": len(artifact_ids),
                "lineage_object_keys": len(object_keys),
                "lineage_ok": lineage_ok,
                "package_hash_api": export.get("package_hash"),
                "package_hash_download": package_hash,
                "mp4_object_key": export.get("mp4_object_key"),
                "mp4_hash": export.get("mp4_hash"),
                "zip_names": names,
            }
        )
        report["ok"] = bool(
            len(uploads) == 90
            and len(approvals) == 10
            and len(artifact_ids) == 90
            and len(object_keys) == 90
            and lineage_ok
            and package_hash == export.get("package_hash")
            and export.get("mp4_object_key")
            and export.get("mp4_hash")
            and any(name.endswith(".srt") for name in names)
            and any("timeline" in name for name in names)
            and any(name.startswith("media/") for name in names)
        )
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        (args.out / "manual_media_10_shot.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        client.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
