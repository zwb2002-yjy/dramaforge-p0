"""Adoption receipt: one asset decision, optionally publishing in the same transaction."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.from_artifact_service import AssetFromArtifactRequest, AssetFromArtifactService
from app.assets.public_assets import PublicAssetService, PublicDisplay
from app.execution.models import Artifact


@pytest.fixture
async def world(session):
    owner = User(email=f"adopt-{uuid4()}@example.com", display_name="A", password_hash="x")
    session.add(owner)
    await session.flush()
    workspace = Workspace(name="Adopt", owner_user_id=owner.id)
    session.add(workspace)
    await session.flush()
    project = Project(workspace_id=workspace.id, name="P", aspect_ratio="16:9", budget_limit=0)
    session.add(project)
    await session.flush()
    artifact = Artifact(
        project_id=project.id,
        artifact_type="image",
        object_key=f"tmp/{uuid4().hex}.png",
        content_hash=uuid4().hex * 2,
        mime_type="image/png",
        storage_state="available",
        byte_size=128,
        width=512,
        height=512,
    )
    session.add(artifact)
    await session.commit()
    session.info["selected_workspace_id"] = workspace.id
    return {
        "session": session,
        "owner": owner,
        "project": project,
        "artifact": artifact,
        "service": AssetFromArtifactService(session),
    }


def _request(world) -> AssetFromArtifactRequest:
    return AssetFromArtifactRequest(
        kind="character",
        name="古桥匠人",
        artifact_id=world["artifact"].id,
        description="",
        metadata={},
        reference_role="front_face",
    )


async def test_adoption_with_publication_and_replay(world):
    receipt = await world["service"].create_with_receipt(
        project_id=world["project"].id,
        actor=world["owner"],
        request=_request(world),
        request_key="adopt-1",
        public_display=PublicDisplay(
            name="古桥匠人", description="明代匠人", style_labels=["水墨"]
        ),
    )
    assert receipt.created is True
    assert receipt.accepted_asset_revision == 1
    assert receipt.publication_id is not None
    publication = await PublicAssetService(
        world["session"], actor=world["owner"]
    ).read(receipt.publication_id)
    assert publication.safe_name == "古桥匠人"
    assert publication.items[0].media_kind == "image"
    replay = await world["service"].create_with_receipt(
        project_id=world["project"].id,
        actor=world["owner"],
        request=_request(world),
        request_key="adopt-1",
        public_display=PublicDisplay(
            name="古桥匠人", description="明代匠人", style_labels=["水墨"]
        ),
    )
    assert replay.created is False
    assert replay.publication_id == receipt.publication_id
    assert replay.asset_id == receipt.asset_id


async def test_adoption_without_display_has_no_publication(world):
    receipt = await world["service"].create_with_receipt(
        project_id=world["project"].id,
        actor=world["owner"],
        request=_request(world),
        request_key="adopt-private",
    )
    assert receipt.publication_id is None
    rows, total = await PublicAssetService(
        world["session"], actor=world["owner"]
    ).list()
    assert total == 0
