"""Review gate 6: quality evidence must prove the reviewed media was produced by
the exact model binding being gated — not by a sibling binding."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.access.projects import ProjectService
from app.consistency.identity_policy import identity_evidence_policy_snapshot
from app.execution.models import Artifact, GraphEdge, GraphNode, NodeRun, ProviderOperation
from app.production import models as _pm  # noqa: F401
from app.production.service import GraphService
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
from app.providers.connection_service import ProviderConnectionService
from app.providers.models import ProviderConnection, ProviderModelBinding
from app.shared.base import Base
from app.shared.errors import ValidationAppError
from app.shared.security import hash_password
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _seed_chain(
    session: AsyncSession,
    workspace: Workspace,
    *,
    producer_binding: ProviderModelBinding,
) -> tuple[ProviderModelBinding, NodeRun]:
    user = await session.scalar(select(User).where(User.id == workspace.owner_user_id))
    assert user is not None
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id, name="QL", aspect_ratio="9:16", actor=user
    )
    graph = await GraphService(session).create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="ql-test",
        created_by=user.id,
        definition={},
    )
    keyframe_node = GraphNode(
        graph_version_id=graph.current_version_id,
        node_key="keyframe",
        node_type="keyframe",
        display_name="Keyframe",
        cacheable=True,
    )
    identity_node = GraphNode(
        graph_version_id=graph.current_version_id,
        node_key="identity_review",
        node_type="identity_review",
        display_name="Identity Review",
        cacheable=True,
    )
    session.add_all([keyframe_node, identity_node])
    await session.flush()
    session.add(
        GraphEdge(
            graph_version_id=graph.current_version_id,
            upstream_node_id=keyframe_node.id,
            output_port="media",
            downstream_node_id=identity_node.id,
            input_port="input",
            required=True,
        )
    )
    keyframe_art = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"projects/{project.id}/kf.png",
        content_hash="a" * 64,
        mime_type="image/png",
        byte_size=12,
    )
    identity_art = Artifact(
        project_id=project.id,
        artifact_type="document",
        storage_state="available",
        object_key=f"projects/{project.id}/fr.json",
        content_hash="b" * 64,
        mime_type="application/json",
        byte_size=10,
    )
    session.add_all([keyframe_art, identity_art])
    await session.flush()
    shot_snapshot = {
        "shot_id": "shot-ql",
        "lead_identity_required": True,
        "identity_evidence_policy": identity_evidence_policy_snapshot(),
    }
    keyframe_run = NodeRun(
        project_id=project.id,
        graph_version_id=graph.current_version_id,
        graph_node_id=keyframe_node.id,
        attempt_no=1,
        idempotency_key=f"ql:{uuid4()}",
        input_hash="a" * 64,
        status="completed",
        input_snapshot=shot_snapshot,
        result_artifact_id=keyframe_art.id,
        created_by=user.id,
    )
    session.add(keyframe_run)
    await session.flush()
    keyframe_op = ProviderOperation(
        node_run_id=keyframe_run.id,
        attempt_no=1,
        purpose="primary",
        operation_kind="keyframe.generate",
        actual_provider="agnes",
        actual_model=producer_binding.model_id,
        protocol_profile="agnes_cn_v1",
        request_fingerprint="f" * 64,
        status="succeeded",
        request_summary={},
        response_summary={},
        submitted_at=None,
        model_binding_id=producer_binding.id,
    )
    session.add(keyframe_op)
    identity_run = NodeRun(
        project_id=project.id,
        graph_version_id=graph.current_version_id,
        graph_node_id=identity_node.id,
        attempt_no=1,
        idempotency_key=f"ql:{uuid4()}",
        input_hash="b" * 64,
        status="completed",
        input_snapshot=shot_snapshot,
        result_artifact_id=identity_art.id,
        output_summary={
            "status": "passed",
            "identity_review_status": "passed",
            "human_approved": True,
        },
        created_by=user.id,
    )
    session.add(identity_run)
    await session.flush()
    return producer_binding, identity_run


async def _seed_binding(
    session: AsyncSession,
    workspace: Workspace,
    user: User,
    *,
    model_id: str = "agnes-image-2.1-flash",
    media_type: str = "image",
    purpose: str = "keyframe",
) -> tuple[ProviderConnection, ProviderModelBinding]:
    manifest = next(m for m in SEED_MANIFESTS if m["model_id"] == model_id)
    entry = await session.scalar(
        select(ModelCatalogEntry).where(
            ModelCatalogEntry.provider_type == "agnes",
            ModelCatalogEntry.protocol_profile == "agnes_cn_v1",
            ModelCatalogEntry.model_id == model_id,
            ModelCatalogEntry.model_revision == "v1",
        )
    )
    if entry is None:
        entry = ModelCatalogEntry(
            provider_type="agnes",
            protocol_profile="agnes_cn_v1",
            model_id=model_id,
            model_revision="v1",
            display_name=manifest["display_name"],
            media_kind="image",
            lifecycle="active",
            catalog_source="official_static",
            capability_manifest_json=manifest,
            option_schema_json={},
            documented_at=date.fromisoformat("2026-08-10"),
            contract_manifest_hash=hash_manifest(manifest),
        )
        session.add(entry)
        await session.flush()
    connection = await session.scalar(
        select(ProviderConnection).where(
            ProviderConnection.workspace_id == workspace.id,
            ProviderConnection.provider_type == "agnes",
            ProviderConnection.protocol_profile == "agnes_cn_v1",
        )
    )
    if connection is None:
        connection = ProviderConnection(
            workspace_id=workspace.id,
            provider_type="agnes",
            display_name="Agnes",
            base_url="https://api.agnes-ai.cn",
            protocol_profile="agnes_cn_v1",
            credential_id=uuid4(),
            credential_revision=1,
            enabled=True,
            verification_status="verified",
            created_by=user.id,
            updated_by=user.id,
        )
        session.add(connection)
        await session.flush()
    binding = ProviderModelBinding(
        workspace_id=workspace.id,
        connection_id=connection.id,
        media_type=media_type,
        model_id=model_id,
        purpose=purpose,
        enabled=True,
        documented=True,
        contract_tested=True,
        account_verified=True,
        quality_gated=False,
        catalog_entry_id=entry.id,
        capability_manifest_hash=entry.contract_manifest_hash,
        remote_resource_kind="model",
        remote_resource_id=model_id,
        invoke_model_value=model_id,
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(binding)
    await session.flush()
    return connection, binding


async def _owner(session: AsyncSession) -> User:
    user = User(
        email=f"ql-owner-{uuid4().hex}@example.com",
        display_name="QL",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_quality_evidence_requires_matching_producer_binding(
    session: AsyncSession,
) -> None:
    user = await _owner(session)
    workspace = Workspace(owner_user_id=user.id, name=f"QL-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    connection, binding = await _seed_binding(session, workspace, user)
    _producer, face_run = await _seed_chain(session, workspace, producer_binding=binding)
    face_art = await session.get(Artifact, face_run.result_artifact_id)
    assert face_art is not None

    service = ProviderConnectionService(session)
    evidence = await service.record_quality_evidence(
        workspace_id=workspace.id,
        connection_id=connection.id,
        model_binding_id=binding.id,
        node_run_id=face_run.id,
        artifact_id=face_art.id,
        actor=user,
    )
    assert evidence.evidence_kind == "identity_review"
    refreshed = await session.get(ProviderModelBinding, binding.id)
    assert refreshed is not None and refreshed.quality_gated is True


@pytest.mark.asyncio
async def test_quality_evidence_rejects_other_model_binding(
    session: AsyncSession,
) -> None:
    user = await _owner(session)
    workspace = Workspace(owner_user_id=user.id, name=f"QL-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    connection, gate_binding = await _seed_binding(session, workspace, user)
    # The producer was a DIFFERENT binding (same connection, video purpose).
    _producer_connection, producer_binding = await _seed_binding(
        session,
        workspace,
        user,
        model_id="agnes-video-v2.0",
        media_type="video",
        purpose="video",
    )
    _producer, face_run = await _seed_chain(
        session, workspace, producer_binding=producer_binding
    )
    face_art = await session.get(Artifact, face_run.result_artifact_id)
    assert face_art is not None

    service = ProviderConnectionService(session)
    with pytest.raises(ValidationAppError) as exc_info:
        await service.record_quality_evidence(
            workspace_id=workspace.id,
            connection_id=connection.id,
            model_binding_id=gate_binding.id,
            node_run_id=face_run.id,
            artifact_id=face_art.id,
            actor=user,
        )
    assert exc_info.value.details["code"] == "MODEL_BINDING_NOT_VERIFIED"
