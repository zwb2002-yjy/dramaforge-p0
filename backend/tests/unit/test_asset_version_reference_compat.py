"""P2-02 AssetVersionReference + CharacterReference compat merge (service level)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.access.models import Project, User, Workspace
from app.assets.asset_card_service import AssetCardReadService
from app.assets.models import (
    Asset,
    AssetVersion,
    AssetVersionReference,
    Character,
    CharacterReference,
)
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


async def _seed_project(session: AsyncSession) -> tuple[User, Project]:
    user = User(
        email=f"compat-{uuid4().hex}@example.com",
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
    return user, project


async def test_read_card_merges_version_and_legacy_without_duplication() -> None:
    engine, session = await _make_env()
    try:
        user, project = await _seed_project(session)
        artifact_a = Artifact(
            project_id=project.id,
            artifact_type="image",
            object_key=f"tmp/{uuid4().hex}.png",
            content_hash=uuid4().hex * 2,
            mime_type="image/png",
        )
        artifact_b = Artifact(
            project_id=project.id,
            artifact_type="image",
            object_key=f"tmp/{uuid4().hex}.png",
            content_hash=uuid4().hex * 2,
            mime_type="image/png",
        )
        session.add_all([artifact_a, artifact_b])
        await session.flush()

        asset = Asset(
            project_id=project.id,
            kind="character",
            name="林墨",
            description="",
            status="active",
            version=1,
        )
        session.add(asset)
        await session.flush()
        session.add(Character(id=asset.id, locked_prompt="portrait"))
        version = AssetVersion(
            project_id=project.id,
            asset_id=asset.id,
            version_number=1,
            kind="character",
            name="林墨",
            description="",
            status="formal",
            created_by=user.id,
        )
        session.add(version)
        await session.flush()
        asset.current_version_id = version.id
        # New canonical reference source: artifact_a as front_face.
        session.add(
            AssetVersionReference(
                project_id=project.id,
                asset_version_id=version.id,
                artifact_id=artifact_a.id,
                reference_role="front_face",
                label="front",
                sort_order=0,
            )
        )
        # Legacy CharacterReference rows: one duplicates artifact_a (must not
        # appear twice) and one adds artifact_b.
        session.add_all(
            [
                CharacterReference(
                    character_id=asset.id,
                    artifact_id=artifact_a.id,
                    reference_kind="canonical",
                    is_canonical=True,
                ),
                CharacterReference(
                    character_id=asset.id,
                    artifact_id=artifact_b.id,
                    reference_kind="unknown_kind",
                    is_canonical=False,
                ),
            ]
        )
        await session.flush()

        card = await AssetCardReadService(session).read_card(
            project_id=project.id, asset_id=asset.id, actor=user
        )
        references = card["references"]
        assert isinstance(references, list)
        artifact_ids = [item["artifact_id"] for item in references]
        # No duplicate artifact across version + legacy sources.
        assert len(artifact_ids) == len(set(artifact_ids))
        assert set(artifact_ids) == {artifact_a.id, artifact_b.id}
        roles = {item["artifact_id"]: item["reference_role"] for item in references}
        assert roles[artifact_a.id] == "front_face"
        assert roles[artifact_b.id] == "legacy"
        sources = {item["artifact_id"]: item["source"] for item in references}
        assert sources[artifact_a.id] == "version"
        assert sources[artifact_b.id] == "legacy"
    finally:
        await session.close()
        await engine.dispose()  # type: ignore[union-attr]
