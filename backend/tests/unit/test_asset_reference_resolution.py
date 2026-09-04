"""P2-06 @Asset resolution: current_formal chain, pinned_version, rename resilience."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.access.models import Project, User, Workspace
from app.api.v1.references import BindingCreate, ShotReferenceService
from app.assets.models import (
    Asset,
    AssetVersion,
    AssetVersionReference,
    Episode,
    Scene,
    Shot,
)
from app.assets.version_service import AssetVersionService
from app.execution.models import Artifact
from app.shared.base import Base
from app.shared.enums import ProjectStage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


async def _make_env() -> tuple[object, AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory()


async def _seed_project(session: AsyncSession) -> tuple[User, Project, Shot]:
    user = User(
        email=f"resolve-{uuid4().hex}@example.com",
        display_name="Owner",
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name="W")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="P",
        stage=ProjectStage.DRAFT.value,
        aspect_ratio="16:9",
        target_platform="general",
        style_bible={},
        budget_limit=Decimal("0"),
        budget_currency="USD",
        provider_dispatch_frozen=False,
    )
    session.add(project)
    await session.flush()
    episode = Episode(project_id=project.id, episode_number=1, title="E1", synopsis="")
    session.add(episode)
    await session.flush()
    scene = Scene(
        episode_id=episode.id,
        scene_number=1,
        location_name="Studio",
        time_of_day="day",
        synopsis="",
    )
    session.add(scene)
    await session.flush()
    shot = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=1,
        shot_type="medium",
        camera_move="static",
        visual_description="turn",
        dialogue="",
        status="draft",
        sort_order=1,
    )
    session.add(shot)
    await session.flush()
    return user, project, shot


async def _seed_character_with_artifacts(
    session: AsyncSession,
    *,
    project_id,
    user,
    name: str,
) -> tuple[Asset, AssetVersion, list[Artifact]]:
    artifact_a = Artifact(
        project_id=project_id,
        artifact_type="image",
        object_key=f"tmp/{uuid4().hex}.png",
        content_hash=uuid4().hex * 2,
        mime_type="image/png",
    )
    artifact_b = Artifact(
        project_id=project_id,
        artifact_type="image",
        object_key=f"tmp/{uuid4().hex}.png",
        content_hash=uuid4().hex * 2,
        mime_type="image/png",
    )
    session.add_all([artifact_a, artifact_b])
    await session.flush()
    asset = Asset(
        project_id=project_id,
        kind="character",
        name=name,
        description="",
        status="active",
        version=1,
    )
    session.add(asset)
    await session.flush()
    version = AssetVersion(
        project_id=project_id,
        asset_id=asset.id,
        version_number=1,
        kind="character",
        name=name,
        description="",
        status="formal",
        created_by=user.id,
    )
    session.add(version)
    await session.flush()
    asset.current_version_id = version.id
    session.add_all(
        [
            AssetVersionReference(
                project_id=project_id,
                asset_version_id=version.id,
                artifact_id=artifact_a.id,
                reference_role="front_face",
                label="front",
                sort_order=0,
            ),
            AssetVersionReference(
                project_id=project_id,
                asset_version_id=version.id,
                artifact_id=artifact_b.id,
                reference_role="primary",
                label="primary",
                sort_order=1,
            ),
        ]
    )
    await session.flush()
    return asset, version, [artifact_a, artifact_b]


async def test_current_formal_and_pinned_version_resolution() -> None:
    engine, session = await _make_env()
    try:
        user, project, shot = await _seed_project(session)
        asset, version_v1, artifacts = await _seed_character_with_artifacts(
            session, project_id=project.id, user=user, name="林墨"
        )
        service = ShotReferenceService(session)
        await service.create_binding(
            project_id=project.id,
            shot_id=shot.id,
            actor=user,
            body=BindingCreate(
                purpose="identity",
                asset_id=asset.id,
                resolution_mode="current_formal",
                label="@林墨",
            ),
        )
        await service.create_binding(
            project_id=project.id,
            shot_id=shot.id,
            actor=user,
            body=BindingCreate(
                purpose="style",
                asset_id=asset.id,
                asset_version_id=version_v1.id,
                resolution_mode="pinned_version",
                label="pinned v1",
            ),
        )
        await session.flush()

        resolved = await service.resolve_shot(
            project_id=project.id, shot_id=shot.id, actor=user
        )
        assert len(resolved) == 4  # 2 per binding, same v1 artifacts
        artifact_ids = {item.artifact_id for item in resolved}
        assert artifact_ids == {artifacts[0].id, artifacts[1].id}

        # Promote a new candidate without references: current_formal now resolves
        # to nothing, but the pinned v1 binding keeps the old artifacts.
        candidate = await AssetVersionService(session).create_candidate(
            project_id=project.id, asset_id=asset.id, actor=user, name="林墨·成年"
        )
        await AssetVersionService(session).promote(
            project_id=project.id,
            asset_id=asset.id,
            version_id=candidate.id,
            actor=user,
        )
        await session.flush()

        resolved_after = await service.resolve_shot(
            project_id=project.id, shot_id=shot.id, actor=user
        )
        # current_formal binding resolved to the promoted v2 (no references) ->
        # contributes none; pinned v1 still contributes its two artifacts.
        assert len(resolved_after) == 2
        assert {item.artifact_id for item in resolved_after} == {
            artifacts[0].id,
            artifacts[1].id,
        }
        assert all(item.source == "pinned_version" for item in resolved_after)
    finally:
        await session.close()
        await engine.dispose()  # type: ignore[union-attr]


async def test_asset_rename_does_not_break_binding() -> None:
    engine, session = await _make_env()
    try:
        user, project, shot = await _seed_project(session)
        asset, _version, artifacts = await _seed_character_with_artifacts(
            session, project_id=project.id, user=user, name="林墨"
        )
        service = ShotReferenceService(session)
        await service.create_binding(
            project_id=project.id,
            shot_id=shot.id,
            actor=user,
            body=BindingCreate(
                purpose="identity",
                asset_id=asset.id,
                resolution_mode="current_formal",
                label="@林墨",
            ),
        )
        await session.flush()

        # Rename the asset: the binding stores the UUID, not the prompt text.
        asset.name = "林墨·成年"
        await session.flush()
        resolved = await service.resolve_shot(
            project_id=project.id, shot_id=shot.id, actor=user
        )
        assert len(resolved) == 2
        assert {item.artifact_id for item in resolved} == {
            artifacts[0].id,
            artifacts[1].id,
        }
    finally:
        await session.close()
        await engine.dispose()  # type: ignore[union-attr]
