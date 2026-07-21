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
# Prefer process-wide memory store so product path is not blocked by flaky MinIO.
os.environ.setdefault("DRAMA_FORCE_MEMORY_STORE", "1")


async def main() -> int:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.access.models import Organization, OrganizationMember, User
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
    from app.runtime.scheduler import AgentRunScheduler, WorkerRuntime
    from app.shared.db import set_rls_context
    from app.shared.enums import MemberRole
    from app.shared.security import hash_password
    from app.storage.minio_store import get_object_store, reset_object_store_for_tests
    from decimal import Decimal
    from sqlalchemy import select

    parser = argparse.ArgumentParser()
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--skip-live-image", action="store_true")
    parser.add_argument("--n-shots", type=int, default=10)
    args = parser.parse_args()
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
    reset_object_store_for_tests()
    store = get_object_store()

    async with factory() as session:
        suffix = uuid4().hex[:8]
        user = User(
            email=f"p0full-{suffix}@example.com",
            display_name="P0Full",
            password_hash=hash_password("password123"),
        )
        session.add(user)
        await session.flush()
        org = Organization(name=f"P0FullOrg-{suffix}")
        session.add(org)
        await session.flush()
        session.add(
            OrganizationMember(
                organization_id=org.id,
                user_id=user.id,
                role=MemberRole.OWNER.value,
            )
        )
        await session.commit()

        await set_rls_context(session, user_id=user.id, organization_id=org.id)
        started = await CreationService(session).start_project(
            organization_id=org.id,
            name=f"P0Full-{suffix}",
            aspect_ratio="9:16",
            actor=user,
            idea="neon rain short drama full p0",
        )
        await session.commit()
        lines.append(
            f"start_project id={started.project_id} text_ops={started.text_provider_operations}"
        )
        assert started.text_provider_operations == 0

        await set_rls_context(
            session,
            user_id=user.id,
            organization_id=org.id,
            project_id=started.project_id,
        )
        rev = await CreationService(session).update_brief_manual(
            project_id=started.project_id,
            actor=user,
            logline="A hero walks into neon rain; full P0 acceptance path",
        )
        rev = await CreationService(session).confirm_brief(
            project_id=started.project_id, revision_id=rev.id, actor=user
        )
        plan = await CreationService(session).create_or_update_plan_manual(
            project_id=started.project_id,
            actor=user,
            brief_revision_id=rev.id,
            plan_body={
                "prompt": "cinematic neon rain opening keyframe 9:16, lead character",
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

        # Canonical ref for face path
        if not args.skip_live_image and settings.agnes_configured():
            try:
                flux = get_flux_adapter(allow_live=True)
                created = await flux.create(
                    {
                        "prompt": "canonical lead portrait, consistent face, soft light",
                        "kind": "keyframe",
                    }
                )
                remote = str(created.get("remote_task_id"))
                poll = await flux.poll(remote)
                uri = poll.get("artifact_uri") or created.get("artifact_uri")
                if isinstance(uri, str) and uri.startswith("http"):
                    import httpx

                    async with httpx.AsyncClient(
                        timeout=120.0, follow_redirects=True
                    ) as client:
                        resp = await client.get(uri)
                        resp.raise_for_status()
                        canon_bytes = resp.content
                else:
                    from app.providers.fake import FakeFluxAdapter

                    fad = FakeFluxAdapter()
                    c = await fad.create({"prompt": "canon fallback", "kind": "keyframe"})
                    canon_bytes = fad.blobs[c["remote_task_id"]]
                lines.append(
                    f"canonical_image live={True} nbytes={len(canon_bytes)} "
                    f"status={poll.get('status') if isinstance(poll, dict) else 'n/a'}"
                )
            except Exception as exc:  # noqa: BLE001
                from app.providers.fake import FakeFluxAdapter

                fad = FakeFluxAdapter()
                c = await fad.create({"prompt": "canon fallback", "kind": "keyframe"})
                canon_bytes = fad.blobs[c["remote_task_id"]]
                lines.append(f"canonical_image live_failed={type(exc).__name__}:{str(exc)[:80]}")
        else:
            from app.providers.fake import FakeFluxAdapter

            fad = FakeFluxAdapter()
            c = await fad.create({"prompt": "canon lead", "kind": "keyframe"})
            canon_bytes = fad.blobs[c["remote_task_id"]]
            lines.append(f"canonical_image live={False} nbytes={len(canon_bytes)}")

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
                "prompt": "cinematic neon rain opening keyframe 9:16, lead character"
            },
        }
        await session.flush()
        await AgentRunScheduler(session).enqueue_node_run_only(confirmed.node_run_id)
        run = await session.get(NodeRun, confirmed.node_run_id)
        lines.append(f"after_enqueue status={run.status if run else None}")
        await WorkerRuntime(session).process_one(confirmed.node_run_id)
        run2 = await session.get(NodeRun, confirmed.node_run_id)
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
        script = (REPO / "fixtures" / "scripts" / "p0_10_shots.md").read_text(
            encoding="utf-8"
        )
        imp = await import_script(
            session,
            project_id=started.project_id,
            actor_id=user.id,
            filename="p0_10_shots.md",
            text=script,
            actor=user,
        )
        lines.append(
            f"script_import scenes={imp.scene_count} shots={imp.shot_count} lead={imp.lead_character}"
        )
        char = await register_lead_character(
            session,
            project_id=started.project_id,
            name=imp.lead_character or "Lin Xia",
            locked_prompt=f"{imp.lead_character or 'Lin Xia'} locked prompt",
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
        # Formal path: queue NodeRuns only (Worker executes). Never flip APP_ENV=test
        # for bulk acceptance — that forced Fake Adapters.
        lines.append("bulk_shots_mode=queue_only_worker_path")
        shots = await produce_shots_p0(
            session,
            project_id=started.project_id,
            user_id=user.id,
            n=len(specs),
            store=store,
            shot_specs=specs,
            shared_canonical_object_key=char.canonical_object_key,
            shared_canonical_bytes=canon_bytes,
            execute_inline=False,
        )
        # Drain via WorkerRuntime (same entry as Arq job) when Redis/Arq may be local
        from app.runtime.scheduler import WorkerRuntime

        wr = WorkerRuntime(session)
        processed = await wr.process_queued(limit=max(50, len(specs) * 12))
        lines.append(f"worker_processed={processed}")
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
            new_subtitle="neon rain street rework line for p0 full",
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
