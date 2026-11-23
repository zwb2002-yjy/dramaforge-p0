"""One synthetic formal asset and its fixed reference for library read tests."""

from uuid import uuid4

from app.access.models import Project, User
from app.assets.models import Asset, AssetVersion, AssetVersionReference
from app.execution.models import Artifact
from app.shared.db import set_rls_context


async def _seed_asset(session, *, project: Project, owner: User) -> tuple[AssetVersion, Artifact]:
    artifact = Artifact(
        project_id=project.id,
        artifact_type="image",
        object_key=f"tmp/{uuid4().hex}.png",
        content_hash=uuid4().hex * 2,
        mime_type="image/png",
        storage_state="available",
        byte_size=16,
        width=1024,
        height=768,
    )
    session.add(artifact)
    await session.flush()
    asset = Asset(
        project_id=project.id,
        kind="character",
        name="古桥匠人",
        description="",
        status="active",
        version=1,
    )
    session.add(asset)
    await session.flush()
    version = AssetVersion(
        project_id=project.id,
        asset_id=asset.id,
        version_number=1,
        kind="character",
        name="古桥匠人",
        description="",
        status="formal",
        created_by=owner.id,
    )
    session.add(version)
    await session.flush()
    asset.current_version_id = version.id
    session.add(
        AssetVersionReference(
            project_id=project.id,
            asset_version_id=version.id,
            artifact_id=artifact.id,
            reference_role="primary",
            label="primary",
            sort_order=0,
        )
    )
    await session.commit()
    await set_rls_context(
        session, user_id=owner.id, workspace_id=project.workspace_id, project_id=project.id,
    )
    return version, artifact
