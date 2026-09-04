"""§20.1 missing-reference-role computation + card integration."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.access.projects import ProjectService
from app.assets.asset_card_service import (
    AssetCardReadService,
    _expected_roles,
    _missing_roles,
)
from app.assets.models import Asset, AssetVersion, AssetVersionReference
from app.execution.models import Artifact
from app.shared.base import Base
from app.shared.security import hash_password
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
        name=f"Missing-{uuid4().hex[:6]}",
        aspect_ratio="9:16",
        actor=user,
    )
    await session.commit()
    return user, project


def test_expected_roles_by_kind() -> None:
    assert "front_face" in _expected_roles("character")
    assert "outfit" in _expected_roles("character")
    assert "layout_reference" in _expected_roles("scene")
    assert "lighting_reference" in _expected_roles("scene")
    # Unknown kinds fall back to the character set (per design).
    assert "profile" in _expected_roles("prop")


def test_missing_roles_complement() -> None:
    present = {"front_face", "three_quarter"}
    missing = _missing_roles("character", present)
    assert "front_face" not in missing
    assert "profile" in missing
    assert "outfit" in missing
    # Scene set is independent.
    scene_missing = _missing_roles("scene", {"layout_reference"})
    assert "layout_reference" not in scene_missing
    assert "lighting_reference" in scene_missing


@pytest.mark.asyncio
async def test_read_card_reports_missing_reference_roles(session: AsyncSession) -> None:
    user, project = await _project(session)
    asset = Asset(
        project_id=project.id,
        kind="character",
        name="A",
        description="",
        status="active",
        metadata_json={},
    )
    session.add(asset)
    await session.flush()
    version = AssetVersion(
        project_id=project.id,
        asset_id=asset.id,
        version_number=1,
        kind="character",
        name="A v1",
        description="",
        metadata_json={},
        status="formal",
        created_by=user.id,
    )
    session.add(version)
    await session.flush()
    asset.current_version_id = version.id
    # Give it only one angle → the rest are missing.
    artifact = Artifact(
        project_id=project.id,
        object_key="obj/front.png",
        mime_type="image/png",
        content_hash="a" * 64,
        byte_size=1,
        storage_state="available",
        artifact_type="image",
    )
    session.add(artifact)
    await session.flush()
    session.add(
        AssetVersionReference(
            project_id=project.id,
            asset_version_id=version.id,
            artifact_id=artifact.id,
            reference_role="front_face",
            label="front",
            sort_order=0,
            metadata_json={},
        )
    )
    await session.commit()

    card = await AssetCardReadService(session).read_card(
        project_id=project.id, asset_id=asset.id, actor=user
    )
    assert card["missing_reference_roles"] == [
        "three_quarter",
        "profile",
        "half_body",
        "full_body",
        "expression",
        "outfit",
    ]
