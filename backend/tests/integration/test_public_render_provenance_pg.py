"""The output keeps the actual cross-workspace grant even if the source was revoked in flight."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.public_assets import (
    ProjectPublicAssetLinkService,
    PublicAssetService,
    PublicDisplay,
)
from app.assets.render_lineage import render_origins_available
from app.assets.source_use import SourceUseService
from app.assets.source_use_models import ArtifactSourceUse
from app.editing.timeline_schema import PublicRenderInput
from app.execution.models import Artifact, NodeRun
from app.production.delivery_graph import EDIT_RENDER_NODE, delivery_graph
from app.production.public_render_provenance import (
    complete_public_render_grants,
    freeze_public_render_grants,
)
from app.providers.models import ArtifactReferenceToken
from app.shared.db import set_rls_context
from app.shared.errors import ValidationAppError
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_agent_http_pg import http_agent as http_agent
from test_director_agent_http_pg import http_database as http_database
from test_director_turn_lifecycle_pg import _async_url
from test_director_turn_lifecycle_pg import pytestmark as pytestmark

from fixtures.public_asset_seed import _seed_asset


async def test_frozen_grants_validate_scope_propagate_and_survive_revocation(http_agent):
    a = http_agent
    engine = create_async_engine(_async_url(a.database.name))
    admin = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with admin() as s:
            owner = await s.get(User, (await s.get(Workspace, a.workspace_id)).owner_user_id)
            source = Project(
                workspace_id=a.other_workspace_id,
                name="source",
                aspect_ratio="16:9",
                budget_limit=0,
            )
            s.add(source)
            await s.flush()
            version, media = await _seed_asset(s, project=source, owner=owner)
            media.artifact_type, media.mime_type = "video", "video/mp4"
            grants = SourceUseService(s, actor=owner, project=source)
            admitted = await grants.declare(
                artifact_id=media.id,
                allowed_uses=["library_reference", "export", "external_processing"],
                statement="合成",
                request_key="permit",
            )
            publication = await PublicAssetService(s, actor=owner).publish(
                version.id, display=PublicDisplay(name="选段", description="", style_labels=[])
            )
            s.info["selected_workspace_id"] = a.workspace_id
            link, _ = await ProjectPublicAssetLinkService(
                s, actor=owner, project_id=a.project_id
            ).create(publication_id=publication.id, local_label="选段", request_key="link")
            item = PublicRenderInput.model_validate(
                {
                    "clip_index": 0,
                    "media_kind": "video",
                    "artifact_id": media.id,
                    "artifact_hash": media.content_hash,
                    "source": {
                        "kind": "public_material",
                        "public_asset_link_id": link.id,
                        "publication_id": publication.id,
                        "publication_item_id": publication.items[0].id,
                    },
                }
            )
            await s.commit()
        async with a.factory() as db:
            await set_rls_context(
                db, user_id=owner.id, workspace_id=a.workspace_id, project_id=a.project_id
            )
            assert await db.scalar(select(Artifact.id).where(Artifact.id == media.id)) is None
            _, graph = await delivery_graph(db, project_id=a.project_id, actor_id=owner.id)
            frozen = await freeze_public_render_grants(db, a.project_id, [item])
            assert frozen[0]["source_revision_id"] == str(admitted.id)
            run = NodeRun(
                project_id=a.project_id,
                graph_node_id=graph.nodes[EDIT_RENDER_NODE].id,
                graph_version_id=graph.version.id,
                idempotency_key="freeze",
                created_by=owner.id,
                input_hash="3" * 64,
                input_snapshot={
                    "public_inputs": [item.model_dump(mode="json")],
                    "public_source_grants": frozen,
                    "node_key": "edit_session_render",
                    "subtitle_input_kind": "saved_text_and_timing",
                },
            )
            db.add(run)
            await db.flush()
            # A pre-existing edit render with no frozen public proof stays readable
            # in its project, but cannot seed a new publication or outbound transfer.
            legacy_run = NodeRun(
                project_id=a.project_id,
                graph_node_id=graph.nodes[EDIT_RENDER_NODE].id,
                graph_version_id=graph.version.id,
                idempotency_key="historical",
                input_hash="4" * 64,
                created_by=owner.id,
                attempt_no=2,
                input_snapshot={"public_inputs": [item.model_dump(mode="json")]},
            )
            db.add(legacy_run)
            await db.flush()
            legacy_art = Artifact(
                project_id=a.project_id,
                artifact_type="video",
                storage_state="available",
                byte_size=16,
                mime_type="video/mp4",
                object_key="fixture/legacy",
                content_hash="b" * 64,
                produced_by_run_id=legacy_run.id,
            )
            db.add(legacy_art)
            await db.flush()
            assert await db.get(Artifact, legacy_art.id) is not None
            assert not await render_origins_available(db, a.project_id, legacy_art.id)
            for old in (False, True):
                subtitle = Artifact(
                    project_id=a.project_id,
                    artifact_type="subtitle",
                    mime_type="application/x-subrip",
                    storage_state="available",
                    byte_size=16,
                    object_key=f"fixture/{old}.srt",
                    content_hash=uuid4().hex * 2,
                    produced_by_run_id=legacy_run.id if old else run.id,
                )
                db.add(subtitle)
                await db.flush()
                original = subtitle.produced_by_run_id
                await complete_public_render_grants(db, run, subtitle)
                assert subtitle.produced_by_run_id == original
                assert not list(
                    await db.scalars(
                        select(ArtifactSourceUse).where(
                            ArtifactSourceUse.artifact_id == subtitle.id
                        )
                    )
                )
                assert await render_origins_available(db, a.project_id, subtitle.id) == (not old)
            with pytest.raises(ValidationAppError):
                await complete_public_render_grants(db, run, legacy_art)
            good = Artifact(
                project_id=a.project_id,
                artifact_type="video",
                storage_state="available",
                byte_size=16,
                mime_type="video/mp4",
                object_key="fixture/good",
                content_hash="c" * 64,
                produced_by_run_id=run.id,
            )
            db.add(good)
            await db.flush()
            await complete_public_render_grants(db, run, good)
            assert await render_origins_available(db, a.project_id, good.id)
            tokens = {}
            for artifact in (good, legacy_art):
                digest = uuid4().hex * 2
                tokens[artifact.id] = digest
                db.add(
                    ArtifactReferenceToken(
                        project_id=a.project_id,
                        workspace_id=a.workspace_id,
                        artifact_id=artifact.id,
                        token_hash=digest,
                        expires_at=datetime.now(UTC) + timedelta(minutes=2),
                        created_by_user_id=owner.id,
                    )
                )
            await db.flush()
            redeem = text("SELECT artifact_id FROM app.artifact_reference_for_token(:digest)")
            assert await db.scalar(redeem, {"digest": tokens[good.id]}) == good.id
            assert await db.scalar(redeem, {"digest": tokens[legacy_art.id]}) is None
            await db.commit()
        impact_path = (
            f"/api/v1/projects/{source.id}/source-use-subjects/{admitted.subject_id}/impact"
        )
        own_headers = {**a.headers, "X-Workspace-Id": str(a.other_workspace_id)}
        impact = await a.client.get(impact_path, headers=own_headers)
        assert impact.status_code == 200, impact.text
        # One active library link and one persisted output dependency. Foreign IDs stay private.
        assert impact.json() == {"items": [], "next_cursor": None, "other_project_uses_count": 2}
        assert (await a.client.get(impact_path, headers=a.headers)).status_code == 404
        async with admin() as s:
            latest = await SourceUseService(s, actor=owner, project=source).declare(
                artifact_id=media.id,
                allowed_uses=["library_reference", "export", "external_processing"],
                statement="合成续期许可",
                request_key="renew",
            )
            await s.commit()
        async with a.factory() as db:
            await set_rls_context(
                db, user_id=owner.id, workspace_id=a.workspace_id, project_id=a.project_id
            )
            renewed = await freeze_public_render_grants(db, a.project_id, [item])
            assert renewed[0]["source_revision_id"] == str(latest.id) != str(admitted.id)
            redo = NodeRun(
                project_id=a.project_id,
                graph_node_id=graph.nodes[EDIT_RENDER_NODE].id,
                graph_version_id=graph.version.id,
                idempotency_key="re-export",
                input_hash="5" * 64,
                created_by=owner.id,
                attempt_no=3,
                input_snapshot={
                    "public_inputs": [item.model_dump(mode="json")],
                    "public_source_grants": renewed,
                },
            )
            db.add(redo)
            await db.flush()
            await complete_public_render_grants(db, redo, good)
            retained = (
                await db.scalars(
                    select(ArtifactSourceUse).where(ArtifactSourceUse.artifact_id == good.id)
                )
            ).one()
            assert (
                retained.consumer_node_run_id == run.id
                and retained.source_revision_id == admitted.id
            )
            # Matched new selectors and grants still cannot reuse old bytes if the input hash differs.
            changed = NodeRun(
                id=uuid4(),
                project_id=a.project_id,
                input_snapshot={
                    "public_inputs": [{**item.model_dump(mode="json"), "artifact_hash": "d" * 64}],
                    "public_source_grants": [{**renewed[0], "artifact_hash": "d" * 64}],
                },
            )
            with pytest.raises(ValidationAppError):
                await complete_public_render_grants(db, changed, good)
            await db.commit()
        async with admin() as s:
            await SourceUseService(s, actor=owner, project=source).declare(
                artifact_id=media.id,
                allowed_uses=[],
                state="revoked",
                statement="合成",
                request_key="revoke",
            )
            await s.commit()
        async with a.factory() as db:
            await set_rls_context(
                db, user_id=owner.id, workspace_id=a.workspace_id, project_id=a.project_id
            )
            assert not await render_origins_available(db, a.project_id, good.id)
            assert await db.scalar(redeem, {"digest": tokens[good.id]}) is None
            with pytest.raises(ValidationAppError):
                await freeze_public_render_grants(db, a.project_id, [item])
            output = Artifact(
                project_id=a.project_id,
                artifact_type="video",
                storage_state="available",
                byte_size=16,
                mime_type="video/mp4",
                object_key="fixture/output",
                content_hash="f" * 64,
                produced_by_run_id=run.id,
            )
            db.add(output)
            await db.flush()
            await complete_public_render_grants(db, run, output)
            await complete_public_render_grants(db, run, output)
            stored = (
                await db.scalars(
                    select(ArtifactSourceUse).where(ArtifactSourceUse.artifact_id == output.id)
                )
            ).one()
            assert (
                stored.source_revision_id == admitted.id and stored.source_project_id == source.id
            )
            assert stored.access_basis["public_asset_link_id"] == str(link.id)
            with pytest.raises(DBAPIError, match="SOURCE_USE_BASIS_INVALID"):
                async with db.begin_nested():
                    db.add(
                        ArtifactSourceUse(
                            artifact_id=output.id,
                            project_id=a.project_id,
                            source_subject_id=admitted.subject_id,
                            source_project_id=source.id,
                            source_revision_id=admitted.id,
                            consumer_node_run_id=run.id,
                            input_role="audio:1",
                            source_access_kind="public_asset",
                            access_basis=stored.access_basis,
                        )
                    )
                    await db.flush()
            legacy = NodeRun(
                id=uuid4(),
                project_id=a.project_id,
                input_snapshot={"public_inputs": [item.model_dump(mode="json")]},
            )
            with pytest.raises(ValidationAppError):
                await complete_public_render_grants(db, legacy, output)
            await db.commit()
    finally:
        await engine.dispose()
