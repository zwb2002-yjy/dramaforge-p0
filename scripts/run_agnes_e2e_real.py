#!/usr/bin/env python3
"""Real end-to-end smoke against Agnes hub + DramaForge path.

Loads gitignored .env (AGNES_*). Never prints full API key.
Does not claim P0 Gate complete — only reports real call evidence.

Flow:
  1) Real image via get_flux_adapter() (AgnesImageAdapter)
  2) Real video create + poll via get_kling_adapter()
  3) FirstFramePipeline: Graph → NodeRun → Agnes image → Artifact → face
  4) Multi-shot mock (10 shots) on same project + export timeline/SRT hashes
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

env_path = REPO / ".env"
if env_path.is_file():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from app.config import Settings, clear_settings_cache  # noqa: E402
from app.providers.agnes import AgnesHubClient, AgnesImageAdapter  # noqa: E402
from app.providers.flux import get_flux_adapter  # noqa: E402
from app.providers.kling import get_kling_adapter  # noqa: E402


def redact(text: str, key: str) -> str:
    return text.replace(key, "***") if key else text


def short_uri(uri: object, n: int = 140) -> object:
    if uri is None:
        return None
    s = str(uri)
    return (s[:n] + "...") if len(s) > n else s


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Real Agnes provider smoke. This is not P0 completion evidence."
    )
    parser.add_argument(
        "--idea",
        required=True,
        help="Creative input for the real provider and local pipeline probes.",
    )
    parser.add_argument(
        "--image-prompt",
        default=None,
        help="Optional keyframe prompt; defaults to a neutral prompt derived from --idea.",
    )
    parser.add_argument(
        "--video-prompt",
        default=None,
        help="Optional video prompt; defaults to a neutral prompt derived from --idea.",
    )
    args = parser.parse_args()
    idea = args.idea.strip()
    if not idea:
        parser.error("--idea must not be empty")
    image_prompt = (args.image_prompt or f"Cinematic short-drama keyframe: {idea}").strip()
    video_prompt = (
        args.video_prompt or f"Cinematic short-drama video, slow camera movement: {idea}"
    ).strip()
    if not image_prompt or not video_prompt:
        parser.error("--image-prompt and --video-prompt must not be empty when provided")

    clear_settings_cache()
    settings = Settings(_env_file=str(env_path) if env_path.is_file() else None)
    key = settings.agnes_api_key
    report: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "base_url": settings.agnes_base_url,
        "image_model": settings.agnes_image_model,
        "video_model": settings.agnes_video_model,
        "configured": settings.agnes_configured(),
        "inputs": {
            "idea_length": len(idea),
            "image_prompt_length": len(image_prompt),
            "video_prompt_length": len(video_prompt),
        },
        "scope": "provider smoke; not P0 completion evidence",
        "steps": {},
    }
    if not settings.agnes_configured():
        report["error"] = "Agnes not configured"
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    client = AgnesHubClient(settings)
    img_adapter = get_flux_adapter()
    vid_adapter = get_kling_adapter()
    report["steps"]["adapter_image"] = type(img_adapter).__name__
    report["steps"]["adapter_video"] = type(vid_adapter).__name__

    # 0) List models (smoke auth)
    print("=== 0) GET /models ===")
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as hc:
            r = await hc.get(
                f"{settings.agnes_base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {key}"},
            )
        report["steps"]["models"] = {
            "http_status": r.status_code,
            "ok": r.status_code == 200,
        }
        print("models", report["steps"]["models"])
    except Exception as exc:
        report["steps"]["models"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print("models failed", report["steps"]["models"])

    # 1) Image via Adapter
    print("=== 1) Real image via get_flux_adapter() ===")
    img_create = await img_adapter.create({"prompt": image_prompt, "kind": "keyframe"})
    report["steps"]["image_create"] = {
        "status": img_create.get("status"),
        "remote_task_id": img_create.get("remote_task_id"),
        "error": img_create.get("error"),
    }
    print("create", {k: img_create.get(k) for k in ("status", "remote_task_id", "error")})
    rid = str(img_create.get("remote_task_id", ""))
    img_poll = await img_adapter.poll(rid)
    report["steps"]["image_poll"] = {
        "status": img_poll.get("status"),
        "artifact_uri": short_uri(img_poll.get("artifact_uri")),
    }
    print("poll", report["steps"]["image_poll"])
    img_cost = await img_adapter.fetch_cost(rid)
    report["steps"]["image_cost"] = img_cost
    print("cost", img_cost)

    # 2) Video create + poll
    print("=== 2) Real video via get_kling_adapter() ===")
    v_create = await vid_adapter.create(
        {
            "prompt": video_prompt,
            "kind": "video",
        }
    )
    report["steps"]["video_create"] = {
        "status": v_create.get("status"),
        "remote_task_id": v_create.get("remote_task_id"),
        "error": v_create.get("error"),
    }
    print("create", report["steps"]["video_create"])
    vrid = str(v_create.get("remote_task_id", ""))
    if v_create.get("status") not in {None, "failed"} and vrid:
        print("waiting for video task...")
        v_final = await client.wait_video(vrid, timeout_s=300.0, interval_s=4.0)
        uri = v_final.get("artifact_uri")
        report["steps"]["video_final"] = {
            "status": v_final.get("status"),
            "progress": v_final.get("progress"),
            "artifact_uri": short_uri(uri),
            "error": v_final.get("error"),
        }
        print("final", report["steps"]["video_final"])
    else:
        report["steps"]["video_final"] = {"status": "skipped", "reason": "create failed"}

    # 3) FirstFramePipeline with real Agnes image
    print("=== 3) FirstFramePipeline + real Agnes image ===")
    try:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.access.models import Organization, OrganizationMember, User  # noqa: F401
        from app.access.projects import ProjectService
        from app.events import models as _em  # noqa: F401
        from app.execution import models as _xm  # noqa: F401
        from app.execution.models import Artifact
        from app.execution.multi_shot import produce_shots, rework_subtitle_only
        from app.execution.pipeline import FirstFramePipeline
        from app.delivery.export_local import build_export_from_runs
        from app.production import models as _pm  # noqa: F401
        from app.providers.fake import FakeOpenAIAdapter
        from app.shared.base import Base
        from app.shared.enums import MemberRole
        from app.shared.model_registry import load_all_models
        from app.shared.security import hash_password

        load_all_models()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            user = User(
                email=f"e2e-{uuid4().hex[:8]}@local.test",
                display_name="E2E",
                password_hash=hash_password("password123"),
            )
            session.add(user)
            await session.flush()
            org = Organization(name="E2E-Org")
            session.add(org)
            await session.flush()
            session.add(
                OrganizationMember(
                    organization_id=org.id, user_id=user.id, role=MemberRole.OWNER.value
                )
            )
            project = await ProjectService(session).create_project(
                organization_id=org.id,
                name="E2E-Project",
                aspect_ratio="9:16",
                actor=user,
            )

            pipeline = FirstFramePipeline(
                session,
                openai=FakeOpenAIAdapter(),
                flux=AgnesImageAdapter(settings),
            )
            result = await pipeline.run(
                project_id=project.id,
                user_id=user.id,
                idea=idea,
                authorized_text=True,
                authorized_image=True,
                materialization_ops=["create_shot_stub", "enqueue_keyframe"],
                face_threshold=0.0,
            )
            art = await session.get(Artifact, result.artifact_id)
            report["steps"]["pipeline"] = {
                "status": "succeeded",
                "graph_id": str(result.graph_id),
                "node_run_id": str(result.node_run_id),
                "artifact_id": str(result.artifact_id),
                "object_key": short_uri(art.object_key if art else None),
                "face_review": result.face_review.status,
                "provider_ops": len(result.provider_operation_ids),
                "brief": result.brief_text[:80],
            }
            print("pipeline", report["steps"]["pipeline"])

            # 4) Multi-shot mock + subtitle rework + export (same project)
            print("=== 4) Multi-shot mock (10) + export on same project ===")
            from decimal import Decimal

            shots = await produce_shots(
                session, project_id=project.id, user_id=user.id, n=10
            )
            # rework first shot subtitle only
            if shots:
                await rework_subtitle_only(
                    session,
                    project_id=project.id,
                    user_id=user.id,
                    shot=shots[0],
                    new_subtitle="Reworked opening line",
                    budget=Decimal("100"),
                )
            export = await build_export_from_runs(
                session,
                project_id=project.id,
                shot_subtitles=[(str(s.shot_id), s.subtitle) for s in shots],
            )
            report["steps"]["multi_shot"] = {
                "status": "succeeded",
                "shot_count": len(shots),
                "all_review_passed": all(s.status == "review_passed" for s in shots),
            }
            report["steps"]["export"] = {
                "status": "succeeded",
                "export_id": str(export.export_id),
                "timeline_hash": export.timeline_hash,
                "srt_hash": export.srt_hash,
                "mp4_placeholder_key": export.mp4_placeholder_key,
                "source_artifact_count": len(export.source_artifact_ids),
                "note": "MP4 is placeholder; live FFmpeg not run in this smoke",
            }
            print("multi_shot", report["steps"]["multi_shot"])
            print("export", report["steps"]["export"])
        await engine.dispose()
    except Exception as exc:
        report["steps"]["pipeline"] = {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
        print("pipeline/downstream failed", report["steps"]["pipeline"])

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    img_ok = report["steps"].get("image_poll", {}).get("status") == "succeeded"
    vid_ok = report["steps"].get("video_final", {}).get("status") == "succeeded"
    pipe_ok = report["steps"].get("pipeline", {}).get("status") == "succeeded"
    multi_ok = report["steps"].get("multi_shot", {}).get("status") == "succeeded"
    export_ok = report["steps"].get("export", {}).get("status") == "succeeded"
    report["summary"] = {
        "image_ok": img_ok,
        "video_ok": vid_ok,
        "pipeline_ok": pipe_ok,
        "multi_shot_ok": multi_ok,
        "export_ok": export_ok,
        "full_flow_ok": all([img_ok, vid_ok, pipe_ok, multi_ok, export_ok]),
        "note": (
            "Real Agnes free-tier smoke: image+video+FirstFramePipeline. "
            "Multi-shot/export use local Graph/mock nodes (no 10x real video). "
            "Not P0 Gate complete (no Docker PG/RLS, live FFmpeg MP4, or 01§3.1)."
        ),
    }
    out = REPO / "tmp" / "provider-smoke" / "agnes_e2e_real.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    text = redact(text, key)
    out.write_text(text + "\n", encoding="utf-8")
    print("=== SUMMARY ===")
    print(text)
    print("wrote", out)
    return 0 if report["summary"]["full_flow_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
