"""Phase 10 P10-03/P10-04 audit on real PostgreSQL.

P10-03 Historical Project Migration Audit (plan 03 §90): seed an old-style
project through the legacy script import path plus characters/canonical
references, a production graph with NodeRun / ProviderOperation / Artifact, and
an Export; then verify the new Scene Workbench reads every entity
(script / scene / shot / character / canonical / node run / provider operation
/ artifact / export).

P10-04 No Guess Backfill Audit (plan 03 §91): a Shot with no formal result stays
NULL through workbench reads (no automatic formal guess), and
require_formal_keyframe fails closed with NO_FORMAL_KEYFRAME.
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import (
    Asset,
    Character,
    CharacterReference,
    Episode,
    Scene,
    ScriptDocument,
    Shot,
)
from app.assets.scene_service import SceneSummaryService
from app.assets.script_import import import_script
from app.delivery.models import Export, ExportItem
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.production.formal_selection import require_formal_keyframe, set_formal_video
from app.production.models import GraphVersion, ProductionGraph, definition_hash
from app.production.trace import build_execution_trace
from app.shared.db import set_rls_context
from app.shared.errors import ValidationAppError
from app.shared.security import hash_password
from app.workbench.scene_service import SceneWorkspaceService, ShotWorkbenchService
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_DEFAULT_URL = "postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge"


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", _DEFAULT_URL)


def _postgres_is_available() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 5432), timeout=1.0):
            pass
        sync_url = _database_url().replace(
            "postgresql+asyncpg://", "postgresql+psycopg://"
        )
        from sqlalchemy import create_engine

        engine = create_engine(sync_url, connect_args={"connect_timeout": 2})
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_PG_ENABLED") != "1" or not _postgres_is_available(),
    reason="set TEST_PG_ENABLED=1 with an explicitly configured PostgreSQL target",
)


@pytest.fixture
async def pg_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


_SCRIPT = """# Episode 1 - Historical Rain

Lead: Lin Xia

## Scene 1 - Street corner / night
Rainy street corner.

### Shot 1 - medium
Visual: Lin Xia turns at the corner, rain on her coat
Dialogue: I finally understand.
Camera: static

## Scene 2 - Old apartment / day
Old apartment interior.

### Shot 1 - close-up
Visual: A worn photo in her hand
Dialogue:
Camera: static
"""


async def _seed_historical_project(session: AsyncSession, suffix: str) -> dict[str, Any]:
    user = User(
        email=f"p10-migration-{suffix}@example.com",
        display_name="P10 migration owner",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"P10 migration {suffix}")
    session.add(workspace)
    await session.flush()
    await set_rls_context(session, user_id=user.id, workspace_id=workspace.id)
    project = Project(
        workspace_id=workspace.id,
        name=f"Historical project {suffix}",
        aspect_ratio="9:16",
        budget_limit=Decimal("0"),
    )
    session.add(project)
    await session.flush()
    await set_rls_context(
        session,
        user_id=user.id,
        workspace_id=workspace.id,
        project_id=project.id,
    )

    imported = await import_script(
        session,
        project_id=project.id,
        actor_id=user.id,
        filename=f"historical-{suffix}.md",
        text=_SCRIPT,
        actor=user,
    )
    assert imported.scene_count == 2
    assert imported.shot_count == 2

    lead_asset = Asset(
        project_id=project.id,
        kind="character",
        name="Lin Xia",
        description="Lead character Lin Xia",
        status="active",
        metadata_json={"role": "lead"},
    )
    session.add(lead_asset)
    await session.flush()
    lead = Character(
        id=lead_asset.id,
        locked_prompt="Lin Xia locked prompt",
        negative_prompt="",
        calibration_state="awaiting_visual_review",
    )
    session.add(lead)
    await session.flush()
    canonical = CharacterReference(
        character_id=lead.id,
        object_key=f"p10/{suffix}/canonical.png",
        reference_kind="canonical",
        is_canonical=True,
    )
    session.add(canonical)
    await session.flush()

    shot = await session.scalar(
        select(Shot)
        .join(Scene, Scene.id == Shot.scene_id)
        .join(Episode, Episode.id == Scene.episode_id)
        .where(Episode.project_id == project.id)
        .order_by(Shot.sort_order)
        .limit(1)
    )
    assert shot is not None

    artifact = Artifact(
        project_id=project.id,
        artifact_type="video",
        storage_state="available",
        object_key=f"p10/{suffix}/artifact.mp4",
        content_hash="f" * 64,
        mime_type="video/mp4",
        byte_size=1024,
        duration_seconds=Decimal("3.000"),
    )
    session.add(artifact)
    await session.flush()

    graph = ProductionGraph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=shot.id,
        template_key="p10-migration-audit",
        status="draft",
        created_by=user.id,
    )
    session.add(graph)
    await session.flush()
    version = GraphVersion(
        graph_id=graph.id,
        version_number=1,
        status="draft",
        definition={"nodes": []},
        definition_hash=definition_hash({"nodes": []}),
    )
    session.add(version)
    await session.flush()
    node = GraphNode(
        graph_version_id=version.id,
        node_key="video",
        node_type="video",
        display_name="Video",
    )
    session.add(node)
    await session.flush()
    run = NodeRun(
        project_id=project.id,
        graph_version_id=version.id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=f"p10-migration:{suffix}",
        input_hash="a" * 64,
        status="completed",
        input_snapshot={
            "workbench_plan": {
                "resolved_model": {
                    "resolved_model_id": f"agnes/{suffix}",
                    "source": "project_profile",
                    "status": "RESOLVED",
                }
            }
        },
        output_summary={"status": "completed"},
        result_artifact_id=artifact.id,
        created_by=user.id,
    )
    session.add(run)
    await session.flush()
    artifact.produced_by_run_id = run.id
    await session.flush()
    operation = ProviderOperation(
        node_run_id=run.id,
        attempt_no=1,
        purpose="primary",
        operation_kind="video.generate",
        actual_provider="agnes",
        actual_model=f"agnes/{suffix}",
        request_fingerprint="b" * 64,
    )
    session.add(operation)
    await session.flush()

    export = Export(
        project_id=project.id,
        format="timeline_json",
        status="completed",
        requested_by=user.id,
        manifest={"items": 1, "timeline_hash": "c" * 64},
    )
    session.add(export)
    await session.flush()
    session.add(
        ExportItem(
            export_id=export.id,
            ordinal=1,
            source_artifact_id=artifact.id,
            role="timeline",
            metadata_json={"kind": "timeline_json"},
        )
    )
    await session.flush()

    return {
        "user": user,
        "workspace": workspace,
        "project": project,
        "script_document_id": imported.script_document_id,
        "shot_id": shot.id,
        "run_id": run.id,
        "artifact_id": artifact.id,
        "export_id": export.id,
        "lead_id": lead.id,
        "canonical_id": canonical.id,
    }


@pytest.mark.asyncio
async def test_historical_project_readable_by_new_workbench_pg(pg_session: AsyncSession) -> None:
    """P10-03: every old project entity is readable through the new workbench."""
    suffix = uuid4().hex[:8]
    seed = await _seed_historical_project(pg_session, suffix)
    project = seed["project"]
    actor = seed["user"]
    await set_rls_context(
        pg_session,
        user_id=actor.id,
        workspace_id=seed["workspace"].id,
        project_id=project.id,
    )

    # script
    script = await pg_session.scalar(
        select(ScriptDocument).where(ScriptDocument.id == seed["script_document_id"])
    )
    assert script is not None and script.project_id == project.id

    # scenes via SceneSummaryService (new workbench API)
    summaries = await SceneSummaryService(pg_session).list_summaries(
        project_id=project.id, actor=actor
    )
    assert len(summaries) == 2
    assert {s["scene_number"] for s in summaries} == {1, 2}

    # scene workspace: shots + references
    scene = await pg_session.scalar(
        select(Scene)
        .join(Episode, Episode.id == Scene.episode_id)
        .where(Episode.project_id == project.id)
        .order_by(Scene.scene_number)
        .limit(1)
    )
    assert scene is not None
    workspace_read = await SceneWorkspaceService(pg_session).get_workspace(
        project_id=project.id, scene_id=scene.id, actor=actor
    )
    assert workspace_read["shots"]
    assert workspace_read["scene"]["id"] == scene.id

    # shot workbench: design state readable
    shot_workbench = await ShotWorkbenchService(pg_session).get_workbench(
        project_id=project.id, shot_id=seed["shot_id"], actor=actor
    )
    assert shot_workbench["shot"]["id"] == seed["shot_id"]

    # character + canonical reference
    lead = await pg_session.get(Character, seed["lead_id"])
    canonical = await pg_session.get(CharacterReference, seed["canonical_id"])
    assert lead is not None and canonical is not None
    assert canonical.character_id == lead.id

    # node run + provider operation + artifact via build_execution_trace
    trace = await build_execution_trace(
        pg_session, project_id=project.id, run_id=seed["run_id"]
    )
    assert trace.model_binding["resolved_model_id"] == f"agnes/{suffix}"
    assert trace.actual_provider == "agnes"
    assert trace.actual_model == f"agnes/{suffix}"
    assert trace.artifact is not None and trace.artifact["artifact_type"] == "video"
    artifact = await pg_session.get(Artifact, seed["artifact_id"])
    assert artifact is not None and artifact.artifact_type == "video"

    # export
    export = await pg_session.get(Export, seed["export_id"])
    assert export is not None and export.status == "completed"
    items = (
        await pg_session.execute(select(ExportItem).where(ExportItem.export_id == export.id))
    ).scalars().all()
    assert len(items) == 1


@pytest.mark.asyncio
async def test_no_guess_backfill_formal_results_stay_null_pg(pg_session: AsyncSession) -> None:
    """P10-04: no automatic formal keyframe/video backfill; NULL is allowed."""
    suffix = uuid4().hex[:8]
    seed = await _seed_historical_project(pg_session, suffix)
    project = seed["project"]
    actor = seed["user"]
    await set_rls_context(
        pg_session,
        user_id=actor.id,
        workspace_id=seed["workspace"].id,
        project_id=project.id,
    )

    shot = await pg_session.get(Shot, seed["shot_id"])
    assert shot is not None
    assert shot.formal_keyframe_artifact_id is None
    assert shot.formal_video_artifact_id is None

    # reading through the new workbench must not backfill
    scene = await pg_session.scalar(
        select(Scene)
        .join(Episode, Episode.id == Scene.episode_id)
        .where(Episode.project_id == project.id)
        .order_by(Scene.scene_number)
        .limit(1)
    )
    assert scene is not None
    await SceneWorkspaceService(pg_session).get_workspace(
        project_id=project.id, scene_id=scene.id, actor=actor
    )
    await pg_session.refresh(shot)
    assert shot.formal_keyframe_artifact_id is None
    assert shot.formal_video_artifact_id is None

    # explicit formal selection is the only way to set it
    artifact = await pg_session.get(Artifact, seed["artifact_id"])
    assert artifact is not None
    await set_formal_video(
        pg_session, project_id=project.id, shot_id=shot.id, artifact_id=artifact.id
    )
    await pg_session.flush()
    await pg_session.refresh(shot)
    assert shot.formal_video_artifact_id == artifact.id

    # fail closed without a formal keyframe
    with pytest.raises(ValidationAppError) as exc_info:
        await require_formal_keyframe(pg_session, project_id=project.id, shot_id=shot.id)
    assert exc_info.value.details.get("code") == "NO_FORMAL_KEYFRAME"
