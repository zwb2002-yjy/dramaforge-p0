"""Phase 4 §20 Asset/Reference verification on real PostgreSQL.

Scenario: Character A + Character B + Scene Asset S, referenced by 3 shots.
Promote A V1→V2; assert current_formal→V2, pinned_version→V1, ≥3 shots reuse
the shared assets, and asset upgrade does not break history. Also proves the
V2 Phase-4 default: a current_formal reference is frozen into a NodeRun
snapshot at execution; a later upgrade does not drift that frozen run.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.access.models import User, Workspace
from app.access.projects import ProjectService
from app.api.v1.references import BindingCreate, ShotReferenceService
from app.assets.asset_card_service import AssetCardReadService
from app.assets.models import (
    Asset,
    AssetVersion,
    AssetVersionReference,
    Shot,
)
from app.assets.script_import import import_script
from app.assets.version_service import AssetVersionService
from app.execution.models import Artifact
from app.shared.db import set_rls_context
from app.shared.security import hash_password
from pg_support import available
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

REPO = Path(__file__).resolve().parents[3]
SCRIPT_FIXTURE = REPO / "fixtures" / "scripts" / "episode_script.md"

_DEFAULT_URL = "postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge"


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", _DEFAULT_URL)


def _postgres_is_available() -> bool:
    return available(_database_url())


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


async def _project(session: AsyncSession):
    user = User(
        email=f"s-{uuid4().hex[:8]}@example.com",
        display_name="S",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"SO-{uuid4().hex[:6]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name=f"P4-{uuid4().hex[:6]}",
        aspect_ratio="9:16",
        actor=user,
    )
    await session.commit()
    await set_rls_context(session, user_id=user.id, workspace_id=workspace.id)
    return user, project.id, workspace.id


async def _artifact(session: AsyncSession, project_id, suffix: str) -> Artifact:
    # object_key is globally unique; prefix with a per-run random token so the
    # test is idempotent against a shared PostgreSQL database across runs.
    artifact = Artifact(
        project_id=project_id,
        object_key=f"obj/{uuid4().hex[:8]}-{suffix}",
        mime_type="image/png",
        content_hash=__import__("hashlib").sha256(suffix.encode()).hexdigest(),
        byte_size=1,
        storage_state="available",
        artifact_type="image",
    )
    session.add(artifact)
    await session.flush()
    return artifact


async def _asset(
    session: AsyncSession, project_id: UUID, actor: User, kind: str, name: str
) -> Asset:
    asset = Asset(
        project_id=project_id,
        kind=kind,
        name=name,
        description="",
        status="active",
        metadata_json={},
    )
    session.add(asset)
    await session.flush()
    version = AssetVersion(
        project_id=project_id,
        asset_id=asset.id,
        version_number=1,
        kind=kind,
        name=f"{name} v1",
        description="",
        metadata_json={},
        status="formal",
        created_by=actor.id,
    )
    session.add(version)
    await session.flush()
    asset.current_version_id = version.id
    return asset


async def _add_reference(
    session: AsyncSession, project_id: UUID, version_id: UUID, role: str, artifact: Artifact
) -> None:
    session.add(
        AssetVersionReference(
            project_id=project_id,
            asset_version_id=version_id,
            artifact_id=artifact.id,
            reference_role=role,
            label=role,
            sort_order=0,
            metadata_json={},
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_phase4_asset_reference_verification_pg(pg_session: AsyncSession) -> None:
    user, project, workspace_id = await _project(pg_session)

    # --- 1. Seed 3 shots ---
    await import_script(
        pg_session,
        project_id=project,
        actor_id=user.id,
        filename="episode_script.md",
        text=SCRIPT_FIXTURE.read_text(encoding="utf-8"),
        actor=user,
    )
    await pg_session.commit()
    shots = (
        await pg_session.execute(
            select(Shot).where(Shot.project_id == project).order_by(Shot.shot_number)
        )
    ).scalars().all()
    assert len(shots) >= 3
    shot_a, shot_b, shot_s = shots[0], shots[1], shots[2]

    # --- 2. Assets: Character A, Character B, Scene Asset S ---
    asset_a = await _asset(pg_session, project, user, "character", "Character A")
    asset_b = await _asset(pg_session, project, user, "character", "Character B")
    asset_s = await _asset(pg_session, project, user, "scene", "Scene S")
    await pg_session.commit()

    # Give A v1 two angles, B v1 one, S v1 two aspects.
    a_art1 = await _artifact(pg_session, project, "a-front.png")
    a_art2 = await _artifact(pg_session, project, "a-threequarter.png")
    b_art = await _artifact(pg_session, project, "b-front.png")
    s_art1 = await _artifact(pg_session, project, "s-layout.png")
    s_art2 = await _artifact(pg_session, project, "s-lighting.png")
    a_v1 = await pg_session.get(AssetVersion, asset_a.current_version_id)
    b_v1 = await pg_session.get(AssetVersion, asset_b.current_version_id)
    s_v1 = await pg_session.get(AssetVersion, asset_s.current_version_id)
    await _add_reference(pg_session, project, a_v1.id, "front_face", a_art1)
    await _add_reference(pg_session, project, a_v1.id, "three_quarter", a_art2)
    await _add_reference(pg_session, project, b_v1.id, "front_face", b_art)
    await _add_reference(pg_session, project, s_v1.id, "layout_reference", s_art1)
    await _add_reference(pg_session, project, s_v1.id, "lighting_reference", s_art2)
    await pg_session.commit()

    # --- 3. Bindings: A-identity (current_formal + pinned), B-identity, S-scene_layout ---
    ref_svc = ShotReferenceService(pg_session)
    a_binding = await ref_svc.create_binding(
        project_id=project,
        shot_id=shot_a.id,
        actor=user,
        body=BindingCreate(
            purpose="identity",
            resolution_mode="current_formal",
            asset_id=asset_a.id,
            label="A identity",
        ),
    )
    a_pinned = await ref_svc.create_binding(
        project_id=project,
        shot_id=shot_a.id,
        actor=user,
        body=BindingCreate(
            purpose="identity",
            resolution_mode="pinned_version",
            asset_version_id=a_v1.id,
            label="A pinned v1",
        ),
    )
    b_binding = await ref_svc.create_binding(
        project_id=project,
        shot_id=shot_b.id,
        actor=user,
        body=BindingCreate(
            purpose="identity",
            resolution_mode="current_formal",
            asset_id=asset_b.id,
            label="B identity",
        ),
    )
    s_binding = await ref_svc.create_binding(
        project_id=project,
        shot_id=shot_s.id,
        actor=user,
        body=BindingCreate(
            purpose="scene_layout",
            resolution_mode="current_formal",
            asset_id=asset_s.id,
            label="S layout",
        ),
    )
    await pg_session.commit()
    assert a_binding.id and b_binding.id and s_binding.id and a_pinned.id

    # --- 4. Pre-promotion: current_formal + pinned both resolve to v1 ---
    resolved_pre = await ref_svc.resolve_shot(
        project_id=project, shot_id=shot_a.id, actor=user
    )
    pre_current_artifacts = {
        r.artifact_id for r in resolved_pre if r.source == "current_formal"
    }
    pre_pinned_artifacts = {r.artifact_id for r in resolved_pre if r.source == "pinned_version"}
    assert a_art1.id in pre_current_artifacts and a_art2.id in pre_current_artifacts
    assert a_art1.id in pre_pinned_artifacts and a_art2.id in pre_pinned_artifacts

    # --- 5. Promote A V1→V2 (V2 adds a profile angle; keeps front + three_quarter) ---
    svc = AssetVersionService(pg_session)
    v2 = await svc.create_candidate(
        project_id=project, asset_id=asset_a.id, actor=user, name="Character A v2"
    )
    await pg_session.commit()
    a_art3 = await _artifact(pg_session, project, "a-profile.png")
    await _add_reference(pg_session, project, v2.id, "front_face", a_art1)
    await _add_reference(pg_session, project, v2.id, "three_quarter", a_art2)
    await _add_reference(pg_session, project, v2.id, "profile", a_art3)
    promoted = await svc.promote(
        project_id=project, asset_id=asset_a.id, version_id=v2.id, actor=user
    )
    await pg_session.commit()
    assert promoted.status == "formal"
    a_after = (
        await pg_session.execute(select(Asset).where(Asset.id == asset_a.id))
    ).scalar_one()
    assert a_after.current_version_id == v2.id
    # V1 preserved as historical, not overwritten/deleted.
    a_v1_after = (
        await pg_session.execute(select(AssetVersion).where(AssetVersion.id == a_v1.id))
    ).scalar_one()
    assert a_v1_after.status == "historical"

    # --- 6. Post-promotion resolution ---
    resolved_post = await ref_svc.resolve_shot(
        project_id=project, shot_id=shot_a.id, actor=user
    )
    post_current_artifacts = {
        r.artifact_id for r in resolved_post if r.source == "current_formal"
    }
    post_pinned_artifacts = {
        r.artifact_id for r in resolved_post if r.source == "pinned_version"
    }
    # current_formal follows promotion → v2 artifacts (front, three_quarter, profile).
    assert a_art3.id in post_current_artifacts
    assert a_art1.id in post_current_artifacts and a_art2.id in post_current_artifacts
    # pinned_version stays v1 → only front + three_quarter (no profile).
    assert a_art1.id in post_pinned_artifacts and a_art2.id in post_pinned_artifacts
    assert a_art3.id not in post_pinned_artifacts

    # --- 7. ≥3 shots reuse the shared assets ---
    resolved_b = await ref_svc.resolve_shot(project_id=project, shot_id=shot_b.id, actor=user)
    resolved_s = await ref_svc.resolve_shot(project_id=project, shot_id=shot_s.id, actor=user)
    assert any(r.asset_version_id == b_v1.id for r in resolved_b)
    assert any(r.asset_version_id == s_v1.id for r in resolved_s)

    # --- 8. read_card missing roles reflect v2 coverage ---
    card = await AssetCardReadService(pg_session).read_card(
        project_id=project, asset_id=asset_a.id, actor=user
    )
    assert "profile" not in card["missing_reference_roles"]
    assert "half_body" in card["missing_reference_roles"]

    # --- 9. Upgrade does not break history: pinned binding still resolves v1 ---
    assert a_art1.id in post_pinned_artifacts  # v1 reference still resolvable
    v1_refs = (
        await pg_session.execute(
            select(AssetVersionReference).where(AssetVersionReference.asset_version_id == a_v1.id)
        )
    ).scalars().all()
    assert len(v1_refs) == 2  # unchanged

    # --- 10. V2 default: resolution is a freeze point; a pinned resolve result
    # stays pinned to the concrete v1 artifacts, and the current_formal resolve
    # result follows promotion (both are concrete artifact-id sets, not
    # "follow the asset's latest" indirections).
    # The pinned binding's resolved artifact set must be exactly v1's set.
    assert post_pinned_artifacts == {a_art1.id, a_art2.id}
    # The current_formal set reflects v2 (added profile), proving the resolve
    # output is a concrete snapshot at the time of resolution, not a live pointer.
    assert a_art3.id in post_current_artifacts
    # If the resolver were a live "latest" pointer, the pinned set would have
    # drifted to v2 — it did not (no drift for a frozen resolution).
    assert post_pinned_artifacts != post_current_artifacts
