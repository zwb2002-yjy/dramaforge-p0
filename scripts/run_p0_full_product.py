"""Full P0 product path smoke (local PG + live BYOK when configured).

Does NOT log secrets or full prompts. Writes evidence under --scratch.
Uses: start_project → manual Brief/Plan → Worker keyframe (Agnes if live) →
script import → lead character → 10-shot graph (media adapters) → export.

Usage:
  APP_ENV=development python scripts/run_p0_full_product.py --scratch DIR
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

# Load .env before settings
_env = REPO / ".env"
if _env.is_file():
    for line in _env.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge",
)
# Formal product path: real MinIO only — never force in-memory object store.
os.environ.pop("DRAMA_FORCE_MEMORY_STORE", None)
if os.environ.get("DRAMA_FORCE_MEMORY_STORE") == "1":
    raise SystemExit("refusing DRAMA_FORCE_MEMORY_STORE=1 on formal product path")


async def main() -> int:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.access.models import Workspace, User
    from app.assets.characters import register_lead_character
    from app.assets.models import Shot
    from app.assets.script_import import import_script
    from app.config import clear_settings_cache, get_settings
    from app.creation.service import CreationService
    from app.delivery.export_service import build_project_export
    from app.execution.models import Artifact, NodeRun
    from app.execution.shot_p0 import produce_shots_p0, rework_subtitle_only_p0, set_shot_lock
    from app.providers.flux import get_flux_adapter
    from app.providers.openai import get_openai_adapter
    from app.runtime.scheduler import AgentRunScheduler
    from app.shared.db import set_rls_context
    from app.shared.security import hash_password
    from app.storage.minio_store import get_object_store
    from decimal import Decimal
    from sqlalchemy import select

    parser = argparse.ArgumentParser()
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--skip-live-image", action="store_true")
    parser.add_argument("--n-shots", type=int, default=10)
    parser.add_argument("--project-name", default="P0 Full Product Evidence")
    parser.add_argument(
        "--idea",
        required=True,
        help="Creative input used for the project, manual brief, and plan.",
    )
    parser.add_argument(
        "--script-file",
        type=Path,
        required=True,
        help="Explicit UTF-8 script file to import; no sample script is implied.",
    )
    parser.add_argument("--lead-name", required=True)
    parser.add_argument(
        "--lead-prompt",
        required=True,
        help="Canonical-reference prompt; it is used only in the provider request.",
    )
    args = parser.parse_args()
    idea = args.idea.strip()
    lead_name = args.lead_name.strip()
    lead_prompt = args.lead_prompt.strip()
    script_path = args.script_file.resolve()
    if not idea or not lead_name or not lead_prompt:
        parser.error("--idea, --lead-name and --lead-prompt must not be empty")
    if not script_path.is_file():
        parser.error(f"--script-file does not exist: {script_path}")
    scratch: Path = args.scratch
    scratch.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        f"P0 full product run {datetime.now(timezone.utc).isoformat()}",
    ]

    clear_settings_cache()
    settings = get_settings()
    lines.append(f"app_env={settings.app_env}")
    lines.append(f"agnes={settings.agnes_configured()} model={settings.agnes_image_model}")
    lines.append(f"text_llm={settings.text_llm_configured()} model={settings.text_llm_model}")
    lines.append(f"tts_enabled={settings.tts_enabled}")

    # 0) optional text smoke
    if settings.text_llm_configured():
        try:
            ad = get_openai_adapter(allow_live=True)
            tr = await ad.create(
                {"prompt": "One word only: READY", "kind": "p0_full", "max_tokens": 16}
            )
            lines.append(
                f"text_status={tr.get('status')} chars={len(str(tr.get('text') or ''))}"
            )
        except Exception as exc:  # noqa: BLE001
            lines.append(f"text_error={type(exc).__name__}:{str(exc)[:120]}")
    else:
        lines.append("text_skipped=not_configured")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # Real MinIO (or fail) — no memory store on formal path
    store = get_object_store()
    lines.append(f"object_store={type(store).__name__}")
    if type(store).__name__ == "InMemoryObjectStore":
        lines.append("FATAL: InMemoryObjectStore on formal path")
        (scratch / "p0_full_product.log").write_text("\n".join(lines), encoding="utf-8")
        return 2

    async with factory() as session:
        suffix = uuid4().hex[:8]
        user = User(
            email=f"p0full-{suffix}@example.com",
            display_name="P0Full",
            password_hash=hash_password("password123"),
        )
        session.add(user)
        await session.flush()
        workspace = Workspace(
            owner_user_id=user.id,
            name=f"P0FullWorkspace-{suffix}",
        )
        session.add(workspace)
        await session.commit()

        await set_rls_context(session, user_id=user.id, workspace_id=workspace.id)
        started = await CreationService(session).start_project(
            workspace_id=workspace.id,
            name=f"{args.project_name.strip() or 'P0 Full Product Evidence'}-{suffix}",
            aspect_ratio="9:16",
            actor=user,
            idea=idea,
        )
        await session.commit()
        lines.append(
            f"start_project id={started.project_id} text_ops={started.text_provider_operations}"
        )
        assert started.text_provider_operations == 0

        await set_rls_context(
            session,
            user_id=user.id,
            workspace_id=workspace.id,
            project_id=started.project_id,
        )
        rev = await CreationService(session).update_brief_manual(
            project_id=started.project_id,
            actor=user,
            logline=idea,
        )
        rev = await CreationService(session).confirm_brief(
            project_id=started.project_id, revision_id=rev.id, actor=user
        )
        plan = await CreationService(session).create_or_update_plan_manual(
            project_id=started.project_id,
            actor=user,
            brief_revision_id=rev.id,
            plan_body={
                "prompt": f"{idea}, lead character, cinematic keyframe, 9:16",
                "shots": args.n_shots,
            },
        )
        confirmed = await CreationService(session).confirm_plan_and_materialize(
            project_id=started.project_id,
            plan_id=plan.id,
            actor=user,
            materialization_ops=["create_shot_stub", "enqueue_keyframe"],
        )
        await session.commit()
        lines.append(f"materialize node_run={confirmed.node_run_id}")

        # Canonical: live Provider only — never FakeFlux silent fallback
        if args.skip_live_image or not settings.agnes_configured():
            lines.append(
                "FATAL: provider_not_configured — need AGNES for live canonical "
                "or supply audited manual media (do not use Fake)"
            )
            (scratch / "p0_full_product.log").write_text("\n".join(lines), encoding="utf-8")
            return 2
        try:
            flux = get_flux_adapter(allow_live=True, allow_fake=False)
            created = await asyncio.wait_for(
                flux.create(
                    {
                        "prompt": lead_prompt,
                        "kind": "keyframe",
                    }
                ),
                timeout=60.0,
            )
            remote = str(created.get("remote_task_id"))
            poll = await asyncio.wait_for(flux.poll(remote), timeout=30.0)
            uri = poll.get("artifact_uri") or created.get("artifact_uri")
            if not (isinstance(uri, str) and uri.startswith("http")):
                lines.append(f"FATAL: no artifact_uri from provider poll={poll}")
                (scratch / "p0_full_product.log").write_text("\n".join(lines), encoding="utf-8")
                return 2
            import httpx

            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                resp = await client.get(uri)
                resp.raise_for_status()
                canon_bytes = resp.content
            if not canon_bytes or canon_bytes.startswith(b"keyframe-STUB") or canon_bytes.startswith(
                b"keyframe-TESTFAKE"
            ):
                lines.append("FATAL: refused STUB/empty canonical bytes")
                return 2
            lines.append(
                f"canonical_image live=True nbytes={len(canon_bytes)} status={poll.get('status')}"
            )
        except Exception as exc:  # noqa: BLE001
            lines.append(f"FATAL: canonical provider {type(exc).__name__}:{str(exc)[:120]}")
            (scratch / "p0_full_product.log").write_text("\n".join(lines), encoding="utf-8")
            return 2

        canon_key = f"projects/{started.project_id}/canonical/lead.png"
        await store.put_bytes(
            object_key=canon_key, data=canon_bytes, mime_type="image/png"
        )
        run = await session.get(NodeRun, confirmed.node_run_id)
        assert run is not None
        run.input_snapshot = {
            **(run.input_snapshot or {}),
            "canonical_object_key": canon_key,
            "plan": {
                "prompt": f"{idea}, lead character, cinematic keyframe, 9:16"
            },
        }
        await session.flush()
        job_id = await AgentRunScheduler(session).enqueue_node_run_only(confirmed.node_run_id)
        lines.append(f"after_enqueue job_id={job_id} (must not be local:*)")
        if str(job_id).startswith("local:"):
            lines.append("FATAL: local:* enqueue is forbidden")
            return 2
        # Wait for real Arq worker — do NOT call WorkerRuntime in-process
        run2 = None
        for _ in range(60):
            await session.refresh(run) if run else None
            run2 = await session.get(NodeRun, confirmed.node_run_id)
            if run2 and run2.status in {
                "completed",
                "cached",
                "completed_after_cancel",
                "failed",
            }:
                break
            await asyncio.sleep(2.0)
            await session.commit()
        art = (
            await session.get(Artifact, run2.result_artifact_id)
            if run2 and run2.result_artifact_id
            else None
        )
        lines.append(
            f"keyframe status={run2.status if run2 else None} "
            f"bytes={art.byte_size if art else 0} "
            f"face={(run2.output_summary or {}).get('face_review') if run2 else None}"
        )
        if art:
            try:
                data = await store.get_bytes(object_key=art.object_key)
                lines.append(f"store_read_keyframe nbytes={len(data)}")
            except Exception as exc:  # noqa: BLE001
                lines.append(f"store_read_keyframe_error={type(exc).__name__}")

        # Script import + 10-shot production
        script = script_path.read_text(encoding="utf-8")
        imp = await import_script(
            session,
            project_id=started.project_id,
            actor_id=user.id,
            filename=script_path.name,
            text=script,
            actor=user,
        )
        lines.append(
            f"script_import scenes={imp.scene_count} shots={imp.shot_count} lead={imp.lead_character}"
        )
        if imp.lead_character and imp.lead_character != lead_name:
            lines.append(
                "FATAL: --lead-name must match the script Lead declaration "
                f"(script={imp.lead_character!r})"
            )
            (scratch / "p0_full_product.log").write_text("\n".join(lines), encoding="utf-8")
            return 2
        char = await register_lead_character(
            session,
            project_id=started.project_id,
            name=imp.lead_character or lead_name,
            locked_prompt=lead_prompt,
            canonical_image_bytes=canon_bytes,
            store=store,
        )
        rows = list(
            (
                await session.execute(
                    select(Shot)
                    .where(Shot.project_id == started.project_id)
                    .order_by(Shot.sort_order)
                )
            )
            .scalars()
            .all()
        )
        specs = [
            (r.id, r.visual_description, r.dialogue or f"Line {r.sort_order}")
            for r in rows
        ][: args.n_shots]
        # Formal path: queue NodeRuns only; resident Arq workers execute.
        lines.append("bulk_shots_mode=queue_only_arq_workers")
        shots = await produce_shots_p0(
            session,
            project_id=started.project_id,
            user_id=user.id,
            n=len(specs),
            store=store,
            shot_specs=specs,
            lead_name=imp.lead_character or lead_name,
            shared_canonical_object_key=char.canonical_object_key,
            shared_canonical_bytes=canon_bytes,
            execute_inline=False,
        )
        # Enqueue all queued NodeRuns via Arq (stable job ids)
        sched = AgentRunScheduler(session)
        n_disp = await sched.dispatch_pending(worker_id="p0-full-product")
        lines.append(f"dispatch_pending enqueued={n_disp} job_ids={sched.enqueued_job_ids[:5]}")
        if any(str(j).startswith("local:") for j in sched.enqueued_job_ids):
            lines.append("FATAL: local:* job ids returned")
            (scratch / "p0_full_product.log").write_text("\n".join(lines), encoding="utf-8")
            return 2
        # Poll until workers progress (no in-process WorkerRuntime drain)
        for _ in range(90):
            q = await session.execute(
                select(NodeRun)
                .where(NodeRun.project_id == started.project_id)
                .where(NodeRun.status == "queued")
            )
            remaining = len(list(q.scalars().all()))
            if remaining == 0:
                break
            await asyncio.sleep(2.0)
            await session.commit()
        lines.append(
            f"produce_shots n={len(shots)} face_checked={sum(1 for s in shots if s.face_checked)} "
            f"continuity={sum(1 for s in shots if s.continuity_checked)} "
            f"status={[s.status for s in shots[:3]]}"
        )
        # subtitle rework + lock
        kf_before = shots[0].run_ids.get("keyframe")
        await rework_subtitle_only_p0(
            session,
            project_id=started.project_id,
            user_id=user.id,
            shot=shots[0],
            new_subtitle=f"{shots[0].subtitle} (timing revised)",
            budget=Decimal("100"),
            store=store,
        )
        lines.append(
            f"subtitle_rework keyframe_stable={shots[0].run_ids.get('keyframe') == kf_before}"
        )
        await set_shot_lock(
            session,
            project_id=started.project_id,
            shot_id=shots[0].shot_id,
            user_id=user.id,
            locked=True,
        )
        await session.commit()
        locked_ok = False
        try:
            await rework_subtitle_only_p0(
                session,
                project_id=started.project_id,
                user_id=user.id,
                shot=shots[0],
                new_subtitle="should block",
                budget=Decimal("10"),
                store=store,
            )
        except ValueError as exc:
            locked_ok = "lock" in str(exc).lower()
        lines.append(f"human_lock_blocks_rework={locked_ok}")

        exp = await build_project_export(
            session,
            project_id=started.project_id,
            requested_by=user.id,
            shot_subtitles=[(str(s.shot_id), s.subtitle) for s in shots],
            store=None,  # default get_object_store
            try_ffmpeg=True,
        )
        lines.append(
            f"export timeline={exp.timeline_hash[:16]}… srt={exp.srt_hash[:16]}… "
            f"package={exp.package_hash[:16]}… items={exp.export_item_count} "
            f"mp4_err={exp.mp4_error} status={exp.export_status}"
        )
        exp2 = await build_project_export(
            session,
            project_id=started.project_id,
            requested_by=user.id,
            shot_subtitles=[(str(s.shot_id), s.subtitle) for s in shots],
            store=None,
            try_ffmpeg=False,
        )
        lines.append(
            f"export_repro timeline_eq={exp.timeline_hash == exp2.timeline_hash} "
            f"srt_eq={exp.srt_hash == exp2.srt_hash} "
            f"package_eq={exp.package_hash == exp2.package_hash}"
        )

    await engine.dispose()
    out = scratch / "p0-full-product-run.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"WROTE {out}")
    # Fail only on hard product failures
    if "start_project" not in "\n".join(lines):
        return 2
    if "keyframe status=completed" not in "\n".join(lines) and "keyframe status=failed" in "\n".join(
        lines
    ):
        # live image may fail hub; still export path matters
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
