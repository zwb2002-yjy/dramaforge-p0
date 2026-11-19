"""Public-link shot references: one source, fixed link and item (I5-02)."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from app.shared.security import CSRF_HEADER
from test_director_turn_api import _csrf, _project, _register
from test_director_turn_api import api as api


def _seed_public_link(client, factory) -> tuple[str, str, str, str, str]:
    workspace = _register(client)
    project = _project(client, workspace, "Public refs")
    imported = client.post(
        f"/api/v1/projects/{project}/scripts/import",
        json={
            "filename": "ref.md",
            "text": (
                "# Episode 1 - Demo\n\n## Scene 1 - Studio / day\nBeat.\n\n"
                "### Shot 1 - medium\nVisual: actor turns\nDialogue: Hi\nCamera: static\n"
            ),
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert imported.status_code == 200, imported.text
    shot_id = str(imported.json()["shot_ids"][0])

    from app.access.models import Project as ProjectModel
    from app.access.models import User as UserModel
    from app.access.models import Workspace as WorkspaceModel
    from app.assets.models import Asset, AssetVersion, AssetVersionReference
    from app.assets.public_assets import PublicAssetService, PublicDisplay
    from app.execution.models import Artifact
    from app.shared.db import set_rls_context

    async def seed() -> tuple[str, str, str, str]:
        async with factory() as session:
            ws = await session.get(WorkspaceModel, UUID(workspace))
            assert ws is not None
            owner = await session.get(UserModel, ws.owner_user_id)
            assert owner is not None
            session.info["selected_workspace_id"] = UUID(workspace)
            await set_rls_context(
                session,
                user_id=owner.id,
                workspace_id=ws.id,
                project_id=UUID(project),
            )
            project_row = await session.get(ProjectModel, UUID(project))
            assert project_row is not None
            artifact = Artifact(
                project_id=project_row.id,
                artifact_type="image",
                object_key=f"tmp/{uuid4().hex}.png",
                content_hash=uuid4().hex * 2,
                mime_type="image/png",
                storage_state="available",
                byte_size=16,
            )
            session.add(artifact)
            await session.flush()
            asset = Asset(
                project_id=project_row.id,
                kind="character",
                name="古桥匠人",
                description="",
                status="active",
                version=1,
            )
            session.add(asset)
            await session.flush()
            version = AssetVersion(
                project_id=project_row.id,
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
            session.add(
                AssetVersionReference(
                    project_id=project_row.id,
                    asset_version_id=version.id,
                    artifact_id=artifact.id,
                    reference_role="primary",
                    label="primary",
                    sort_order=0,
                )
            )
            await session.flush()
            published = await PublicAssetService(session, actor=owner).publish(
                version.id,
                display=PublicDisplay(name="古桥匠人", description="", style_labels=[]),
            )
            from app.assets.public_assets import ProjectPublicAssetLinkService

            link, _created = await ProjectPublicAssetLinkService(
                session, actor=owner, project_id=project_row.id
            ).create(
                publication_id=published.id,
                local_label="公共参考",
                request_key="public-ref-link",
            )
            from app.contracts.shot_reference import ShotReferenceIntent
            from app.production.models import ShotReferenceBinding
            from app.production.workbench_execution import WorkbenchExecutionService

            binding = ShotReferenceBinding(
                project_id=project_row.id,
                shot_id=UUID(shot_id),
                stage="image",
                public_asset_link_id=link.id,
                publication_item_id=published.items[0].id,
                resolution_mode="public_link",
                purpose="identity",
                label="公共参考",
                sort_order=0,
                created_by=owner.id,
            )
            session.add(binding)
            await session.flush()
            hydrated = await WorkbenchExecutionService(
                session, user_id=owner.id
            )._hydrate_and_validate_references(
                project=project_row,
                shot_id=UUID(shot_id),
                stage="image_keyframe",
                references=[
                    ShotReferenceIntent(
                        binding_id=binding.id, purpose="identity", source="public"
                    )
                ],
            )
            await session.commit()
            return (
                str(published.id),
                str(published.items[0].id),
                str(link.id),
                shot_id,
                str(hydrated[0].artifact_id),
                str(hydrated[0].publication_id),
                str(hydrated[0].publication_item_id),
                str(hydrated[0].public_asset_link_id),
            )

    (
        publication_id,
        item_id,
        link_id,
        shot,
        hydrated_artifact,
        hydrated_publication,
        hydrated_item,
        hydrated_link,
    ) = asyncio.run(seed())
    return (
        publication_id,
        item_id,
        link_id,
        shot,
        project,
        hydrated_artifact,
        hydrated_publication,
        hydrated_item,
        hydrated_link,
    )


def test_public_link_binding_resolves_and_rejects_detached(api):
    client, factory = api
    (
        publication_id,
        item_id,
        link_id,
        shot_id,
        project,
        hydrated_artifact,
        hydrated_publication,
        hydrated_item,
        hydrated_link,
    ) = _seed_public_link(client, factory)
    base = f"/api/v1/projects/{project}/shots/{shot_id}/references"
    created = client.post(
        base,
        json={
            "source": "public",
            "public_asset_link_id": link_id,
            "publication_item_id": item_id,
            "purpose": "identity",
            "label": "公共参考",
            "stage": "image",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code == 201, created.text
    binding = created.json()
    assert binding["public_asset_link_id"] == link_id
    assert binding["publication_item_id"] == item_id
    assert binding["resolution_mode"] == "public_link"
    resolved = client.post(
        f"{base}/resolve", json={}, headers={CSRF_HEADER: _csrf(client)}
    )
    assert resolved.status_code == 200, resolved.text
    references = [item for item in resolved.json() if item["binding_id"] == binding["id"]]
    assert len(references) == 1
    assert references[0]["source"] == "public_link"
    assert references[0]["purpose"] == "identity"
    # The Production plan hydration consumes the same binding and freezes the
    # public identity + the real source-project artifact, not a private lookup.
    assert hydrated_publication == publication_id
    assert hydrated_item == item_id
    assert hydrated_link == link_id
    assert hydrated_artifact == references[0]["artifact_id"]
    ambiguous = client.post(
        base,
        json={
            "source": "public",
            "public_asset_link_id": link_id,
            "publication_item_id": item_id,
            "asset_id": link_id,
            "purpose": "identity",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert ambiguous.status_code == 422
    assert ambiguous.json()["details"]["code"] == "REFERENCE_SOURCE_AMBIGUOUS"
    missing = client.post(
        base,
        json={"source": "public", "purpose": "identity"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert missing.status_code == 422
    assert missing.json()["details"]["code"] == "REFERENCE_PUBLIC_SOURCE_REQUIRED"
