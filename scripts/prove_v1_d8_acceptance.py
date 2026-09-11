#!/usr/bin/env python3
"""V1-D8 candidate-bound real acceptance for the independent director runtime.

Two product chains are driven through authenticated canonical HTTP APIs against
one exact runtime source commit:

  Template + AUTO  real text proposal, user decision, bounded AUTO delegation,
                   independent director worker, exactly one canonical NodeRun,
                   real keyframe/video media, Formal, Editing, MP4/SRT.
  Free + ASSIST    free script, real Shot/Editing proposals with partial
                   accept/reject, manual execution, the same production kernel
                   and the same delivery.

Default phases perform no Provider calls. ``--real`` is required by any phase
that can bill a Provider, and ``--candidate`` must equal the running
``/health`` ``source_commit``.

MANUAL director-off production is proven separately by the D8 local evidence.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx

# The shared acceptance plumbing persists JSON with the platform default
# encoding. On a Windows GBK locale that cannot round-trip the Chinese product
# strings, so re-exec once in UTF-8 mode before any file I/O happens.
if not sys.flags.utf8_mode and not os.environ.get("DRAMAFORGE_D8_UTF8"):
    os.environ["DRAMAFORGE_D8_UTF8"] = "1"
    os.execv(sys.executable, [sys.executable, "-X", "utf8", *sys.argv])

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = "c00b1899-b4ac-46c7-b4c7-25a230e9ebe2"
ACCEPTANCE_PROJECT = "dramaforge-v1-d8-acceptance"
TEMPLATE = {"key": "single_monologue_v1", "version": "1"}
MEDIA_SHOT_LIMIT = 4


def _load_r7():
    """Reuse the R7 acceptance plumbing (state, receipts, proven delivery)."""
    path = Path(__file__).resolve().with_name("prove_v1_r7_acceptance.py")
    spec = importlib.util.spec_from_file_location("prove_v1_r7_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.WORKSPACE = WORKSPACE
    return module


r7 = _load_r7()


def psql(query: str) -> str:
    """Read-only query against the isolated acceptance database."""
    result = subprocess.run(
        ["docker", "exec", "-i", f"{ACCEPTANCE_PROJECT}-postgres-1", "psql",
         "-U", "dramaforge", "-d", "dramaforge", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1"],
        input=query, capture_output=True, text=True, encoding="utf-8", check=False)
    if result.returncode:
        raise RuntimeError("Acceptance database query failed; raw output withheld")
    return result.stdout.strip()


class D8Acceptance(r7.Acceptance):
    def __init__(self, client, state_path, *, real, evidence_dir=None):
        super().__init__(client, state_path, real=real, evidence_dir=evidence_dir)
        self.workspace = self.state.get("workspace_id", WORKSPACE)

    def login(self):
        response = self.client.post(
            "/auth/login",
            json={
                "email": "professional-proof@example.com",
                "password": "professional-proof-password-2026",
            },
        )
        if response.is_error:
            raise RuntimeError(f"Acceptance login failed: HTTP {response.status_code}")
        self.headers = {
            "X-Workspace-Id": self.workspace,
            "X-CSRF-Token": self.read("/auth/csrf")["csrf_token"],
        }
        self.state["workspace_id"] = self.workspace
        self.save()

    # ------------------------------------------------------------------ helpers
    def decide_turn(self, name, project_id, turn_id, *, decision="accept", indices=(0,),
                    wait_seconds=240):
        """Route one user decision to the endpoint that owns the bound engine.

        A bound turn only becomes decidable once the director worker has driven
        the graph to its decision checkpoint, so wait for the runtime revision
        before choosing the endpoint.
        """
        turn = self.read(f"/projects/{project_id}/director/turns/{turn_id}")
        if turn.get("engine_version") and turn.get("runtime_revision") is None:
            deadline = time.monotonic() + wait_seconds
            while time.monotonic() < deadline and turn.get("runtime_revision") is None:
                if turn.get("status") in {"failed", "stopped", "completed"}:
                    break
                time.sleep(3)
                turn = self.read(f"/projects/{project_id}/director/turns/{turn_id}")
        if turn.get("runtime_revision") is not None:
            return self.once(
                name, "POST",
                f"/projects/{project_id}/director/runtime/turns/{turn_id}/decision",
                {
                    "decision": decision,
                    "accepted_operation_indices": list(indices),
                    "signal_id": str(uuid4()),
                    "expected_revision": turn["revision"],
                    "expected_runtime_revision": turn["runtime_revision"],
                },
            )
        return self.once(
            name, "POST",
            f"/projects/{project_id}/director/turns/{turn_id}/decision",
            {
                "decision": decision,
                "accepted_operation_indices": list(indices),
                "expected_revision": turn["revision"],
            },
        )

    def wait_turn_node_run(self, project_id, turn_id, *, deadline_seconds=900):
        """Wait for the director worker to create the authorized NodeRun."""
        deadline = time.monotonic() + deadline_seconds
        last = None
        while time.monotonic() < deadline:
            turn = self.read(f"/projects/{project_id}/director/turns/{turn_id}")
            last = turn
            created = list(turn.get("node_run_ids") or [])
            if len(created) > 1:
                raise RuntimeError("AUTO delegation created more than one NodeRun")
            if created:
                return turn, created[0]
            if turn.get("status") in {"failed", "stopped"}:
                raise RuntimeError(
                    f"Delegated turn reached {turn.get('status')}: {turn.get('last_error')}"
                )
            time.sleep(4)
        raise RuntimeError(f"Delegated turn produced no NodeRun; last state {last.get('status')}")

    # ---------------------------------------------------------------- preflight
    def preflight(self):
        models = self.read("/models")
        configured = {row["id"] for row in models if row.get("configured")}
        required = {
            "litellm/script-quality",
            "agnes/agnes-image-2.1-flash",
            "agnes/agnes-video-v2.0",
        }
        if not required <= configured:
            raise RuntimeError("The explicitly selected acceptance models are not configured")
        self.state["models"] = [
            {k: row.get(k) for k in ("id", "configured", "provider_id")} for row in models
        ]
        self.state["unconfigured_providers"] = sorted(
            row["provider_id"] for row in models if not row.get("configured")
        )
        profiles = self.read(f"/workspaces/{self.workspace}/model-profiles")
        if not any(row.get("is_default") for row in profiles):
            self.once(
                "workspace_profile", "POST",
                f"/workspaces/{self.workspace}/model-profiles",
                {
                    "name": "V1-D8 explicit text configuration",
                    "is_default": True,
                    "bindings": {
                        slot: {"model_id": "litellm/script-quality", "enabled": True}
                        for slot in ("planning.brief", "planning.script", "planning.storyboard")
                    },
                },
            )
        connections = self.read(f"/workspaces/{self.workspace}/provider-connections")
        agnes = next(
            row for row in connections
            if row.get("provider_type") == "agnes" and row.get("enabled")
        )
        bindings = self.read(
            f"/workspaces/{self.workspace}/provider-connections/{agnes['id']}/model-bindings"
        )
        self.state["bindings"] = {
            purpose: next(
                row for row in bindings
                if row.get("purpose") == purpose and row.get("enabled")
                and row.get("account_verified")
            )
            for purpose in ("keyframe", "video")
        }
        existing = self.read(f"/workspaces/{self.workspace}/projects")
        for label, start, mode in (
            ("template_auto", "TEMPLATE", "AUTO"),
            ("free_assist", "FREE", "ASSIST"),
        ):
            name = f"V1-D8 {label} {self.state['run_key']}"
            project = next((row for row in existing if row["name"] == name), None)
            if project is None:
                project = self.once(
                    f"project:{label}", "POST", "/projects",
                    {
                        "workspace_id": self.workspace,
                        "name": name,
                        "aspect_ratio": "9:16",
                        "start_type": start,
                        "director_autonomy": mode,
                        **(
                            {"template_key": TEMPLATE["key"], "template_version": TEMPLATE["version"]}
                            if start == "TEMPLATE" else {}
                        ),
                    },
                )
            self.state["projects"][label] = project
            self.save()
            for purpose in ("keyframe", "video"):
                self.once(
                    f"binding:{label}:{purpose}", "PUT",
                    f"/projects/{project['id']}/provider-bindings/{purpose}",
                    {"model_binding_id": self.state["bindings"][purpose]["id"]},
                )
        self.state["assertions"]["preflight"] = "PASS"
        self.save()

    # -------------------------------------------------------------------- story
    def story(self):
        template = self.state["projects"]["template_auto"]["id"]
        generated = self.once(
            "template:story", "POST",
            f"/projects/{template}/story/proposals/generate",
            {
                "request_key": f"d8:{self.state['run_key']}:story",
                "brief": r7.BRIEF,
                "filename": "last-bus.md",
            },
            paid=True,
        )
        proposal_id = generated["proposal"]["id"]
        # The create response does not serialize the freshly created items; the
        # canonical read is the authoritative view of the typed operations.
        proposal = self.read(f"/projects/{template}/story/proposals/{proposal_id}")
        operations = proposal["operations"]
        shot_ops = [op for op in operations if op["command"] == "story.upsert_shot"]
        # Keep at least four accepted shots so the saved cut stays inside the
        # delivery duration the Final Film gate asserts; the script itself
        # decides the real shot count.
        if len(shot_ops) < 5:
            raise RuntimeError(
                f"Generated story has {len(shot_ops)} shots; needs at least five "
                "before one is rejected"
            )
        rejected = shot_ops[-1]["id"]
        applied = self.once(
            "template:story-apply", "POST",
            f"/projects/{template}/story/proposals/{proposal_id}/apply",
            {
                "decisions": [
                    {"item_id": op["id"],
                     "decision": "rejected" if op["id"] == rejected else "accepted"}
                    for op in operations
                ]
            },
        )
        if applied.get("failed"):
            raise RuntimeError("Story apply has failed items; no media dispatch permitted")
        turn_id = generated["director_evidence"]["turn_id"]
        # A proposal-bound turn is decided through the canonical Proposal API:
        # the runtime decision endpoint deliberately rejects it and the bound
        # engine resumes from the persisted canonical decision.
        story_turn = self.read(f"/projects/{template}/director/turns/{turn_id}")
        self.state["template_auto:story"] = {
            "proposal_id": proposal_id,
            "turn_id": turn_id,
            "operations": len(operations),
            "shots": len(shot_ops),
            "rejected_operation": rejected,
            "engine_version": story_turn.get("engine_version"),
            "runtime_revision": story_turn.get("runtime_revision"),
            "status": story_turn.get("status"),
            "wait_reason": story_turn.get("wait_reason"),
            "resumed_by_canonical_decision": story_turn.get("status") == "completed",
        }
        if story_turn.get("engine_version") is None:
            raise RuntimeError("Story proposal turn is not bound to a runtime engine")
        if story_turn.get("status") != "completed":
            raise RuntimeError(
                f"Bound story turn did not complete from the canonical decision: "
                f"{story_turn.get('status')}/{story_turn.get('wait_reason')}"
            )
        self.save()

        free = self.state["projects"]["free_assist"]["id"]
        self.once(
            "free:import", "POST", f"/projects/{free}/scripts/import",
            {"filename": "letter-before-dawn.md", "text": r7.FREE_SCRIPT},
        )
        for label, project in (("template", template), ("free", free)):
            shot = self.shots(project)[0]
            sid = shot["id"]
            suggestion = self.once(
                f"{label}:shot-text", "POST",
                f"/projects/{project}/director/shots/{sid}/suggestion",
                {
                    "scene_id": shot["scene_id"],
                    "shot_id": sid,
                    "expected_shot_version": shot["version"],
                    "request_key": f"d8:{self.state['run_key']}:{label}:shot",
                    "user_instruction": (
                        "保持静止摄影机，不要推镜；把人物表情调整得更克制，保留米色服装。"
                    ),
                },
                paid=True,
            )
            turn_id = suggestion["director_evidence"]["turn_id"]
            turn = self.read(f"/projects/{project}/director/turns/{turn_id}")
            self.state.setdefault("shot_suggestion_turns", {})[label] = {
                "turn_id": turn_id,
                "engine_version": turn.get("engine_version"),
                "runtime_revision": turn.get("runtime_revision"),
            }
            self.save()
            self.decide_turn(f"{label}:accept-shot-runtime", project, turn_id,
                             decision="accept", indices=[0])
            self.once(
                f"{label}:save-shot", "PATCH", f"/projects/{project}/shots/{sid}/design",
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

    # -------------------------------------------------------------------- media
    def _preview(self, pid, sid, stage, purpose):
        shot = self.shot(pid, sid)
        return {
            "stage": stage,
            "prompt": shot.get("image_prompt" if purpose == "keyframe" else "video_prompt")
            or shot["visual_description"],
            "expected_shot_version": shot["version"],
            "mode_id": "text_to_image" if purpose == "keyframe" else "first_frame",
            "requested_binding_id": self.state["bindings"][purpose]["id"],
            "references": [],
            "semantic_intent": {},
            "accept_approximations": False,
        }

    def media(self):
        """Template uses the AUTO delegation path; Free uses the manual path.

        Media generation is bounded to the shots each path needs for a valid
        cut: the Owner implementation asks for the minimum necessary new calls
        rather than regenerating the whole script, and the Final Film gate needs
        at least four complete Formal shots to stay inside its duration rule.
        """
        self.state["media_shot_limit"] = MEDIA_SHOT_LIMIT
        for label, project in self.state["projects"].items():
            pid = project["id"]
            delegated = label == "template_auto"
            all_shots = self.shots(pid)
            selected = all_shots[:MEDIA_SHOT_LIMIT]
            self.state.setdefault("media_scope", {})[label] = {
                "shots_in_project": len(all_shots),
                "shots_generated": len(selected),
            }
            self.save()
            for original in selected:
                sid = original["id"]
                for stage, formal, purpose in (
                    ("image_keyframe", "keyframe", "keyframe"),
                    ("video", "video", "video"),
                ):
                    prefix = f"{label}:{sid}:{stage}"
                    preview = self.once(
                        prefix + ":preview", "POST",
                        f"/projects/{pid}/shots/{sid}/execution-plan",
                        lambda pid=pid, sid=sid, stage=stage, purpose=purpose: self._preview(
                            pid, sid, stage, purpose
                        ),
                    )
                    if any(
                        gap["severity"] == "fatal"
                        for gap in preview["plan"]["capability_gaps"]
                    ):
                        raise RuntimeError("Unsupported preview; no silent adaptation")
                    body = self.state["steps"][prefix + ":preview"]["request"]
                    key = f"d8:{self.state['run_key']}:{sid}:{stage}"
                    frozen = {
                        **body,
                        "plan_fingerprint": preview["plan_fingerprint"],
                        "accepted_approximations": [],
                    }
                    if delegated:
                        decision_id = str(uuid4())
                        turn = self.once(
                            prefix + ":delegate", "POST",
                            f"/projects/{pid}/director/runtime/shots/{sid}/executions",
                            {
                                "decision_id": decision_id,
                                "authorization_expires_at": (
                                    datetime.now(timezone.utc) + timedelta(minutes=20)
                                ).isoformat(),
                                "max_steps": 6,
                                "execution": frozen,
                            },
                            paid=True,
                            command_key=f"{key}:auto",
                        )
                        turn, run_id = self.wait_turn_node_run(pid, turn["id"])
                        self.state.setdefault("auto_turns", []).append(
                            {
                                "shot_id": sid,
                                "stage": stage,
                                "turn_id": turn["id"],
                                "engine_version": turn.get("engine_version"),
                                "runtime_execution_id": turn.get("runtime_execution_id"),
                                "runtime_revision": turn.get("runtime_revision"),
                                "node_run_ids": list(turn.get("node_run_ids") or []),
                                "status": turn.get("status"),
                            }
                        )
                        self.save()
                    else:
                        receipt = self.once(
                            prefix + ":dispatch", "POST",
                            f"/projects/{pid}/shots/{sid}/executions",
                            frozen, paid=True, command_key=key,
                        )
                        run_id = receipt["node_run_id"]
                    run = self.wait_run(pid, run_id)
                    self.once(
                        prefix + ":formal", "POST",
                        f"/projects/{pid}/shots/{sid}/formal-{formal}",
                        lambda run=run, pid=pid, sid=sid: {
                            "artifact_id": run["result_artifact_id"],
                            "expected_shot_version": self.shot(pid, sid)["version"],
                        },
                    )
            formal_shots = [
                shot for basic in self.shots(pid)
                if (shot := self.shot(pid, basic["id"])).get("formal_keyframe_artifact_id")
                and shot.get("formal_video_artifact_id")
            ]
            if len(formal_shots) < 4:
                raise RuntimeError(f"{label} has fewer than four complete Formal media shots")
            self.state.setdefault("formal_shot_ids", {})[label] = [s["id"] for s in formal_shots]
            self.state["assertions"][label + ":formal_media"] = "PASS"
            self.save()

    # ------------------------------------------------------------------ runtime
    def runtime(self):
        """Prove the independent director runtime facts for this exact run."""
        template = self.state["projects"]["template_auto"]["id"]
        turns = self.read(f"/projects/{template}/director/turns?limit=100")
        bound = [t for t in turns if t.get("engine_version") or t.get("runtime_execution_id")]
        auto_turn_ids = {t["turn_id"] for t in self.state.get("auto_turns", [])}
        evidence = {
            "turns_total": len(turns),
            "turns_bound_to_engine": len(bound),
            "engines": sorted({t.get("engine_version") for t in bound if t.get("engine_version")}),
            "auto_turns": self.state.get("auto_turns", []),
            "auto_turn_node_run_counts": {
                t["turn_id"]: len(t.get("node_run_ids") or [])
                for t in self.state.get("auto_turns", [])
            },
            "director_rows": {
                "turns": int(psql(
                    f"SELECT count(*) FROM director_turns WHERE project_id='{template}';")),
                "runtime_controls": int(psql(
                    f"SELECT count(*) FROM director_runtime_controls WHERE project_id='{template}';")),
                "runtime_wakeups": int(psql(
                    f"SELECT count(*) FROM director_runtime_wakeups WHERE project_id='{template}';")),
            },
            "checkpoint_schemas": psql(
                "SELECT coalesce(string_agg(schema_name, ',' ORDER BY schema_name), '')"
                " FROM information_schema.schemata WHERE schema_name LIKE 'lg_%'"
                " OR schema_name LIKE '%checkpoint%';"),
        }
        if not bound:
            raise RuntimeError("No turn is bound to a runtime engine on the AUTO path")
        if len(auto_turn_ids) < 2:
            raise RuntimeError("AUTO delegation did not cover both stages")
        for turn_id, count in evidence["auto_turn_node_run_counts"].items():
            if count != 1:
                raise RuntimeError(f"Delegated turn {turn_id} has {count} NodeRuns, expected 1")
        if evidence["director_rows"]["turns"] < 2:
            raise RuntimeError("Director turn rows are missing on the AUTO path")
        self.state["runtime_evidence"] = evidence
        self.state["assertions"]["independent_director_runtime"] = "PASS"
        self.save()

    # ---------------------------------------------------------------- evidence
    def collect(self):
        snapshot = {
            "candidate_sha": self.state.get("candidate_sha"),
            "workspace_id": self.workspace,
            "models": self.state.get("models"),
            "unconfigured_providers": self.state.get("unconfigured_providers"),
            "projects": {
                label: project["id"] for label, project in self.state["projects"].items()
            },
            "runtime_evidence": self.state.get("runtime_evidence"),
            "deliveries": self.state.get("deliveries"),
            "editing_only_rerender": self.state.get("editing_only_rerender"),
            "assertions": self.state.get("assertions"),
        }
        for label, project in self.state["projects"].items():
            snap = self.read(f"/projects/{project['id']}/snapshot")
            operations = snap.get("provider_operations", [])
            snapshot.setdefault("provider_operations", {})[label] = {
                "total": len(operations),
                "remote_media": len(self.remote_media_operations(snap)),
                "kinds": sorted({op.get("operation_kind") for op in operations}),
            }
            snapshot.setdefault("node_runs", {})[label] = len(snap.get("node_runs", []))
        required = {
            "preflight": "PASS",
            "story_and_user_decisions": "PASS",
            "template_auto:formal_media": "PASS",
            "free_assist:formal_media": "PASS",
            "independent_director_runtime": "PASS",
            "editing_only_rerender": "PASS",
            "final_mp4_srt_download": "PASS",
        }
        missing = {
            key: value for key, value in required.items()
            if (self.state.get("assertions") or {}).get(key) != value
        }
        snapshot["missing_assertions"] = missing
        snapshot["complete"] = not missing
        if self.evidence_dir is not None:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            (self.evidence_dir / "acceptance.json").write_text(
                json.dumps(r7.sanitized(snapshot), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        self.state["complete"] = snapshot["complete"]
        self.save()
        print(json.dumps({"complete": snapshot["complete"], "missing": missing},
                         ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8088/api/v1")
    parser.add_argument(
        "--phase",
        choices=["preflight", "story", "media", "runtime", "editing", "delivery", "collect"],
        default="preflight",
    )
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--candidate")
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=900, trust_env=False) as client:
        run = D8Acceptance(client, args.state, real=args.real, evidence_dir=args.evidence_dir)
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
            run.state["candidate_sha"] = args.candidate
            run.state["runtime_health"] = {
                "source_commit": health.get("source_commit"),
                "env": health.get("env"),
                "version": health.get("version"),
            }
            run.save()
        getattr(run, args.phase)()
        print(json.dumps(
            {"phase": args.phase, "steps": len(run.state["steps"]),
             "assertions": run.state["assertions"], "complete": run.state.get("complete", False)},
            ensure_ascii=False,
        ))


if __name__ == "__main__":
    main()
