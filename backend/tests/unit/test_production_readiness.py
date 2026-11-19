"""Work-type production readiness read model (I8b-01)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.production.readiness import read_production_readiness
from app.providers.model_profiles.service import ProductionModelProfileService
from app.providers.models import ProviderModelBinding
from model_infra_fixture import seed_model_infra
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _project(session: AsyncSession, *, work_type: str, planned: int | None):
    suffix = uuid4().hex[:8]
    user = User(email=f"ready-{suffix}@example.com", display_name="R", password_hash="x")
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{suffix}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name=f"P-{suffix}",
        aspect_ratio="9:16",
        budget_limit=0,
        work_type=work_type,
        planned_episode_count=planned,
    )
    session.add(project)
    await session.flush()
    return project, user


async def _configure_media(session: AsyncSession, project: Project, user: User) -> None:
    await seed_model_infra(session, project=project, user=user)
    profile = await ProductionModelProfileService(session).get_project_profile(
        project_id=project.id
    )
    assert profile is not None
    image = await session.scalar(
        select(ProviderModelBinding).where(
            ProviderModelBinding.workspace_id == project.workspace_id,
            ProviderModelBinding.media_type == "image",
        )
    )
    video = await session.scalar(
        select(ProviderModelBinding).where(
            ProviderModelBinding.workspace_id == project.workspace_id,
            ProviderModelBinding.media_type == "video",
        )
    )
    assert image is not None and video is not None
    profile.image_model_binding_id = image.id
    profile.video_model_binding_id = video.id
    await session.flush()


async def _story(session: AsyncSession, project: Project, *, shots: int = 1) -> None:
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
    for index in range(shots):
        session.add(
            Shot(
                project_id=project.id,
                scene_id=scene.id,
                shot_number=index + 1,
                sort_order=index + 1,
                shot_type="wide",
                camera_move="static",
                status="draft",
                visual_description="",
                dialogue="",
                duration_seconds=5,
                image_prompt="",
                video_prompt="",
            )
        )
    await session.flush()


@pytest.mark.asyncio
async def test_single_comic_with_story_and_media_is_ready(session: AsyncSession) -> None:
    project, user = await _project(session, work_type="single_comic", planned=1)
    await _configure_media(session, project, user)
    await _story(session, project)
    readiness = await read_production_readiness(session, project_id=project.id)
    assert readiness.work_type == "single_comic"
    assert readiness.episode_count == 1
    assert readiness.scene_count == 1
    assert readiness.shot_count == 1
    assert readiness.image_binding_configured is True
    assert readiness.video_binding_configured is True
    assert readiness.voice_binding_configured is False
    assert readiness.blockers == []
    assert readiness.ready is True
    assert {item.key for item in readiness.items} == {
        "story_structure",
        "scenes",
        "shots",
        "media_defaults",
        "cross_episode_sharing",
        "formal_media",
    }


@pytest.mark.asyncio
async def test_missing_story_or_media_blocks_readiness(session: AsyncSession) -> None:
    project, _user = await _project(session, work_type="single_comic", planned=1)
    empty = await read_production_readiness(session, project_id=project.id)
    assert empty.ready is False
    assert "story_structure" in empty.blockers
    assert "scenes" in empty.blockers
    assert "media_defaults" in empty.blockers

    serial, user = await _project(session, work_type="serial_comic", planned=3)
    await _configure_media(session, serial, user)
    await _story(session, serial)
    partial = await read_production_readiness(session, project_id=serial.id)
    structure = next(item for item in partial.items if item.key == "story_structure")
    assert structure.status == "partial"
    assert "story_structure" in partial.blockers


@pytest.mark.asyncio
async def test_serial_comic_with_two_episodes_is_ready(session: AsyncSession) -> None:
    project, user = await _project(session, work_type="serial_comic", planned=2)
    await _configure_media(session, project, user)
    for episode_number in (1, 2):
        episode = Episode(
            project_id=project.id,
            episode_number=episode_number,
            title=f"E{episode_number}",
            synopsis="",
        )
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
        session.add(
            Shot(
                project_id=project.id,
                scene_id=scene.id,
                shot_number=1,
                sort_order=1,
                shot_type="wide",
                camera_move="static",
                status="draft",
                visual_description="",
                dialogue="",
                duration_seconds=5,
                image_prompt="",
                video_prompt="",
            )
        )
    await session.flush()
    readiness = await read_production_readiness(session, project_id=project.id)
    assert readiness.episode_count == 2
    assert readiness.scene_count == 2
    assert readiness.shot_count == 2
    structure = next(item for item in readiness.items if item.key == "story_structure")
    assert structure.status == "ready"
    assert readiness.ready is True


@pytest.mark.asyncio
async def test_shared_asset_across_episodes_is_reported(session: AsyncSession) -> None:
    from app.assets.models import Asset, AssetVersion
    from app.production.models import ShotReferenceBinding

    project, user = await _project(session, work_type="serial_comic", planned=2)
    await _configure_media(session, project, user)
    shots = []
    for episode_number in (1, 2):
        episode = Episode(
            project_id=project.id,
            episode_number=episode_number,
            title=f"E{episode_number}",
            synopsis="",
        )
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
            sort_order=1,
            shot_type="wide",
            camera_move="static",
            status="draft",
            visual_description="",
            dialogue="",
            duration_seconds=5,
            image_prompt="",
            video_prompt="",
        )
        session.add(shot)
        shots.append(shot)
    await session.flush()
    asset = Asset(project_id=project.id, kind="character", name="Hero", version=1)
    session.add(asset)
    await session.flush()
    version = AssetVersion(
        project_id=project.id,
        asset_id=asset.id,
        version_number=1,
        kind="character",
        name="Hero",
        description="",
        metadata_json={},
        status="candidate",
        created_by=user.id,
    )
    session.add(version)
    await session.flush()
    for shot in shots:
        session.add(
            ShotReferenceBinding(
                project_id=project.id,
                shot_id=shot.id,
                stage="both",
                asset_id=asset.id,
                asset_version_id=version.id,
                resolution_mode="pinned_version",
                purpose="identity",
                label="Hero",
                created_by=user.id,
            )
        )
    await session.flush()
    readiness = await read_production_readiness(session, project_id=project.id)
    assert readiness.shared_asset_count == 1
    sharing = next(item for item in readiness.items if item.key == "cross_episode_sharing")
    assert sharing.status == "ready"
    assert "1个资产被两集以上引用" in sharing.detail


@pytest.mark.asyncio
async def test_current_formal_binding_also_counts_as_cross_episode_sharing(
    session: AsyncSession,
) -> None:
    """The ordinary "current formal version" reference shares like a pin.

    Existing readiness only counted pins, so a project whose two episodes both
    reference the asset's current version looked unshared. Both shapes are the
    same business fact and must be reported the same way.
    """
    from app.assets.models import Asset, AssetVersion
    from app.production.models import ShotReferenceBinding

    project, user = await _project(session, work_type="serial_comic", planned=2)
    await _configure_media(session, project, user)
    shots = []
    for episode_number in (1, 2):
        episode = Episode(
            project_id=project.id,
            episode_number=episode_number,
            title=f"E{episode_number}",
            synopsis="",
        )
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
            sort_order=1,
            shot_type="wide",
            camera_move="static",
            status="draft",
            visual_description="",
            dialogue="",
            duration_seconds=5,
            image_prompt="",
            video_prompt="",
        )
        session.add(shot)
        shots.append(shot)
    await session.flush()
    asset = Asset(project_id=project.id, kind="character", name="Hero", version=1)
    session.add(asset)
    await session.flush()
    version = AssetVersion(
        project_id=project.id,
        asset_id=asset.id,
        version_number=1,
        kind="character",
        name="Hero",
        description="",
        metadata_json={},
        status="formal",
        created_by=user.id,
    )
    session.add(version)
    await session.flush()
    asset.current_version_id = version.id
    for shot in shots:
        session.add(
            ShotReferenceBinding(
                project_id=project.id,
                shot_id=shot.id,
                stage="both",
                asset_id=asset.id,
                resolution_mode="current_formal",
                purpose="identity",
                label="Hero",
                created_by=user.id,
            )
        )
    await session.flush()

    readiness = await read_production_readiness(session, project_id=project.id)
    assert readiness.shared_asset_count == 1
    sharing = next(item for item in readiness.items if item.key == "cross_episode_sharing")
    assert sharing.status == "ready"
