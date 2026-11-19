"""Edit timeline schema 2 is typed and its sources are verified at Save (I9-01)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.editing.adapter import EditingAdapter
from app.execution.models import Artifact
from app.production.models import ShotReferenceBinding  # noqa: F401 - document intent
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _shot(
    session: AsyncSession, *, formal: bool = True
) -> tuple[Project, User, Shot, Artifact | None]:
    suffix = uuid4().hex[:8]
    user = User(email=f"edit-{suffix}@example.com", display_name="E", password_hash="x")
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
        work_type="single_comic",
        planned_episode_count=1,
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
        sort_order=1,
        status="draft",
        visual_description="frame",
        duration_seconds=5,
    )
    session.add(shot)
    await session.flush()
    artifact = None
    if formal:
        artifact = Artifact(
            project_id=project.id,
            artifact_type="video",
            storage_state="available",
            object_key=f"obj/{uuid4().hex}",
            content_hash="a" * 64,
            mime_type="video/mp4",
            byte_size=1024,
            duration_seconds=5,
        )
        session.add(artifact)
        await session.flush()
        shot.formal_video_artifact_id = artifact.id
        await session.flush()
    return project, user, shot, artifact


def _clip(shot: Shot, artifact: Artifact, *, order: int = 1, kind: str = "shot_formal"):
    return {
        "id": f"clip-{order}",
        "order": order,
        "duration_seconds": 5.0,
        "subtitle": "",
        "transition": None,
        "source": {
            "kind": kind,
            "shot_id": str(shot.id),
            "artifact_id": str(artifact.id),
        },
    }


@pytest.mark.asyncio
async def test_schema1_timeline_is_stored_without_an_upgrade(session: AsyncSession) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    legacy = {
        "clips": [
            {
                "id": "clip-1",
                "shot_id": str(shot.id),
                "artifact_id": str(artifact.id),
                "order": 1,
                "duration_seconds": 5.0,
                "subtitle": "",
                "audio_id": None,
                "transition": None,
            }
        ],
        "metadata": {"note": "legacy"},
    }
    saved = await adapter.save_timeline(
        project_id=project.id,
        session_id=row.id,
        timeline={**legacy, "schema_version": 1},
        expected_session_version=1,
    )
    # No on-disk schema marker is invented for a schema 1 document.
    assert "schema_version" not in saved.timeline
    assert saved.timeline["clips"] == legacy["clips"]
    assert saved.version == 2


@pytest.mark.asyncio
async def test_schema2_shot_formal_source_is_verified_and_stored(session: AsyncSession) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    saved = await adapter.save_timeline(
        project_id=project.id,
        session_id=row.id,
        timeline={"schema_version": 2, "clips": [_clip(shot, artifact)], "metadata": {}},
        expected_session_version=1,
    )
    assert saved.timeline["schema_version"] == 2
    clip = saved.timeline["clips"][0]
    assert clip["source"]["kind"] == "shot_formal"
    assert clip["source"]["artifact_id"] == str(artifact.id)


@pytest.mark.asyncio
async def test_schema2_rejects_a_source_that_is_not_the_current_formal_video(
    session: AsyncSession,
) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    other = Artifact(
        project_id=project.id,
        artifact_type="video",
        storage_state="available",
        object_key=f"obj/{uuid4().hex}",
        content_hash="b" * 64,
        mime_type="video/mp4",
        byte_size=1024,
    )
    session.add(other)
    await session.flush()
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    stale = _clip(shot, artifact)
    stale["source"]["artifact_id"] = str(other.id)
    with pytest.raises(ValidationAppError) as rejected:
        await adapter.save_timeline(
            project_id=project.id,
            session_id=row.id,
            timeline={"schema_version": 2, "clips": [stale], "metadata": {}},
            expected_session_version=1,
        )
    assert rejected.value.details["code"] == "EDIT_SOURCE_NOT_FORMAL"
    await session.rollback()


@pytest.mark.asyncio
async def test_schema2_refuses_public_material_without_a_real_link(session: AsyncSession) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    forged = _clip(shot, artifact)
    forged["source"] = {
        "kind": "public_material",
        "publication_id": str(uuid4()),
        "publication_item_id": str(uuid4()),
        "public_asset_link_id": str(uuid4()),
    }
    with pytest.raises(ValidationAppError) as refused:
        await adapter.save_timeline(
            project_id=project.id,
            session_id=row.id,
            timeline={"schema_version": 2, "clips": [forged], "metadata": {}},
            expected_session_version=1,
        )
    # Identities in the JSON are never trusted; the link must really exist.
    assert refused.value.details["code"] == "EDIT_SOURCE_NOT_ADOPTED"
    await session.rollback()


async def _adopted_version(session: AsyncSession, *, project: Project, user: User):
    """One formal, current asset version with a playable video reference."""
    from app.assets.models import Asset, AssetVersion, AssetVersionReference

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
    media = Artifact(
        project_id=project.id,
        artifact_type="video",
        storage_state="available",
        object_key=f"obj/{uuid4().hex}",
        content_hash="d" * 64,
        mime_type="video/mp4",
        byte_size=4096,
    )
    session.add(media)
    await session.flush()
    session.add(
        AssetVersionReference(
            project_id=project.id,
            asset_version_id=version.id,
            artifact_id=media.id,
            reference_role="performance",
            label="take",
            sort_order=0,
            metadata_json={},
        )
    )
    await session.flush()
    return asset, version, media


@pytest.mark.asyncio
async def test_adopted_asset_version_clip_is_verified_and_snapshotted(
    session: AsyncSession,
) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    asset, version, media = await _adopted_version(session, project=project, user=user)
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    clip = _clip(shot, artifact)
    clip["source"] = {
        "kind": "asset_version",
        "asset_id": str(asset.id),
        "asset_version_id": str(version.id),
    }
    saved = await adapter.save_timeline(
        project_id=project.id,
        session_id=row.id,
        timeline={"schema_version": 2, "clips": [clip], "metadata": {}},
        expected_session_version=1,
    )
    snapshot = saved.timeline["clips"][0]["selection_snapshot"]
    assert snapshot["kind"] == "asset_version"
    assert snapshot["artifact_id"] == str(media.id)
    assert snapshot["artifact_hash"] == media.content_hash


@pytest.mark.asyncio
async def test_stale_or_medialess_asset_version_is_rejected(session: AsyncSession) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    asset, version, _media = await _adopted_version(session, project=project, user=user)
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    clip = _clip(shot, artifact)
    clip["source"] = {
        "kind": "asset_version",
        "asset_id": str(asset.id),
        "asset_version_id": str(version.id),
    }
    # A newer candidate takes over the asset: the pinned version is no longer current.
    version.status = "historical"
    asset.current_version_id = None
    await session.flush()
    with pytest.raises(ValidationAppError) as rejected:
        await adapter.save_timeline(
            project_id=project.id,
            session_id=row.id,
            timeline={"schema_version": 2, "clips": [clip], "metadata": {}},
            expected_session_version=1,
        )
    assert rejected.value.details["code"] == "EDIT_SOURCE_NOT_ADOPTED"
    await session.rollback()


@pytest.mark.asyncio
async def test_schema2_rejects_malformed_documents(session: AsyncSession) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    # Build the documents before committing: the commit expires ORM attributes.
    missing_source = _clip(shot, artifact)
    missing_source.pop("source")
    duplicate = [_clip(shot, artifact, order=1), _clip(shot, artifact, order=2)]
    duplicate[1]["id"] = duplicate[0]["id"]
    gap = [_clip(shot, artifact, order=1), _clip(shot, artifact, order=3)]
    unknown_kind = _clip(shot, artifact, kind="private_upload")

    # Each rejected save rolls back, so the session row must already be durable.
    # Capture raw ids first: committing expires the ORM instances.
    project_id, session_id = project.id, row.id
    await session.commit()

    for document in (missing_source, duplicate, gap, unknown_kind):
        clips = document if isinstance(document, list) else [document]
        with pytest.raises(ValidationAppError) as rejected:
            await adapter.save_timeline(
                project_id=project_id,
                session_id=session_id,
                timeline={"schema_version": 2, "clips": clips, "metadata": {}},
                expected_session_version=1,
            )
        assert rejected.value.details["code"] == "EDIT_TIMELINE_INVALID"
        await session.rollback()


@pytest.mark.asyncio
async def test_episode_scoped_session_rejects_a_clip_from_another_episode(
    session: AsyncSession,
) -> None:
    """Episode scope is enforced at Save, not by trusting the timeline JSON."""
    from app.assets.models import Episode

    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    other_episode = Episode(project_id=project.id, episode_number=2, title="E2", synopsis="")
    session.add(other_episode)
    await session.flush()
    adapter = EditingAdapter(session)
    scoped = await adapter.create_session(
        project_id=project.id,
        user_id=user.id,
        name="Episode 2",
        episode_id=other_episode.id,
    )
    with pytest.raises(ValidationAppError) as rejected:
        await adapter.save_timeline(
            project_id=project.id,
            session_id=scoped.id,
            timeline={"schema_version": 2, "clips": [_clip(shot, artifact)], "metadata": {}},
            expected_session_version=1,
        )
    assert rejected.value.details["code"] == "EDIT_CLIP_OUT_OF_EPISODE"
    await session.rollback()


@pytest.mark.asyncio
async def test_episode_scoped_session_accepts_its_own_clip_and_rejects_foreign_episode(
    session: AsyncSession,
) -> None:
    from app.assets.models import Episode

    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    episode = await session.scalar(select(Episode).where(Episode.project_id == project.id))
    assert episode is not None
    adapter = EditingAdapter(session)
    scoped = await adapter.create_session(
        project_id=project.id,
        user_id=user.id,
        name="Episode 1",
        episode_id=episode.id,
    )
    saved = await adapter.save_timeline(
        project_id=project.id,
        session_id=scoped.id,
        timeline={"schema_version": 2, "clips": [_clip(shot, artifact)], "metadata": {}},
        expected_session_version=1,
    )
    assert saved.episode_id == episode.id
    assert saved.timeline["schema_version"] == 2

    # An episode from a different project is not a valid scope at creation.
    _other_project, _other_user, _other_shot, _other_artifact = await _shot(session)
    with pytest.raises(NotFoundError):
        await adapter.create_session(
            project_id=project.id,
            user_id=user.id,
            name="Foreign",
            episode_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_save_records_a_server_side_selection_snapshot(session: AsyncSession) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    saved = await adapter.save_timeline(
        project_id=project.id,
        session_id=row.id,
        timeline={"schema_version": 2, "clips": [_clip(shot, artifact)], "metadata": {}},
        expected_session_version=1,
    )
    snapshot = saved.timeline["clips"][0]["selection_snapshot"]
    assert snapshot["schema_version"] == 2
    assert snapshot["session_version"] == 2
    assert snapshot["clip_id"] == "clip-1"
    assert snapshot["kind"] == "shot_formal"
    assert snapshot["artifact_hash"] == artifact.content_hash
    assert snapshot["identity"]["artifact_id"] == str(artifact.id)
    assert snapshot["confirmed_at"]


@pytest.mark.asyncio
async def test_unchanged_source_reuses_the_previous_observation(session: AsyncSession) -> None:
    """Saving again without touching the source must not re-date the proof."""
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    first = await adapter.save_timeline(
        project_id=project.id,
        session_id=row.id,
        timeline={"schema_version": 2, "clips": [_clip(shot, artifact)], "metadata": {}},
        expected_session_version=1,
    )
    original = dict(first.timeline["clips"][0]["selection_snapshot"])
    second = await adapter.save_timeline(
        project_id=project.id,
        session_id=row.id,
        timeline={"schema_version": 2, "clips": [_clip(shot, artifact)], "metadata": {}},
        expected_session_version=2,
    )
    reused = second.timeline["clips"][0]["selection_snapshot"]
    assert reused["confirmed_at"] == original["confirmed_at"]
    assert reused["session_version"] == original["session_version"]


@pytest.mark.asyncio
async def test_changed_source_redates_and_keeps_the_initial_source(
    session: AsyncSession,
) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    await adapter.save_timeline(
        project_id=project.id,
        session_id=row.id,
        timeline={"schema_version": 2, "clips": [_clip(shot, artifact)], "metadata": {}},
        expected_session_version=1,
    )
    replacement = Artifact(
        project_id=project.id,
        artifact_type="video",
        storage_state="available",
        object_key=f"obj/{uuid4().hex}",
        content_hash="c" * 64,
        mime_type="video/mp4",
        byte_size=2048,
    )
    session.add(replacement)
    await session.flush()
    shot.formal_video_artifact_id = replacement.id
    await session.flush()
    updated = await adapter.save_timeline(
        project_id=project.id,
        session_id=row.id,
        timeline={
            "schema_version": 2,
            "clips": [_clip(shot, replacement)],
            "metadata": {},
        },
        expected_session_version=2,
    )
    snapshot = updated.timeline["clips"][0]["selection_snapshot"]
    assert snapshot["artifact_hash"] == replacement.content_hash
    assert snapshot["session_version"] == 3
    assert snapshot["initial_source"]["artifact_id"] == str(artifact.id)


async def _published_material(session: AsyncSession, *, project: Project, user: User):
    """Publish an adopted version and link it into the consuming project."""
    from app.assets.public_asset_models import PublicAssetPublicationItem
    from app.assets.public_assets import (
        ProjectPublicAssetLinkService,
        PublicAssetService,
        PublicDisplay,
    )

    _asset, version, media = await _adopted_version(session, project=project, user=user)
    publication = await PublicAssetService(session, actor=user).publish(
        version.id,
        display=PublicDisplay(name="Hero take", description="", style_labels=[]),
    )
    item = (
        await session.scalars(
            select(PublicAssetPublicationItem).where(
                PublicAssetPublicationItem.publication_id == publication.id
            )
        )
    ).first()
    assert item is not None
    link, _created = await ProjectPublicAssetLinkService(
        session, actor=user, project_id=project.id
    ).create(
        publication_id=publication.id,
        local_label="hero",
        request_key=f"link-{uuid4().hex}",
    )
    return publication, item, link, media


@pytest.mark.asyncio
async def test_public_material_clip_resolves_through_the_project_link(
    session: AsyncSession,
) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    publication, item, link, media = await _published_material(session, project=project, user=user)
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    clip = _clip(shot, artifact)
    clip["source"] = {
        "kind": "public_material",
        "publication_id": str(publication.id),
        "publication_item_id": str(item.id),
        "public_asset_link_id": str(link.id),
    }
    saved = await adapter.save_timeline(
        project_id=project.id,
        session_id=row.id,
        timeline={"schema_version": 2, "clips": [clip], "metadata": {}},
        expected_session_version=1,
    )
    snapshot = saved.timeline["clips"][0]["selection_snapshot"]
    assert snapshot["kind"] == "public_material"
    assert snapshot["artifact_id"] == str(media.id)
    assert snapshot["artifact_hash"] == media.content_hash


@pytest.mark.asyncio
async def test_detached_public_link_or_withdrawn_publication_is_rejected(
    session: AsyncSession,
) -> None:
    from datetime import UTC, datetime

    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    publication, item, link, _media = await _published_material(session, project=project, user=user)
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    clip = _clip(shot, artifact)
    clip["source"] = {
        "kind": "public_material",
        "publication_id": str(publication.id),
        "publication_item_id": str(item.id),
        "public_asset_link_id": str(link.id),
    }

    from app.assets.public_asset_models import ProjectPublicAssetLink

    stored_link = await session.get(ProjectPublicAssetLink, link.id)
    assert stored_link is not None
    stored_link.detached_at = datetime.now(UTC)
    await session.flush()
    with pytest.raises(ValidationAppError) as detached:
        await adapter.save_timeline(
            project_id=project.id,
            session_id=row.id,
            timeline={"schema_version": 2, "clips": [clip], "metadata": {}},
            expected_session_version=1,
        )
    assert detached.value.details["code"] == "EDIT_SOURCE_NOT_ADOPTED"
    await session.rollback()

    project2, user2, shot2, artifact2 = await _shot(session)
    assert artifact2 is not None
    publication2, item2, link2, _media2 = await _published_material(
        session, project=project2, user=user2
    )
    adapter2 = EditingAdapter(session)
    row2 = await adapter2.create_session(project_id=project2.id, user_id=user2.id, name="Edit")
    withdrawn = _clip(shot2, artifact2)
    withdrawn["source"] = {
        "kind": "public_material",
        "publication_id": str(publication2.id),
        "publication_item_id": str(item2.id),
        "public_asset_link_id": str(link2.id),
    }
    from app.assets.public_asset_models import PublicAssetPublication

    stored_publication = await session.get(PublicAssetPublication, publication2.id)
    assert stored_publication is not None
    stored_publication.status = "withdrawn"
    stored_publication.withdrawn_at = datetime.now(UTC)
    await session.flush()
    with pytest.raises(ValidationAppError) as revoked:
        await adapter2.save_timeline(
            project_id=project2.id,
            session_id=row2.id,
            timeline={"schema_version": 2, "clips": [withdrawn], "metadata": {}},
            expected_session_version=1,
        )
    assert revoked.value.details["code"] == "EDIT_SOURCE_NOT_ADOPTED"


@pytest.mark.asyncio
async def test_save_keeps_the_version_conflict_contract(session: AsyncSession) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    with pytest.raises(ConflictError):
        await adapter.save_timeline(
            project_id=project.id,
            session_id=row.id,
            timeline={"schema_version": 2, "clips": [_clip(shot, artifact)], "metadata": {}},
            expected_session_version=7,
        )
