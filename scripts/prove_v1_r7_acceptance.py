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
    "请创作一部约25秒、五个叙事镜头的写实短片《末班车之前》。只有一位成年虚构女性主角，"
    "在雨后的公交站捡到一张旧车票，犹豫、回忆、微笑，然后决定向前走。单一地点夜晚，"
    "服装始终是米色风衣，不要推镜，固定摄影机，通过景别和动作推进情绪。"
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


class Acceptance:
    def __init__(self, client, state_path: Path, *, real: bool):
        self.client = client
        self.path = state_path
        self.real = real
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
        return sorted(
            self.read(f"/projects/{project}/shots"), key=lambda row: (row["sort_order"], row["id"])
        )

    def shot(self, project, shot_id):
        return next(row for row in self.shots(project) if row["id"] == shot_id)

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
                    run = self.wait_run(pid, receipt["node_run_id"])
                    self.once(
                        prefix + ":formal",
                        "POST",
                        f"/projects/{pid}/shots/{sid}/formal-{formal}",
                        lambda run=run, pid=pid, sid=sid: {
                            "artifact_id": run["result_artifact_id"],
                            "expected_shot_version": self.shot(pid, sid)["version"],
                        },
                    )
            self.state["assertions"][label + ":formal_media"] = "PASS"
            self.save()

    def editing(self):
        for label, project in self.state["projects"].items():
            pid = project["id"]
            edit = self.once(
                label + ":edit", "POST", f"/projects/{pid}/edit-sessions", {"name": "R7 saved cut"}
            )
            eid = edit["id"]
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
            def edited(edit=edit, label=label):
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
                return {"timeline": timeline}

            saved = self.once(
                label + ":timeline-save",
                "PATCH",
                f"/projects/{pid}/edit-sessions/{eid}/timeline",
                edited,
            )
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

    def collect(self):
        for label, project in self.state["projects"].items():
            pid = project["id"]
            self.state[label + ":snapshot"] = sanitized(self.read(f"/projects/{pid}/snapshot"))
            self.state[label + ":director_turns"] = sanitized(
                self.read(f"/projects/{pid}/director/turns?limit=100")
            )
        # These additional required acceptance paths are intentionally not
        # declared passed just because primary production completed.
        for gate in (
            "editing_advice_apply",
            "review_repair",
            "manual_regression",
            "real_remote_recovery",
            "browser_interaction",
            "final_8080_identity",
            "final_mp4_srt_download",
        ):
            self.state["assertions"].setdefault(gate, "NOT_VERIFIED")
        self.state["complete"] = False
        self.save()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8088/api/v1")
    parser.add_argument(
        "--phase",
        choices=["preflight", "story", "media", "editing", "collect"],
        default="preflight",
    )
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--candidate", help="Exact runtime source SHA required for paid phases")
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=600, trust_env=False) as client:
        run = Acceptance(client, args.state, real=args.real)
        run.login()
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
                raise RuntimeError(
                    "Candidate changed; preserve prior evidence and do not relabel it"
                )
            run.state["candidate_sha"] = args.candidate
            run.save()
        getattr(run, args.phase)()
        print(
            json.dumps(
                {
                    "phase": args.phase,
                    "steps": len(run.state["steps"]),
                    "assertions": run.state["assertions"],
                    "goal_complete": False,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
