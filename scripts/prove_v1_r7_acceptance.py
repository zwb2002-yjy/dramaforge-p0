#!/usr/bin/env python3
"""Checkpointed R7 real acceptance through authenticated canonical HTTP APIs.

Default preflight performs no Provider calls. --real is required for text/media
phases. Unknown writes are never automatically retried; completed steps restore
persisted responses, and media receipts are read by their original command key.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = "c00b1899-b4ac-46c7-b4c7-25a230e9ebe2"
SECRET_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "password",
    "api_key",
    "apikey",
    "ciphertext",
    "secret",
    "token",
    "access_token",
    "signed_url",
    "source_url",
    "artifact_uri",
    "wire_request",
    "wire_response",
    "raw_response",
}
BRIEF = (
    "请创作一部约25秒、五个叙事镜头的写实短片《渡口天亮》。只有一位成年虚构男性主角，"
    "在清晨渡口发现一台旧录音机，倾听、迟疑、释然，然后把它留在长椅上转身登船。"
    "服装始终是深蓝夹克，不要推镜，固定摄影机，通过景别和动作推进情绪。"
    "五个镜头是这次创作要求，不是产品默认镜头数。每句中文对白不超过六个字，"
    "另给一个可以删除的收尾镜头。视觉描述用清晰英文，真人电影质感，不要动画或字幕文字入画。"
)
FREE_SCRIPT = (
    "\n".join(
        [
            ("# Episode 1 - A letter before dawn"),
            ("## Scene 1 - Quiet apartment / morning"),
            (
                "An adult fictional woman reads an old letter and decides to reconnec"
                "t with a friend."
            ),
            ("### Shot 1 - wide"),
            (
                "Visual: live-action cinematic morning interior, adult fictional woma"
                "n with short black hair in a beige cardigan stands beside a wooden t"
                "able, static camera, warm dawn window light"
            ),
            ("Dialogue: 天亮了。"),
            ("### Shot 2 - closeup"),
            (
                "Visual: live-action closeup of the same fictional woman with short b"
                "lack hair and beige cardigan unfolding an old letter, subtle express"
                "ion, static camera, no camera push-in"
            ),
            ("Dialogue: 我记得。"),
            ("### Shot 3 - medium"),
            (
                "Visual: live-action medium shot of the same fictional woman in beige"
                " cardigan smiling gently as she holds the letter beside a window, st"
                "atic camera"
            ),
            ("Dialogue: 再试一次。"),
            ("### Shot 4 - wide"),
            (
                "Visual: live-action wide shot of the same fictional woman in beige c"
                "ardigan placing the letter on the wooden table and walking toward th"
                "e door, warm dawn light, fixed camera"
            ),
            ("Dialogue: 现在出发。"),
        ]
    )
    + "\n"
)
FREE_UNKNOWN_VIDEO_REVISION = (
    "live-action medium close shot of the same fictional woman with short black hair "
    "and beige cardigan folding the old letter closed, placing both hands on the "
    "wooden table, then looking toward the dawn window, static camera, no push-in"
)


def sanitized(value):
    if isinstance(value, dict):
        return {
            key: sanitized(item)
            for key, item in value.items()
            if key.lower() not in SECRET_KEYS
            and re.sub(r"[^a-z]", "", key.lower())
            not in {
                "xapikey",
                "xcsrftoken",
                "passwordhash",
                "secretkey",
                "privatekey",
                "accesskey",
            }
        }
    if isinstance(value, list):
        return [sanitized(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{12,}", "[REDACTED]", value)

        def clean(match):
            parsed = urlsplit(match.group())
            host = parsed.hostname or ""
            try:
                if parsed.port:
                    host += f":{parsed.port}"
            except ValueError:
                pass
            return urlunsplit((parsed.scheme, host, parsed.path, "", ""))

        return re.sub(r"https?://[^\s\"<>]+", clean, value)
    return value


def apply_editing_operations(
    timeline: dict,
    operations: list[dict],
    *,
    selected_indices: list[int] | None = None,
) -> dict:
    """Apply the same bounded typed Editing operations as the browser draft.

    The returned value is still only a draft.  The caller must explicitly PATCH
    the EditSession Timeline before it becomes a saved canonical version.
    """
    draft = json.loads(json.dumps(timeline))
    clips = draft.get("clips")
    if not isinstance(clips, list):
        raise RuntimeError("Editing suggestion target Timeline has no clips")
    indices = selected_indices if selected_indices is not None else list(range(len(operations)))
    if not indices:
        raise RuntimeError("Editing suggestion adoption must select at least one operation")

    for index in indices:
        if index < 0 or index >= len(operations):
            raise RuntimeError("Editing suggestion operation index is invalid")
        operation = operations[index]
        kind = operation.get("operation")
        if kind == "reorder_clips":
            ordered_ids = operation.get("clip_ids")
            if not isinstance(ordered_ids, list):
                raise RuntimeError("Editing reorder operation has no clip_ids")
            by_id = {str(clip.get("id")): clip for clip in clips if clip.get("id") is not None}
            reordered = [by_id.get(str(clip_id)) for clip_id in ordered_ids]
            if any(clip is None for clip in reordered) or len(reordered) != len(clips):
                raise RuntimeError("Editing reorder operation does not match the saved Timeline")
            clips = [{**clip, "order": order} for order, clip in enumerate(reordered, start=1)]
            draft["clips"] = clips
            continue
        if kind not in {"set_clip_duration", "set_clip_subtitle"}:
            raise RuntimeError(f"Unsupported Editing suggestion operation: {kind}")
        target = str(operation.get("clip_id") or "")
        matched = False
        for clip in clips:
            if target not in {str(clip.get("id") or ""), str(clip.get("shot_id") or "")}:
                continue
            matched = True
            if kind == "set_clip_duration":
                clip["duration_seconds"] = operation["duration_seconds"]
            else:
                clip["subtitle"] = operation["subtitle"]
        if not matched:
            raise RuntimeError("Editing suggestion target is not in the saved Timeline")
    return draft


class Acceptance:
    def __init__(self, client, state_path: Path, *, real: bool, evidence_dir: Path | None = None):
        self.client = client
        self.path = state_path
        self.real = real
        self.evidence_dir = evidence_dir
        self.state = (
            json.loads(state_path.read_text())
            if state_path.exists()
            else {
                "schema_version": 1,
                "run_key": uuid4().hex[:12],
                "steps": {},
                "projects": {},
                "assertions": {},
                "complete": False,
            }
        )
        self.headers = {}
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".pending")
        temp.write_text(
            json.dumps(sanitized(self.state), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temp.replace(self.path)

    def read(self, path):
        response = self.client.get(path, headers=self.headers)
        if response.is_error:
            raise RuntimeError(f"Read {path.split('?')[0]} failed: HTTP {response.status_code}")
        return response.json()

    def once(self, name, method, path, payload, *, paid=False, command_key=None):
        previous = self.state["steps"].get(name)
        if previous is not None:
            if previous["status"] == "succeeded":
                return previous["response"]
            raise RuntimeError(
                f"Step {name} has {previous['status']} outcome; "
                "inspect its persisted receipt, do not replay"
            )
        if paid and not self.real:
            raise RuntimeError("--real is required by this Provider acceptance phase")
        body = payload() if callable(payload) else payload
        entry = {
            "method": method,
            "path": path,
            "request": sanitized(body),
            "request_hash": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
            "paid_command": paid,
            "command_key": command_key,
            "status": "started",
        }
        self.state["steps"][name] = entry
        self.save()  # durable before I/O, including any potentially billable request
        try:
            response = self.client.request(
                method,
                path,
                json=body,
                headers={
                    **self.headers,
                    **({"Idempotency-Key": command_key} if command_key else {}),
                },
            )
        except Exception as error:
            entry.update(status="unknown", error_class=type(error).__name__)
            self.save()
            raise RuntimeError(f"Unknown outcome for {name}; no automatic replay") from None
        try:
            result = response.json()
        except ValueError:
            result = {"error": "non-JSON response"}
        entry.update(
            status="failed" if response.is_error else "succeeded",
            http_status=response.status_code,
            response=sanitized(result),
        )
        self.save()
        if response.is_error:
            code = result.get("details", {}).get("code", result.get("code", "unknown"))
            raise RuntimeError(f"Step {name} failed: HTTP {response.status_code}, {code}")
        return result

    def expect_error_once(self, name, method, path, payload, *, expected_statuses):
        """Persist and execute one fail-closed HTTP probe without replaying unknown I/O."""
        previous = self.state["steps"].get(name)
        if previous is not None:
            if previous["status"] == "succeeded":
                return previous["response"]
            raise RuntimeError(
                f"Step {name} has {previous['status']} outcome; inspect it, do not replay"
            )
        body = payload() if callable(payload) else payload
        entry = {
            "method": method,
            "path": path,
            "request": sanitized(body),
            "request_hash": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
            "paid_command": False,
            "status": "started",
        }
        self.state["steps"][name] = entry
        self.save()
        try:
            response = self.client.request(method, path, json=body, headers=self.headers)
        except Exception as error:
            entry.update(status="unknown", error_class=type(error).__name__)
            self.save()
            raise RuntimeError(f"Unknown outcome for {name}; no automatic replay") from None
        try:
            result = response.json()
        except ValueError:
            result = {"error": "non-JSON response"}
        accepted = response.status_code in set(expected_statuses)
        entry.update(
            status="succeeded" if accepted else "failed",
            http_status=response.status_code,
            response=sanitized(result),
        )
        self.save()
        if not accepted:
            raise RuntimeError(
                f"Negative probe {name} returned HTTP {response.status_code}; "
                f"expected {sorted(expected_statuses)}"
            )
        return result

    @staticmethod
    def remote_media_operations(snapshot):
        return [
            operation
            for operation in snapshot.get("provider_operations", [])
            if operation.get("actual_provider") not in {"local", "local_ffmpeg", "local_tts"}
            and operation.get("operation_kind")
            in {"image.generate", "keyframe.generate", "video.generate"}
        ]

    def login(self):
        response = self.client.post(
            "/auth/login",
            json={
                "email": os.environ.get("DRAMAFORGE_PROOF_EMAIL", "professional-proof@example.com"),
                "password": os.environ.get(
                    "DRAMAFORGE_PROOF_PASSWORD", "professional-proof-password-2026"
                ),
            },
        )
        if response.is_error:
            raise RuntimeError(f"Acceptance login failed: HTTP {response.status_code}")
        self.headers = {
            "X-Workspace-Id": WORKSPACE,
            "X-CSRF-Token": self.read("/auth/csrf")["csrf_token"],
        }

    def shots(self, project):
        rows = self.read(f"/projects/{project}/shots")
        return sorted(rows, key=lambda row: (row["sort_order"], row["id"]))

    def shot(self, project, shot_id):
        basic = next(row for row in self.shots(project) if row["id"] == shot_id)
        workbench = self.read(f"/projects/{project}/shots/{shot_id}/workbench")
        detailed = workbench.get("shot") if isinstance(workbench, dict) else None
        return {**basic, **(detailed if isinstance(detailed, dict) else {})}

    def preflight(self):
        models = self.read("/models")
        required = {
            "litellm/script-quality",
            "agnes/agnes-image-2.1-flash",
            "agnes/agnes-video-v2.0",
        }
        configured = {row["id"] for row in models if row.get("configured")}
        if not required <= configured:
            raise RuntimeError("The explicitly selected acceptance models are not configured")
        self.state["models"] = [
            {k: r.get(k) for k in ("id", "configured", "provider_id")} for r in models
        ]
        self.state["minimax_special_case"] = "NOT_VERIFIED_NO_CONFIGURED_BINDING"
        profiles = self.read(f"/workspaces/{WORKSPACE}/model-profiles")
        if not any(row.get("is_default") for row in profiles):
            self.once(
                "workspace_profile",
                "POST",
                f"/workspaces/{WORKSPACE}/model-profiles",
                {
                    "name": "R7 explicit text configuration",
                    "is_default": True,
                    "bindings": {
                        slot: {"model_id": "litellm/script-quality", "enabled": True}
                        for slot in ("planning.brief", "planning.script", "planning.storyboard")
                    },
                },
            )
        # Built-in template registry is code-owned; the creation API validates
        # this exact registered key/version (there is no template-list route).
        template = {"key": "single_monologue_v1", "version": "1"}
        connections = self.read(f"/workspaces/{WORKSPACE}/provider-connections")
        agnes = next(
            row for row in connections if row.get("provider_type") == "agnes" and row.get("enabled")
        )
        bindings = self.read(
            f"/workspaces/{WORKSPACE}/provider-connections/{agnes['id']}/model-bindings"
        )
        self.state["bindings"] = {
            purpose: next(
                row
                for row in bindings
                if row.get("purpose") == purpose
                and row.get("enabled")
                and row.get("account_verified")
            )
            for purpose in ("keyframe", "video")
        }
        existing = self.read(f"/workspaces/{WORKSPACE}/projects")
        for label, start, mode in (
            ("template_auto", "TEMPLATE", "AUTO"),
            ("free_assist", "FREE", "ASSIST"),
        ):
            name = f"R7 {label} {self.state['run_key']}"
            project = next((row for row in existing if row["name"] == name), None)
            if project is None:
                project = self.once(
                    f"project:{label}",
                    "POST",
                    "/projects",
                    {
                        "workspace_id": WORKSPACE,
                        "name": name,
                        "aspect_ratio": "9:16",
                        "start_type": start,
                        "director_autonomy": mode,
                        **(
                            {
                                "template_key": template["key"],
                                "template_version": str(template["version"]),
                            }
                            if start == "TEMPLATE"
                            else {}
                        ),
                    },
                )
            if project.get("aspect_ratio") != "9:16":
                raise RuntimeError(
                    "Configured acceptance bindings require portrait; "
                    "preserve this preflight and start a separate portrait run"
                )
            self.state["projects"][label] = project
            self.save()
            for purpose in ("keyframe", "video"):
                self.once(
                    f"binding:{label}:{purpose}",
                    "PUT",
                    f"/projects/{project['id']}/provider-bindings/{purpose}",
                    {"model_binding_id": self.state["bindings"][purpose]["id"]},
                )
        self.state["assertions"]["preflight"] = "PASS"
        self.save()

    def story(self):
        template = self.state["projects"]["template_auto"]["id"]
        generated = self.once(
            "template:story",
            "POST",
            f"/projects/{template}/story/proposals/generate",
            {
                "request_key": f"r7:{self.state['run_key']}:story",
                "brief": BRIEF,
                "filename": "last-bus.md",
            },
            paid=True,
        )
        operations = generated["proposal"]["operations"]
        shot_ops = [op for op in operations if op["command"] == "story.upsert_shot"]
        if len(shot_ops) < 4:
            raise RuntimeError(
                "Generated story needs review: insufficient shots for trimmed 15–30s acceptance"
            )
        rejected = shot_ops[-1]["id"]
        applied = self.once(
            "template:story-apply",
            "POST",
            f"/projects/{template}/story/proposals/{generated['proposal']['id']}/apply",
            {
                "decisions": [
                    {
                        "item_id": op["id"],
                        "decision": "rejected" if op["id"] == rejected else "accepted",
                    }
                    for op in operations
                ]
            },
        )
        if applied.get("failed"):
            raise RuntimeError("Story apply has failed items; no media dispatch permitted")
        free = self.state["projects"]["free_assist"]["id"]
        self.once(
            "free:import",
            "POST",
            f"/projects/{free}/scripts/import",
            {"filename": "letter-before-dawn.md", "text": FREE_SCRIPT},
        )
        for label, project in (("template", template), ("free", free)):
            shot = self.shots(project)[0]
            sid = shot["id"]
            suggestion = self.once(
                f"{label}:shot-text",
                "POST",
                f"/projects/{project}/director/shots/{sid}/suggestion",
                lambda shot=shot, sid=sid, label=label: {
                    "scene_id": shot["scene_id"],
                    "shot_id": sid,
                    "expected_shot_version": shot["version"],
                    "request_key": f"r7:{self.state['run_key']}:{label}:shot",
                    "user_instruction": (
                        "保持静止摄影机，不要推镜；把人物表情调整得更克制，保留米色服装。"
                    ),
                },
                paid=True,
            )
            turn_id = suggestion["director_evidence"]["turn_id"]
            self.once(
                f"{label}:accept-shot",
                "POST",
                f"/projects/{project}/director/turns/{turn_id}/decision",
                lambda project=project, turn_id=turn_id: {
                    "expected_revision": self.read(f"/projects/{project}/director/turns/{turn_id}")[
                        "revision"
                    ],
                    "decision": "accept",
                    "accepted_operation_indices": [0],
                },
            )
            self.once(
                f"{label}:save-shot",
                "PATCH",
                f"/projects/{project}/shots/{sid}/design",
                lambda project=project, sid=sid, suggestion=suggestion: {
                    "expected_version": self.shot(project, sid)["version"],
                    "image_prompt": suggestion["suggested_image_prompt"]
                    + " Natural soft light, live action.",
                    "video_prompt": suggestion["suggested_video_prompt"]
                    + " User constraint: locked-off camera, no dolly push-in.",
                    "director_state": suggestion["suggested_director_state"],
                },
            )
        self.state["assertions"]["story_and_user_decisions"] = "PASS"
        self.save()

    def replace_template(self):
        """Abandon an unreconciled Template project without replaying its writes."""
        old_project = self.state["projects"]["template_auto"]
        unresolved = [
            item
            for item in self.state.get("unreconciled_media_submissions", [])
            if item.get("project_id") == old_project["id"]
        ]
        if not unresolved or any(item.get("replay_allowed") is not False for item in unresolved):
            raise RuntimeError("Template replacement requires preserved non-replayable submissions")
        old_snapshot = self.read(f"/projects/{old_project['id']}/snapshot")
        if any(
            operation.get("status") == "succeeded"
            for operation in self.remote_media_operations(old_snapshot)
        ):
            raise RuntimeError("Do not replace a Template project with successful remote media")
        owned_step_names = [
            name
            for name in self.state["steps"]
            if name in {"project:template_auto"}
            or name.startswith("binding:template_auto:")
            or name.startswith("template:")
            or name.startswith("template_auto:")
        ]
        self.state.setdefault("abandoned_projects", []).append(
            {
                "project": old_project,
                "reason": "unreconciled_provider_submissions_no_remote_identity",
                "replay_allowed": False,
                "unreconciled_submissions": unresolved,
                "steps": {name: self.state["steps"][name] for name in owned_step_names},
            }
        )
        for name in owned_step_names:
            del self.state["steps"][name]
        self.state["unreconciled_media_submissions"] = [
            item
            for item in self.state.get("unreconciled_media_submissions", [])
            if item.get("project_id") != old_project["id"]
        ]
        replacement = self.once(
            "replacement:template-project",
            "POST",
            "/projects",
            {
                "workspace_id": WORKSPACE,
                "name": f"R7 replacement template_auto {self.state['run_key']}",
                "aspect_ratio": "9:16",
                "start_type": "TEMPLATE",
                "director_autonomy": "AUTO",
                "template_key": "single_monologue_v1",
                "template_version": "1",
            },
        )
        for purpose in ("keyframe", "video"):
            self.once(
                f"replacement:template-binding:{purpose}",
                "PUT",
                f"/projects/{replacement['id']}/provider-bindings/{purpose}",
                {"model_binding_id": self.state["bindings"][purpose]["id"]},
            )
        self.state["projects"]["template_auto"] = replacement
        self.state["assertions"].pop("story_and_user_decisions", None)
        self.state["assertions"].pop("template_auto:formal_media", None)
        self.state.get("formal_shot_ids", {}).pop("template_auto", None)
        self.state.pop("failed_run", None)
        self.save()

    def wait_run(self, project, run_id):
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            snapshot = self.read(f"/projects/{project}/snapshot")
            run = next((row for row in snapshot["node_runs"] if row["id"] == run_id), None)
            if run and run["status"] in {"completed", "cached", "completed_after_cancel"}:
                return run
            if run and run["status"] in {"failed", "cancelled"}:
                self.state["failed_run"] = sanitized(run)
                self.save()
                raise RuntimeError(f"Persisted run failed: {run.get('error_code')}; no resubmit")
            time.sleep(4)
        raise RuntimeError(f"Run {run_id} still pending; resume by reading, not dispatching")

    def media(self):
        for label, project in self.state["projects"].items():
            pid = project["id"]
            for original in self.shots(pid):
                sid = original["id"]
                skip_shot = False
                for stage, formal, purpose in (
                    ("image_keyframe", "keyframe", "keyframe"),
                    ("video", "video", "video"),
                ):
                    prefix = f"{label}:{sid}:{stage}"

                    def preview_body(pid=pid, sid=sid, stage=stage, purpose=purpose):
                        shot = self.shot(pid, sid)
                        return {
                            "stage": stage,
                            "prompt": shot.get(
                                "image_prompt" if purpose == "keyframe" else "video_prompt"
                            )
                            or shot["visual_description"],
                            "expected_shot_version": shot["version"],
                            "mode_id": "text_to_image" if purpose == "keyframe" else "first_frame",
                            "requested_binding_id": self.state["bindings"][purpose]["id"],
                            "references": [],
                            "semantic_intent": {},
                            "accept_approximations": False,
                        }

                    preview = self.once(
                        prefix + ":preview",
                        "POST",
                        f"/projects/{pid}/shots/{sid}/execution-plan",
                        preview_body,
                    )
                    if any(
                        gap["severity"] == "fatal" for gap in preview["plan"]["capability_gaps"]
                    ):
                        raise RuntimeError("Unsupported preview; no silent adaptation")
                    body = self.state["steps"][prefix + ":preview"]["request"]
                    key = f"r7:{self.state['run_key']}:{sid}:{stage}"
                    receipt = self.once(
                        prefix + ":dispatch",
                        "POST",
                        f"/projects/{pid}/shots/{sid}/executions",
                        {
                            **body,
                            "plan_fingerprint": preview["plan_fingerprint"],
                            "accepted_approximations": [],
                        },
                        paid=True,
                        command_key=key,
                    )
                    try:
                        run = self.wait_run(pid, receipt["node_run_id"])
                    except RuntimeError:
                        failed = self.state.get("failed_run")
                        if (
                            isinstance(failed, dict)
                            and failed.get("id") == receipt["node_run_id"]
                            and failed.get("error_code") == "PROVIDER_SUBMISSION_UNKNOWN"
                        ):
                            unresolved = self.state.setdefault("unreconciled_media_submissions", [])
                            if not any(
                                item.get("node_run_id") == failed["id"] for item in unresolved
                            ):
                                unresolved.append(
                                    {
                                        "project_id": pid,
                                        "shot_id": sid,
                                        "stage": stage,
                                        "node_run_id": failed["id"],
                                        "status": "unknown_submission",
                                        "cost_status": "unknown",
                                        "replay_allowed": False,
                                    }
                                )
                                self.save()
                            skip_shot = True
                            break
                        raise
                    self.once(
                        prefix + ":formal",
                        "POST",
                        f"/projects/{pid}/shots/{sid}/formal-{formal}",
                        lambda run=run, pid=pid, sid=sid: {
                            "artifact_id": run["result_artifact_id"],
                            "expected_shot_version": self.shot(pid, sid)["version"],
                        },
                    )
                if skip_shot:
                    continue
            formal_shots = [
                shot
                for basic in self.shots(pid)
                if (shot := self.shot(pid, basic["id"])).get("formal_keyframe_artifact_id")
                and shot.get("formal_video_artifact_id")
            ]
            if len(formal_shots) < 4:
                raise RuntimeError(f"{label} has fewer than four complete Formal media shots")
            self.state.setdefault("formal_shot_ids", {})[label] = [
                shot["id"] for shot in formal_shots
            ]
            self.state["assertions"][label + ":formal_media"] = "PASS"
            self.save()

    def revise_unknown_free(self):
        """Replace one indeterminate Free-path video intent without replaying it.

        A transport timeout after submission is permanently retained as unknown.
        This phase records an explicit user design revision with a materially new
        prompt and a distinct idempotency key, then generates only that revision.
        """
        project_id = self.state["projects"]["free_assist"]["id"]
        unresolved = [
            item
            for item in self.state.get("unreconciled_media_submissions", [])
            if item.get("project_id") == project_id
        ]
        if len(unresolved) != 1 or unresolved[0].get("stage") != "video":
            raise RuntimeError("Expected exactly one unreconciled Free video submission")
        unknown = unresolved[0]
        if unknown.get("replay_allowed") is not False or unknown.get("cost_status") != "unknown":
            raise RuntimeError("Unknown submission must remain non-replayable with unknown cost")
        shot_id = unknown["shot_id"]
        shot = self.shot(project_id, shot_id)
        if shot.get("formal_video_artifact_id"):
            raise RuntimeError("Unknown-submission shot already has a Formal video")

        original_prefix = f"free_assist:{shot_id}:video"
        original_dispatch = self.state["steps"].get(original_prefix + ":dispatch")
        if not isinstance(original_dispatch, dict):
            raise RuntimeError("Unknown submission is missing its durable original receipt")
        original_prompt = original_dispatch.get("request", {}).get("prompt")
        if not original_prompt or original_prompt == FREE_UNKNOWN_VIDEO_REVISION:
            raise RuntimeError(
                "Replacement intent must be materially distinct from the unknown one"
            )

        revised = self.once(
            f"free-revision:{shot_id}:design",
            "PATCH",
            f"/projects/{project_id}/shots/{shot_id}/design",
            {
                "expected_version": shot["version"],
                "image_prompt": shot.get("image_prompt") or shot["visual_description"],
                "video_prompt": FREE_UNKNOWN_VIDEO_REVISION,
            },
        )
        preview = self.once(
            f"free-revision:{shot_id}:video:preview",
            "POST",
            f"/projects/{project_id}/shots/{shot_id}/execution-plan",
            {
                "stage": "video",
                "prompt": FREE_UNKNOWN_VIDEO_REVISION,
                "expected_shot_version": revised["version"],
                "mode_id": "first_frame",
                "requested_binding_id": self.state["bindings"]["video"]["id"],
                "references": [],
                "semantic_intent": {},
                "accept_approximations": False,
            },
        )
        if any(gap["severity"] == "fatal" for gap in preview["plan"]["capability_gaps"]):
            raise RuntimeError("Revised Free video preview is unsupported")
        preview_request = self.state["steps"][
            f"free-revision:{shot_id}:video:preview"
        ]["request"]
        replacement_key = f"r7:{self.state['run_key']}:{shot_id}:video-revision-1"
        receipt = self.once(
            f"free-revision:{shot_id}:video:dispatch",
            "POST",
            f"/projects/{project_id}/shots/{shot_id}/executions",
            {
                **preview_request,
                "plan_fingerprint": preview["plan_fingerprint"],
                "accepted_approximations": [],
            },
            paid=True,
            command_key=replacement_key,
        )
        run = self.wait_run(project_id, receipt["node_run_id"])
        formal = self.once(
            f"free-revision:{shot_id}:video:formal",
            "POST",
            f"/projects/{project_id}/shots/{shot_id}/formal-video",
            lambda: {
                "artifact_id": run["result_artifact_id"],
                "expected_shot_version": self.shot(project_id, shot_id)["version"],
            },
        )
        replacement_dispatch = self.state["steps"][
            f"free-revision:{shot_id}:video:dispatch"
        ]
        if replacement_dispatch["request_hash"] == original_dispatch["request_hash"]:
            raise RuntimeError("Revised request unexpectedly matches the unknown submission")
        self.state["unknown_submission_replacement"] = {
            "project_id": project_id,
            "shot_id": shot_id,
            "original_node_run_id": unknown["node_run_id"],
            "original_request_hash": original_dispatch["request_hash"],
            "original_cost_status": "unknown",
            "original_replay_allowed": False,
            "replacement_node_run_id": receipt["node_run_id"],
            "replacement_request_hash": replacement_dispatch["request_hash"],
            "replacement_command_key_hash": hashlib.sha256(
                replacement_key.encode()
            ).hexdigest(),
            "formal_video_artifact_id": formal["formal_video_artifact_id"],
        }
        self.state.pop("failed_run", None)
        self.state["assertions"]["unknown_submission_not_replayed"] = "PASS"
        self.save()

    def editing(self):
        for label, project in self.state["projects"].items():
            if self.state.get(label + ":final_job"):
                continue
            pid = project["id"]
            edit = self.once(
                label + ":edit", "POST", f"/projects/{pid}/edit-sessions", {"name": "R7 saved cut"}
            )
            eid = edit["id"]
            advice = None
            if label == "free_assist":
                advice = self.once(
                    label + ":editing-text",
                    "POST",
                    f"/projects/{pid}/edit-sessions/{eid}/director-suggestion",
                    {
                        "expected_session_version": edit["version"],
                        "user_instruction": (
                            "仅调整字幕表达，使第一句更简洁；不要改变音视频来源，不要重生成媒体。"
                        ),
                        "request_key": f"r7:{self.state['run_key']}:editing",
                    },
                    paid=True,
                )
                self.state["editing_advice_review_required"] = advice
                self.save()

            # Save explicit timeline edits. Advice application is a separate
            # auditable user step; never silently translate an arbitrary plan.
            def edited(edit=edit, label=label, advice=advice):
                timeline = json.loads(json.dumps(edit["timeline"]))
                clips = list(reversed(timeline["clips"]))
                for index, clip in enumerate(clips):
                    clip.update(
                        order=index + 1,
                        source_in_seconds=0.1,
                        duration_seconds=4.8,
                        subtitle=f"{label} · 选择向前 {index + 1}",
                        transition={"kind": "cut"},
                    )
                timeline["clips"] = clips
                if advice is not None:
                    operations = advice["suggestion"]["plan"]["operations"]
                    timeline = apply_editing_operations(timeline, operations)
                    timeline.setdefault("metadata", {})["director_suggestion_applied"] = advice[
                        "suggestion"
                    ]["base_session_version"]
                return {"timeline": timeline}

            saved = self.once(
                label + ":timeline-save",
                "PATCH",
                f"/projects/{pid}/edit-sessions/{eid}/timeline",
                edited,
            )
            if advice is not None:
                saved_timeline = saved["timeline"]
                expected = apply_editing_operations(
                    {
                        **edit["timeline"],
                        "clips": [
                            {
                                **clip,
                                "order": index + 1,
                                "source_in_seconds": 0.1,
                                "duration_seconds": 4.8,
                                "subtitle": f"{label} · 选择向前 {index + 1}",
                                "transition": {"kind": "cut"},
                            }
                            for index, clip in enumerate(reversed(edit["timeline"]["clips"]))
                        ],
                    },
                    advice["suggestion"]["plan"]["operations"],
                )
                if saved_timeline["clips"] != expected["clips"]:
                    raise RuntimeError("Saved Timeline does not contain the adopted Editing advice")
                if saved_timeline.get("metadata", {}).get("director_suggestion_applied") != advice[
                    "suggestion"
                ]["base_session_version"]:
                    raise RuntimeError("Saved Timeline is missing Editing adoption provenance")
                self.state["assertions"]["editing_advice_apply"] = "PASS"
                self.save()
            prepared = self.once(
                label + ":tail",
                "POST",
                f"/projects/{pid}/final-film/prepare",
                {
                    "edit_session_id": eid,
                    "expected_timeline_version": saved["version"],
                    "mode": "prepare",
                },
            )
            for run_id in prepared["node_run_ids"]:
                self.wait_run(pid, run_id)
            job = self.once(
                label + ":render",
                "POST",
                f"/projects/{pid}/final-film/render",
                {
                    "edit_session_id": eid,
                    "expected_timeline_version": saved["version"],
                    "name": "R7 final film",
                },
                command_key=f"r7:{self.state['run_key']}:{label}:film",
            )
            self.wait_run(pid, job["node_run_id"])
            self.state[label + ":final_job"] = self.read(
                f"/projects/{pid}/final-film/runs/{job['node_run_id']}"
            )
            self.save()

    def recover_local_editing(self):
        failed = self.state.get("failed_run")
        if not isinstance(failed, dict):
            raise RuntimeError("Local Editing recovery requires a persisted failed NodeRun")
        if (
            failed.get("node_key") != "voice"
            or failed.get("error_code") != "WORKER_ERROR"
            or "uq_artifacts_project_hash_type" not in str(failed.get("error_summary") or "")
        ):
            raise RuntimeError("Persisted failure is not the known concurrent Artifact race")
        input_snapshot = failed.get("input_snapshot", {})
        project_id = str(input_snapshot.get("project_id") or "")
        label = next(
            (
                name
                for name, project in self.state["projects"].items()
                if project["id"] == project_id
            ),
            None,
        )
        if label is None and input_snapshot.get("shot_id"):
            failed_shot_id = str(input_snapshot["shot_id"])
            label = next(
                (
                    name
                    for name, project in self.state["projects"].items()
                    if any(
                        shot["id"] == failed_shot_id for shot in self.shots(project["id"])
                    )
                ),
                None,
            )
            if label is not None:
                project_id = self.state["projects"][label]["id"]
        if label is None:
            raise RuntimeError("Failed local Editing run is not owned by an acceptance project")
        saved_step = self.state["steps"].get(label + ":timeline-save")
        if not isinstance(saved_step, dict) or saved_step.get("status") != "succeeded":
            raise RuntimeError("Local Editing recovery requires the prior saved Timeline")
        old_snapshot = self.read(f"/projects/{project_id}/snapshot")
        remote_before = len(self.remote_media_operations(old_snapshot))
        prefix = f"local-recovery:{label}"
        edit = self.once(
            prefix + ":edit",
            "POST",
            f"/projects/{project_id}/edit-sessions",
            {"name": "R7 recovered saved cut"},
        )
        saved = self.once(
            prefix + ":timeline-save",
            "PATCH",
            f"/projects/{project_id}/edit-sessions/{edit['id']}/timeline",
            {"timeline": saved_step["response"]["timeline"]},
        )
        prepared = self.once(
            prefix + ":tail",
            "POST",
            f"/projects/{project_id}/final-film/prepare",
            {
                "edit_session_id": edit["id"],
                "expected_timeline_version": saved["version"],
                "mode": "prepare",
            },
        )
        for run_id in prepared["node_run_ids"]:
            self.wait_run(project_id, run_id)
        job = self.once(
            prefix + ":render",
            "POST",
            f"/projects/{project_id}/final-film/render",
            {
                "edit_session_id": edit["id"],
                "expected_timeline_version": saved["version"],
                "name": "R7 recovered final film",
            },
            command_key=f"r7:{self.state['run_key']}:{label}:film-recovery-1",
        )
        self.wait_run(project_id, job["node_run_id"])
        final_job = self.read(f"/projects/{project_id}/final-film/runs/{job['node_run_id']}")
        remote_after = len(
            self.remote_media_operations(self.read(f"/projects/{project_id}/snapshot"))
        )
        if remote_after != remote_before:
            raise RuntimeError("Local Editing recovery unexpectedly generated remote media")
        self.state["local_artifact_race_failure"] = sanitized(failed)
        self.state["local_artifact_race_recovery"] = {
            "project_id": project_id,
            "failed_node_run_id": failed["id"],
            "replacement_edit_session_id": edit["id"],
            "replacement_render_run_id": job["node_run_id"],
            "remote_media_operation_count_before": remote_before,
            "remote_media_operation_count_after": remote_after,
        }
        self.state[label + ":final_job"] = final_job
        self.state["assertions"]["local_artifact_race_recovery"] = "PASS"
        self.state.pop("failed_run", None)
        self.save()

    def review_submit(self):
        project = self.state["projects"]["template_auto"]
        project_id = project["id"]
        shot_id = self.shots(project_id)[0]["id"]
        shot = self.shot(project_id, shot_id)
        if not shot.get("formal_video_artifact_id"):
            raise RuntimeError("Review acceptance requires a Formal video")
        before = self.read(f"/projects/{project_id}/snapshot")
        annotation = self.once(
            "review:annotation",
            "POST",
            f"/projects/{project_id}/shots/{shot_id}/annotations",
            {
                "artifact_id": shot["formal_video_artifact_id"],
                "target_kind": "video_time",
                "time_start": 1.0,
                "time_end": 2.0,
                "note": "人物停顿略短；保留原正式视频，先生成一个修复候选再决定。",
                "severity": "warning",
            },
        )
        plan = self.once(
            "review:repair-plan",
            "POST",
            f"/projects/{project_id}/shots/{shot_id}/repair-plan",
            {},
        )
        if plan.get("annotation_count", 0) < 1 or "rerun_video" not in plan.get(
            "repair_options", []
        ):
            raise RuntimeError("Review annotation did not produce the expected repair plan")
        repair = self.once(
            "review:repair-submit",
            "POST",
            f"/projects/{project_id}/shots/{shot_id}/repair",
            {
                "repair_option": "rerun_video",
                "idempotency_key": f"r7:{self.state['run_key']}:repair-video",
            },
            paid=True,
        )
        self.state["review_repair"] = {
            "project_id": project_id,
            "shot_id": shot_id,
            "annotation_id": annotation["id"],
            "repair_plan": sanitized(plan),
            "repair_run_id": repair["node_run_id"],
            "formal_video_before": shot["formal_video_artifact_id"],
            "remote_media_operation_count_before": len(self.remote_media_operations(before)),
        }
        self.save()

    def review_collect(self):
        evidence = self.state.get("review_repair")
        if not isinstance(evidence, dict):
            raise RuntimeError("Run review-submit before review-collect")
        project_id = evidence["project_id"]
        run = self.wait_run(project_id, evidence["repair_run_id"])
        after = self.read(f"/projects/{project_id}/snapshot")
        shot = self.shot(project_id, evidence["shot_id"])
        operations = [
            operation
            for operation in after.get("provider_operations", [])
            if operation.get("node_run_id") == evidence["repair_run_id"]
        ]
        if len(operations) != 1 or operations[0].get("status") != "succeeded":
            raise RuntimeError("Repair must have exactly one successful Provider operation")
        if shot.get("formal_video_artifact_id") != evidence["formal_video_before"]:
            raise RuntimeError("Repair candidate changed Formal video before explicit confirmation")
        evidence.update(
            repair_run=sanitized(run),
            repair_operation=sanitized(operations[0]),
            formal_video_after=shot.get("formal_video_artifact_id"),
            remote_media_operation_count_after=len(self.remote_media_operations(after)),
        )
        self.state["assertions"]["review_repair"] = "PASS"
        self.save()

    def regressions(self):
        template_id = self.state["projects"]["template_auto"]["id"]
        free_id = self.state["projects"]["free_assist"]["id"]
        template_basic = self.shots(template_id)[0]
        free_basic = self.shots(free_id)[0]
        template_shot = self.shot(template_id, template_basic["id"])
        free_shot = self.shot(free_id, free_basic["id"])

        remote_before_negative = {
            project_id: len(
                self.remote_media_operations(self.read(f"/projects/{project_id}/snapshot"))
            )
            for project_id in (template_id, free_id)
        }
        self.expect_error_once(
            "negative:cross-project-formal",
            "POST",
            f"/projects/{template_id}/shots/{template_shot['id']}/formal-keyframe",
            {
                "artifact_id": free_shot["formal_keyframe_artifact_id"],
                "expected_shot_version": template_shot["version"],
            },
            expected_statuses={404, 422},
        )
        self.expect_error_once(
            "negative:stale-shot-save",
            "PATCH",
            f"/projects/{template_id}/shots/{template_shot['id']}/design",
            {
                "expected_version": 1,
                "image_prompt": template_shot.get("image_prompt")
                or template_shot["visual_description"],
                "video_prompt": template_shot.get("video_prompt")
                or template_shot["visual_description"],
            },
            expected_statuses={409},
        )
        csrf = self.headers.pop("X-CSRF-Token")
        try:
            self.expect_error_once(
                "negative:csrf",
                "POST",
                f"/projects/{template_id}/shots/{template_shot['id']}/annotations",
                {"target_kind": "shot", "note": "must not persist without CSRF"},
                expected_statuses={403},
            )
        finally:
            self.headers["X-CSRF-Token"] = csrf
        self.expect_error_once(
            "negative:binding-mismatch",
            "POST",
            f"/projects/{template_id}/shots/{template_shot['id']}/execution-plan",
            {
                "stage": "image_keyframe",
                "prompt": template_shot.get("image_prompt") or template_shot["visual_description"],
                "expected_shot_version": template_shot["version"],
                "mode_id": "text_to_image",
                "requested_binding_id": self.state["bindings"]["video"]["id"],
                "references": [],
                "semantic_intent": {},
                "accept_approximations": False,
            },
            expected_statuses={409, 422},
        )
        remote_after_negative = {
            project_id: len(
                self.remote_media_operations(self.read(f"/projects/{project_id}/snapshot"))
            )
            for project_id in (template_id, free_id)
        }
        if remote_after_negative != remote_before_negative:
            raise RuntimeError("Negative probes created a remote media Provider operation")
        self.state["assertions"]["negative_boundaries"] = "PASS"

        manual = self.once(
            "manual:project",
            "POST",
            "/projects",
            {
                "workspace_id": WORKSPACE,
                "name": f"R7 manual regression {self.state['run_key']}",
                "aspect_ratio": "9:16",
                "start_type": "FREE",
                "director_autonomy": "MANUAL",
            },
        )
        imported = self.once(
            "manual:import",
            "POST",
            f"/projects/{manual['id']}/scripts/import",
            {"filename": "manual-regression.md", "text": FREE_SCRIPT},
        )
        manual_snapshot = self.read(f"/projects/{manual['id']}/snapshot")
        manual_turns = self.read(f"/projects/{manual['id']}/director/turns?limit=100")
        if (
            manual_snapshot.get("node_runs")
            or manual_snapshot.get("provider_operations")
            or manual_turns
        ):
            raise RuntimeError("MANUAL create/import unexpectedly started Director or Runtime work")
        switched = self.once(
            "manual:switch-assist",
            "PATCH",
            f"/projects/{manual['id']}/creative-profile",
            {
                "expected_version": manual["creative_profile"]["version"],
                "director_autonomy": "ASSIST",
            },
        )
        final_manual = self.once(
            "manual:switch-back",
            "PATCH",
            f"/projects/{manual['id']}/creative-profile",
            {
                "expected_version": switched["version"],
                "director_autonomy": "MANUAL",
            },
        )
        final_snapshot = self.read(f"/projects/{manual['id']}/snapshot")
        if (
            final_manual["project_id"] != manual["id"]
            or final_snapshot.get("node_runs")
            or final_snapshot.get("provider_operations")
        ):
            raise RuntimeError("Autonomy switching changed Project/Runtime identity")
        self.state["manual_regression"] = {
            "project_id": manual["id"],
            "shot_count": len(imported["shot_ids"]),
            "final_autonomy": final_manual["director_autonomy"],
            "node_run_count": 0,
            "provider_operation_count": 0,
        }
        self.state["assertions"]["manual_regression"] = "PASS"
        self.save()

    def delivery(self):
        remote_before = {}
        for label in ("template_auto", "free_assist"):
            project_id = self.state["projects"][label]["id"]
            remote_before[label] = len(
                self.remote_media_operations(self.read(f"/projects/{project_id}/snapshot"))
            )

        free_edit = self.state["steps"]["free_assist:timeline-save"]["response"]
        free_id = self.state["projects"]["free_assist"]["id"]

        def rerender_timeline():
            timeline = json.loads(json.dumps(free_edit["timeline"]))
            timeline["clips"][0]["subtitle"] = (
                str(timeline["clips"][0].get("subtitle") or "") + " · 复核版"
            )
            timeline.setdefault("metadata", {})["r7_editing_only_rerender"] = self.state["run_key"]
            return {"timeline": timeline}

        saved = self.once(
            "free_assist:rerender-save",
            "PATCH",
            f"/projects/{free_id}/edit-sessions/{free_edit['id']}/timeline",
            rerender_timeline,
        )
        prepared = self.once(
            "free_assist:rerender-tail",
            "POST",
            f"/projects/{free_id}/final-film/prepare",
            {
                "edit_session_id": saved["id"],
                "expected_timeline_version": saved["version"],
                "mode": "prepare",
            },
        )
        for run_id in prepared["node_run_ids"]:
            self.wait_run(free_id, run_id)
        rerender = self.once(
            "free_assist:rerender-film",
            "POST",
            f"/projects/{free_id}/final-film/render",
            {
                "edit_session_id": saved["id"],
                "expected_timeline_version": saved["version"],
                "name": "R7 editing-only rerender",
            },
            command_key=f"r7:{self.state['run_key']}:free_assist:rerender",
        )
        self.wait_run(free_id, rerender["node_run_id"])
        self.state["free_assist:rerender_job"] = self.read(
            f"/projects/{free_id}/final-film/runs/{rerender['node_run_id']}"
        )

        deliveries = {}
        for label in ("template_auto", "free_assist"):
            project_id = self.state["projects"][label]["id"]
            job = (
                self.state["free_assist:rerender_job"]
                if label == "free_assist"
                else self.state["template_auto:final_job"]
            )
            result = job.get("result")
            if job.get("status") not in {
                "completed",
                "cached",
                "completed_after_cancel",
            } or not isinstance(result, dict):
                raise RuntimeError(f"{label} Final Film is not complete")
            probe_assertions = (result.get("ffprobe") or {}).get("assertions")
            if not isinstance(probe_assertions, dict) or not all(probe_assertions.values()):
                raise RuntimeError(f"{label} Final Film ffprobe assertions failed")
            duration = float(result.get("duration_seconds") or 0)
            if not 15 <= duration <= 30:
                raise RuntimeError(f"{label} Final Film is outside 15–30 seconds")
            film_response = self.client.get(
                f"/projects/{project_id}/artifacts/{result['artifact_id']}/content",
                headers=self.headers,
            )
            subtitle_response = self.client.get(
                f"/projects/{project_id}/artifacts/{result['subtitle_artifact_id']}/content",
                headers=self.headers,
            )
            if film_response.is_error or subtitle_response.is_error:
                raise RuntimeError(f"{label} Final Film or SRT download failed")
            film_hash = hashlib.sha256(film_response.content).hexdigest()
            subtitle_hash = hashlib.sha256(subtitle_response.content).hexdigest()
            if (
                film_hash != result["content_hash"]
                or subtitle_hash != result["subtitle_content_hash"]
            ):
                raise RuntimeError(f"{label} downloaded delivery hash mismatch")
            subtitle_text = subtitle_response.content.decode("utf-8-sig")
            if "-->" not in subtitle_text or not subtitle_text.strip():
                raise RuntimeError(f"{label} independent SRT is empty or invalid")
            deliveries[label] = {
                "project_id": project_id,
                "node_run_id": job["node_run_id"],
                "artifact_id": result["artifact_id"],
                "subtitle_artifact_id": result["subtitle_artifact_id"],
                "timeline_version": result["timeline_version"],
                "duration_seconds": result["duration_seconds"],
                "film_sha256": film_hash,
                "film_byte_size": len(film_response.content),
                "subtitle_sha256": subtitle_hash,
                "subtitle_byte_size": len(subtitle_response.content),
                "subtitle_cue_count": result["subtitle_cue_count"],
                "formal_reference_count": len(result["formal_references"]),
                "ffprobe": sanitized(result["ffprobe"]),
            }
            if self.evidence_dir is not None:
                self.evidence_dir.mkdir(parents=True, exist_ok=True)
                film_path = self.evidence_dir / f"{label}-final-film.mp4"
                subtitle_path = self.evidence_dir / f"{label}-final-film.srt"
                film_path.write_bytes(film_response.content)
                subtitle_path.write_bytes(subtitle_response.content)
                deliveries[label]["film_file"] = film_path.name
                deliveries[label]["subtitle_file"] = subtitle_path.name
        remote_after = {
            label: len(
                self.remote_media_operations(
                    self.read(f"/projects/{self.state['projects'][label]['id']}/snapshot")
                )
            )
            for label in ("template_auto", "free_assist")
        }
        if remote_before != remote_after:
            raise RuntimeError("Editing-only rerender created a remote image/video operation")
        self.state["deliveries"] = deliveries
        self.state["editing_only_rerender"] = {
            "remote_media_operations_before": remote_before,
            "remote_media_operations_after": remote_after,
            "delta": 0,
        }
        self.state["assertions"]["editing_only_rerender"] = "PASS"
        self.state["assertions"]["final_mp4_srt_download"] = "PASS"
        self.save()

    def import_external_proof(self, kind, path):
        proof = json.loads(path.read_text(encoding="utf-8"))
        if proof.get("candidate_sha") != self.state.get("candidate_sha"):
            raise RuntimeError(f"{kind} proof belongs to another candidate")
        if kind == "recovery":
            expected_run = (self.state.get("review_repair") or {}).get("repair_run_id")
            required = {
                "repair_run_id": expected_run,
                "provider_operation_count_before_restart": 1,
                "provider_operation_count_after_completion": 1,
                "additional_create_count": 0,
                "worker_stopped": True,
                "worker_restarted": True,
                "final_status": "completed",
            }
            if any(proof.get(key) != value for key, value in required.items()):
                raise RuntimeError("Recovery proof does not establish one-task restart recovery")
            if not proof.get("remote_id_hash_before") or proof.get(
                "remote_id_hash_before"
            ) != proof.get("remote_id_hash_after"):
                raise RuntimeError("Recovery proof does not preserve the remote task identity")
            self.state["assertions"]["real_remote_recovery"] = "PASS"
        elif kind == "browser":
            expected = {
                label: self.state["projects"][label]["id"]
                for label in ("template_auto", "free_assist")
            }
            assertions = proof.get("assertions")
            if (
                proof.get("entry_port") != 8080
                or proof.get("project_ids") != expected
                or not isinstance(assertions, dict)
                or not assertions
                or not all(value is True for value in assertions.values())
                or proof.get("console_error_count") != 0
            ):
                raise RuntimeError("Browser proof is incomplete or is not from the formal entry")
            self.state["assertions"]["browser_interaction"] = "PASS"
        elif kind == "runtime":
            services = proof.get("services")
            if (
                proof.get("entry_port") != 8080
                or proof.get("migration_head") != "20260908_0060"
                or not isinstance(services, dict)
                or set(services)
                != {"api", "dispatcher", "worker_default", "worker_heavy", "frontend"}
                or any(
                    row.get("source_commit") != self.state.get("candidate_sha")
                    or row.get("healthy") is not True
                    for row in services.values()
                )
            ):
                raise RuntimeError(
                    "Formal runtime proof does not bind every service to the candidate"
                )
            self.state["assertions"]["final_8080_identity"] = "PASS"
        else:
            raise RuntimeError(f"Unknown external proof kind: {kind}")
        self.state.setdefault("external_proofs", {})[kind] = sanitized(proof)
        self.save()

    def promote_candidate(self, candidate_sha, proof_path):
        if proof_path is None:
            raise RuntimeError("Candidate promotion requires a source-equivalence proof")
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        previous = self.state.get("candidate_sha")
        allowed_paths = {
            "backend/app/execution/artifact_lineage.py",
            "backend/tests/integration/test_artifact_lineage_pg.py",
            "backend/tests/unit/test_r7_acceptance_driver.py",
            "frontend/tests/live/v1-r7-real-acceptance.spec.ts",
            "scripts/prove_v1_r7_acceptance.py",
        }
        changed_paths = set(proof.get("changed_paths") or [])
        if (
            not previous
            or proof.get("previous_candidate") != previous
            or proof.get("candidate_sha") != candidate_sha
            or not changed_paths
            or not changed_paths <= allowed_paths
            or "backend/app/execution/artifact_lineage.py" not in changed_paths
            or proof.get("provider_submission_diff_empty") is not True
            or proof.get("full_quality_gate") != "PASS"
            or proof.get("concurrent_artifact_pg_regression") != "PASS"
        ):
            raise RuntimeError("Candidate source-equivalence proof is incomplete")
        if self.state["assertions"].get("template_auto:formal_media") != "PASS" or self.state[
            "assertions"
        ].get("free_assist:formal_media") != "PASS":
            raise RuntimeError("Candidate promotion requires completed dual-path media evidence")
        self.state.setdefault("candidate_history", []).append(
            {
                "candidate_sha": previous,
                "preserved_media_assertions": {
                    label: self.state["assertions"].get(label + ":formal_media")
                    for label in ("template_auto", "free_assist")
                },
                "reason": "acceptance_discovered_artifact_identity_concurrency_fix",
            }
        )
        self.state["candidate_sha"] = candidate_sha
        self.state["candidate_equivalence"] = sanitized(proof)
        self.state["assertions"]["candidate_source_equivalence"] = "PASS"
        self.save()

    def collect(self):
        for label in ("template_auto", "free_assist"):
            project = self.state["projects"][label]
            pid = project["id"]
            self.state[label + ":snapshot"] = sanitized(self.read(f"/projects/{pid}/snapshot"))
            self.state[label + ":director_turns"] = sanitized(
                self.read(f"/projects/{pid}/director/turns?limit=100")
            )
        self.save()
        if self.state["projects"]["template_auto"]["id"] == self.state["projects"][
            "free_assist"
        ]["id"]:
            raise RuntimeError("Dual-path acceptance reused one Project identity")
        text_turn_ids = {
            self.state["steps"]["template:story"]["response"]["director_evidence"]["turn_id"],
            self.state["steps"]["template:shot-text"]["response"]["director_evidence"]["turn_id"],
            self.state["steps"]["free:shot-text"]["response"]["director_evidence"]["turn_id"],
            self.state["steps"]["free_assist:editing-text"]["response"]["director_evidence"][
                "turn_id"
            ],
        }
        all_turns = [
            turn
            for label in ("template_auto", "free_assist")
            for turn in self.state[label + ":director_turns"]
        ]
        selected_turns = [turn for turn in all_turns if turn.get("id") in text_turn_ids]
        if len(selected_turns) != 4 or any(
            turn.get("transport_status") != "succeeded"
            or not turn.get("context_hash")
            or not turn.get("output_hash")
            or not turn.get("model_resolution")
            for turn in selected_turns
        ):
            raise RuntimeError("Story/Shot/Editing text turns lack durable model/hash lineage")
        self.state["assertions"]["text_turn_lineage"] = "PASS"

        provider_identities = {}
        media_execution_freeze = {}
        allowed_source_commits = {self.state.get("candidate_sha")}
        equivalence = self.state.get("candidate_equivalence")
        if (
            self.state["assertions"].get("candidate_source_equivalence") == "PASS"
            and isinstance(equivalence, dict)
        ):
            allowed_source_commits.add(equivalence.get("previous_candidate"))
        for label in ("template_auto", "free_assist"):
            snapshot = self.state[label + ":snapshot"]
            expected = len(self.state["formal_shot_ids"][label]) * 2
            dispatch_steps = [
                step
                for name, step in self.state["steps"].items()
                if name.endswith(":dispatch")
                and (
                    name.startswith(label + ":")
                    or (label == "free_assist" and name.startswith("free-revision:"))
                )
            ]
            dispatch_run_ids = {
                step["response"]["node_run_id"]
                for step in dispatch_steps
                if step.get("status") == "succeeded"
            }
            frozen_runs = [
                run
                for run in snapshot.get("node_runs", [])
                if run.get("id") in dispatch_run_ids
                and run.get("status") in {"completed", "cached", "completed_after_cancel"}
            ]
            successful_run_ids = {run["id"] for run in frozen_runs}
            remote = [
                operation
                for operation in self.remote_media_operations(snapshot)
                if operation.get("node_run_id") in successful_run_ids
            ]
            if len(remote) < expected or any(
                operation.get("status") != "succeeded"
                or operation.get("actual_provider") != "agnes"
                or operation.get("actual_model")
                not in {"agnes-image-2.1-flash", "agnes-video-v2.0"}
                or not operation.get("model_binding_id")
                or not operation.get("connection_id")
                or not operation.get("credential_revision_id")
                for operation in remote
            ):
                raise RuntimeError(f"{label} remote Provider identities are incomplete")
            provider_identities[label] = [
                {
                    "node_run_id": operation.get("node_run_id"),
                    "actual_provider": operation.get("actual_provider"),
                    "actual_model": operation.get("actual_model"),
                    "model_binding_id": operation.get("model_binding_id"),
                    "connection_id": operation.get("connection_id"),
                    "credential_revision_id": operation.get("credential_revision_id"),
                    "provider_cost": operation.get("provider_cost"),
                    "cost_status": (
                        "reported"
                        if (operation.get("response_summary") or {}).get("provider_reported_cost")
                        is not None
                        else "unknown"
                    ),
                    "currency": operation.get("currency"),
                }
                for operation in remote
            ]
            if len(frozen_runs) != expected or any(
                (run.get("input_snapshot") or {}).get("source_commit")
                not in allowed_source_commits
                or not (run.get("input_snapshot") or {}).get("model_binding_id")
                or not ((run.get("input_snapshot") or {}).get("execution_identity") or {}).get(
                    "credential_revision_id"
                )
                or run.get("status") not in {"completed", "cached", "completed_after_cancel"}
                for run in frozen_runs
            ):
                raise RuntimeError(f"{label} media NodeRuns are not frozen to the candidate")
            media_execution_freeze[label] = [
                {
                    "node_run_id": run.get("id"),
                    "node_key": run.get("node_key"),
                    "source_commit": (run.get("input_snapshot") or {}).get("source_commit"),
                    "model_binding_id": (run.get("input_snapshot") or {}).get(
                        "model_binding_id"
                    ),
                    "connection_revision_id": (
                        (run.get("input_snapshot") or {}).get("execution_identity") or {}
                    ).get("connection_revision_id"),
                    "credential_revision_id": (
                        (run.get("input_snapshot") or {}).get("execution_identity") or {}
                    ).get("credential_revision_id"),
                    "input_hash": run.get("input_hash"),
                    "result_artifact_id": run.get("result_artifact_id"),
                    "status": run.get("status"),
                }
                for run in frozen_runs
            ]
        self.state["provider_identities"] = provider_identities
        self.state["media_execution_freeze"] = media_execution_freeze
        self.state["assertions"]["provider_identity_no_fallback"] = "PASS"
        self.state["assertions"]["distinct_projects_shared_runtime"] = "PASS"

        for gate in (
            "editing_advice_apply",
            "review_repair",
            "manual_regression",
            "real_remote_recovery",
            "browser_interaction",
            "final_8080_identity",
            "final_mp4_srt_download",
            "editing_only_rerender",
            "negative_boundaries",
        ):
            self.state["assertions"].setdefault(gate, "NOT_VERIFIED")
        required = {
            "preflight",
            "story_and_user_decisions",
            "template_auto:formal_media",
            "free_assist:formal_media",
            "editing_advice_apply",
            "review_repair",
            "manual_regression",
            "real_remote_recovery",
            "browser_interaction",
            "final_8080_identity",
            "final_mp4_srt_download",
            "editing_only_rerender",
            "negative_boundaries",
            "text_turn_lineage",
            "provider_identity_no_fallback",
            "distinct_projects_shared_runtime",
        }
        if self.state.get("candidate_history"):
            required.add("candidate_source_equivalence")
        if self.state.get("local_artifact_race_failure"):
            required.add("local_artifact_race_recovery")
        if self.state.get("unreconciled_media_submissions"):
            required.add("unknown_submission_not_replayed")
        self.state["complete"] = all(
            self.state["assertions"].get(gate) == "PASS" for gate in required
        )
        self.state["required_assertions"] = sorted(required)
        self.save()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8088/api/v1")
    parser.add_argument(
        "--phase",
        choices=[
            "preflight",
            "story",
            "media",
            "revise-unknown-free",
            "replace-template",
            "editing",
            "recover-local-editing",
            "promote-candidate",
            "review-submit",
            "review-collect",
            "regressions",
            "delivery",
            "collect",
        ],
        default="preflight",
    )
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--candidate", help="Exact runtime source SHA required for paid phases")
    parser.add_argument("--candidate-equivalence-proof", type=Path)
    parser.add_argument("--recovery-proof", type=Path)
    parser.add_argument("--browser-proof", type=Path)
    parser.add_argument("--runtime-proof", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=600, trust_env=False) as client:
        run = Acceptance(client, args.state, real=args.real, evidence_dir=args.evidence_dir)
        run.login()
        if args.phase == "promote-candidate" and not args.real:
            raise RuntimeError("Candidate promotion requires exact runtime verification")
        if args.real:
            if not args.candidate or not re.fullmatch(r"[0-9a-f]{40}", args.candidate):
                raise RuntimeError("Paid acceptance requires an exact --candidate SHA")
            origin = urlsplit(args.base_url)
            health = client.get(
                urlunsplit((origin.scheme, origin.netloc, "/health", "", ""))
            ).json()
            if health.get("source_commit") != args.candidate or health.get("env") == "test":
                raise RuntimeError("Runtime identity/environment does not match the paid candidate")
            prior = run.state.get("candidate_sha")
            if prior and prior != args.candidate:
                if args.phase != "promote-candidate":
                    raise RuntimeError(
                        "Candidate changed; preserve prior evidence and do not relabel it"
                    )
                run.promote_candidate(args.candidate, args.candidate_equivalence_proof)
            else:
                if args.phase == "promote-candidate":
                    raise RuntimeError("Candidate promotion target already matches the checkpoint")
                run.state["candidate_sha"] = args.candidate
                run.save()
        for kind, proof_path in (
            ("recovery", args.recovery_proof),
            ("browser", args.browser_proof),
            ("runtime", args.runtime_proof),
        ):
            if proof_path is not None:
                run.import_external_proof(kind, proof_path)
        if args.phase != "promote-candidate":
            getattr(run, args.phase.replace("-", "_"))()
        print(
            json.dumps(
                {
                    "phase": args.phase,
                    "steps": len(run.state["steps"]),
                    "assertions": run.state["assertions"],
                    "goal_complete": run.state.get("complete", False),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
