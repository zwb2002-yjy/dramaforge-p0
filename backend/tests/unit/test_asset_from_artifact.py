"""Explicit "generated Artifact becomes an Asset card" creation-chain tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.from_artifact_service import (
    AssetFromArtifactRequest,
    AssetFromArtifactService,
    asset_creation_request_hash,
)
from app.assets.models import Asset, AssetVersion, AssetVersionReference
from app.execution.models import Artifact
from app.shared.base import Base
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError
from app.shared.security import hash_password
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _project(session: AsyncSession) -> tuple[User, Project]:
    user = User(
        email=f"fa-{uuid4().hex[:8]}@example.com",
        display_name="FA",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:6]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:6]}",
        aspect_ratio="9:16",
        actor=user,
    )
    await session.commit()
    return user, project


async def _artifact(
    session: AsyncSession,
    *,
    project_id: UUID,
    artifact_type: str = "image",
    storage_state: str = "available",
) -> Artifact:
    artifact = Artifact(
        project_id=project_id,
        artifact_type=artifact_type,
        storage_state=storage_state,
        object_key=f"obj/{uuid4().hex}.bin",
        content_hash=uuid4().hex * 2,
        mime_type="image/png",
        byte_size=8,
    )
    session.add(artifact)
    await session.flush()
    return artifact


def _request(artifact_id: UUID, **overrides: object) -> AssetFromArtifactRequest:
    payload: dict[str, object] = {
        "kind": "character",
        "name": f"林墨-{uuid4().hex[:6]}",
        "artifact_id": artifact_id,
        "description": "lead",
        "metadata": {"source": "keyframe"},
        "reference_role": "front_face",
    }
    payload.update(overrides)
    return AssetFromArtifactRequest(**payload)  # type: ignore[arg-type]


async def _count(session: AsyncSession, model: type) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(model))).scalar_one()
    )


@pytest.mark.asyncio
async def test_creation_writes_asset_version_and_reference_in_one_chain(
    session: AsyncSession,
) -> None:
    user, project = await _project(session)
    artifact = await _artifact(session, project_id=project.id)

    asset = await AssetFromArtifactService(session).create(
        project_id=project.id, actor=user, request=_request(artifact.id)
    )
    await session.commit()

    assert asset.status == "active" and asset.version == 1
    assert asset.current_version_id is not None
    version = await session.get(AssetVersion, asset.current_version_id)
    assert version is not None and version.status == "formal" and version.version_number == 1
    reference = (
        await session.execute(
            select(AssetVersionReference).where(
                AssetVersionReference.asset_version_id == version.id
            )
        )
    ).scalar_one()
    assert reference.artifact_id == artifact.id
    assert reference.reference_role == "front_face"


@pytest.mark.asyncio
async def test_same_request_key_and_input_returns_the_original_card(
    session: AsyncSession,
) -> None:
    """A retried submission must not create a second Asset/Version/Reference set."""
    user, project = await _project(session)
    artifact = await _artifact(session, project_id=project.id)
    request = _request(artifact.id)
    service = AssetFromArtifactService(session)

    first = await service.create(
        project_id=project.id, actor=user, request=request, request_key="add:asset:1"
    )
    await session.commit()
    second = await service.create(
        project_id=project.id, actor=user, request=request, request_key="add:asset:1"
    )
    await session.commit()

    assert second.id == first.id
    assert await _count(session, Asset) == 1
    assert await _count(session, AssetVersion) == 1
    assert await _count(session, AssetVersionReference) == 1


@pytest.mark.asyncio
async def test_same_request_key_with_different_input_is_a_conflict(
    session: AsyncSession,
) -> None:
    user, project = await _project(session)
    artifact = await _artifact(session, project_id=project.id)
    service = AssetFromArtifactService(session)
    await service.create(
        project_id=project.id,
        actor=user,
        request=_request(artifact.id),
        request_key="add:asset:2",
    )
    await session.commit()

    with pytest.raises(ConflictError) as failure:
        await service.create(
            project_id=project.id,
            actor=user,
            request=_request(artifact.id, description="changed"),
            request_key="add:asset:2",
        )

    assert failure.value.details.get("code") == "ASSET_CREATION_REQUEST_REUSED"
    assert await _count(session, Asset) == 1


@pytest.mark.asyncio
async def test_a_new_key_allows_the_same_artifact_in_another_card(
    session: AsyncSession,
) -> None:
    """Retry safety must not forbid an explicit second asset for one artifact."""
    user, project = await _project(session)
    artifact = await _artifact(session, project_id=project.id)
    service = AssetFromArtifactService(session)

    first = await service.create(
        project_id=project.id,
        actor=user,
        request=_request(artifact.id, name="林墨 主视觉"),
        request_key="add:asset:3a",
    )
    second = await service.create(
        project_id=project.id,
        actor=user,
        request=_request(artifact.id, name="林墨 参考"),
        request_key="add:asset:3b",
    )
    await session.commit()

    assert first.id != second.id
    assert await _count(session, Asset) == 2


@pytest.mark.asyncio
async def test_creation_without_a_key_stays_available_for_older_callers(
    session: AsyncSession,
) -> None:
    user, project = await _project(session)
    artifact = await _artifact(session, project_id=project.id)
    service = AssetFromArtifactService(session)

    asset = await service.create(
        project_id=project.id, actor=user, request=_request(artifact.id, name="无键创建")
    )
    await session.commit()

    assert asset.creation_request_key is None
    assert asset.creation_request_hash is None


@pytest.mark.asyncio
async def test_missing_or_foreign_artifact_is_not_found(session: AsyncSession) -> None:
    user, project = await _project(session)
    other_user, other_project = await _project(session)
    foreign = await _artifact(session, project_id=other_project.id)
    service = AssetFromArtifactService(session)

    with pytest.raises(NotFoundError):
        await service.create(
            project_id=project.id, actor=user, request=_request(uuid4()), request_key="k1"
        )
    with pytest.raises(NotFoundError):
        await service.create(
            project_id=project.id, actor=user, request=_request(foreign.id), request_key="k2"
        )
    assert await _count(session, Asset) == 0


@pytest.mark.asyncio
async def test_unstored_or_deleted_artifact_cannot_become_an_asset(
    session: AsyncSession,
) -> None:
    from datetime import UTC, datetime

    user, project = await _project(session)
    quarantined = await _artifact(session, project_id=project.id, storage_state="quarantined")
    deleted = await _artifact(session, project_id=project.id)
    deleted.deleted_at = datetime.now(UTC)
    await session.flush()
    service = AssetFromArtifactService(session)

    with pytest.raises(ValidationAppError) as unstored:
        await service.create(
            project_id=project.id, actor=user, request=_request(quarantined.id), request_key="k3"
        )
    assert unstored.value.details.get("code") == "ARTIFACT_NOT_STORED"

    with pytest.raises(ValidationAppError) as removed:
        await service.create(
            project_id=project.id, actor=user, request=_request(deleted.id), request_key="k4"
        )
    assert removed.value.details.get("code") == "ARTIFACT_DELETED"
    assert await _count(session, Asset) == 0


@pytest.mark.asyncio
async def test_kind_and_reference_role_compatibility_is_enforced(
    session: AsyncSession,
) -> None:
    user, project = await _project(session)
    image = await _artifact(session, project_id=project.id)
    service = AssetFromArtifactService(session)

    with pytest.raises(ValidationAppError) as bad_role:
        await service.create(
            project_id=project.id,
            actor=user,
            request=_request(image.id, reference_role="motion"),
            request_key="k5",
        )
    assert bad_role.value.details.get("code") == "ASSET_REFERENCE_ROLE_UNSUPPORTED"

    # A kind outside the canonical role table keeps its freedom, but still has to
    # match the artifact type.
    with pytest.raises(ValidationAppError) as mismatch:
        await service.create(
            project_id=project.id,
            actor=user,
            request=_request(image.id, kind="video", reference_role="primary"),
            request_key="k7",
        )
    assert mismatch.value.details.get("code") == "ARTIFACT_KIND_MISMATCH"
    assert await _count(session, Asset) == 0


@pytest.mark.asyncio
async def test_duplicate_kind_and_name_is_reported_as_a_conflict(
    session: AsyncSession,
) -> None:
    user, project = await _project(session)
    first_artifact = await _artifact(session, project_id=project.id)
    second_artifact = await _artifact(session, project_id=project.id)
    service = AssetFromArtifactService(session)
    await service.create(
        project_id=project.id,
        actor=user,
        request=_request(first_artifact.id, name="同名资产"),
        request_key="k8",
    )
    await session.commit()

    with pytest.raises(ConflictError) as failure:
        await service.create(
            project_id=project.id,
            actor=user,
            request=_request(second_artifact.id, name="同名资产"),
            request_key="k9",
        )

    assert failure.value.details.get("code") == "ASSET_NAME_TAKEN"
    assert await _count(session, Asset) == 1


def test_request_hash_is_stable_across_key_order() -> None:
    artifact_id = uuid4()
    first = asset_creation_request_hash(
        artifact_id=artifact_id,
        kind="character",
        name="林墨",
        description="lead",
        reference_role="front_face",
        metadata={"a": 1, "b": 2},
    )
    second = asset_creation_request_hash(
        artifact_id=artifact_id,
        kind="character",
        name="林墨",
        description="lead",
        reference_role="front_face",
        metadata={"b": 2, "a": 1},
    )
    changed = asset_creation_request_hash(
        artifact_id=artifact_id,
        kind="character",
        name="林墨",
        description="lead",
        reference_role="profile",
        metadata={"a": 1, "b": 2},
    )
    assert first == second
    assert first != changed
