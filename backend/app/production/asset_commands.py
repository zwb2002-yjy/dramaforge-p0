"""Asset media commands: one NodeRun through the same receipt/Worker path (I8a-03).

An explicit user command freezes the previewed asset plan, creates (or reuses) the
asset-scoped ProductionGraph, and queues exactly one NodeRun. It never calls a
Provider itself: the existing Worker claims the run and uses the frozen model
resolution. Repeated submission with the same idempotency key returns the original
receipt; a different payload on the same key is a conflict.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.assets.models import Asset
from app.contracts.production_commands import ExecutionReceipt
from app.execution.models import NodeRun
from app.production.asset_plan import (
    AssetExecutionBody,
    AssetVideoPlanBody,
    AssetVoicePlanBody,
    build_asset_image_plan,
    build_asset_voice_plan,
)
from app.production.execution_plan import fingerprint_plan
from app.production.models import GraphVersion, ProductionGraph
from app.production.service import GraphService
from app.production.workbench_execution import WorkbenchExecutionService
from app.shared.enums import GraphStatus
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

ASSET_IMAGE_TEMPLATE_KEY = "asset-image-v1"
_ASSET_NODE_KEY = "image"


def _asset_idempotency_key(*, asset_id: UUID, override: str | None, plan_fingerprint: str) -> str:
    raw = (
        f"asset-command:{asset_id}:{override}"
        if override
        else f"asset-command:{asset_id}:{plan_fingerprint}"
    )
    if len(raw) <= 160:
        return raw
    return f"asset-command:{asset_id}:{hashlib.sha256(raw.encode()).hexdigest()}"


def _input_hash(snapshot: dict[str, object]) -> str:
    canonical = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _find_receipt(
    session: AsyncSession,
    *,
    project_id: UUID,
    asset_id: UUID,
    key: str,
    plan_fingerprint: str,
) -> NodeRun | None:
    run = await session.scalar(
        select(NodeRun).where(
            NodeRun.project_id == project_id,
            NodeRun.idempotency_key == key,
        )
    )
    if run is None:
        return None
    snapshot = run.input_snapshot or {}
    scope = await session.scalar(
        select(ProductionGraph.scope_entity_id)
        .join(GraphVersion, GraphVersion.graph_id == ProductionGraph.id)
        .where(
            GraphVersion.id == run.graph_version_id,
            ProductionGraph.project_id == project_id,
            ProductionGraph.scope_type == "asset",
        )
    )
    if (
        scope != asset_id
        or snapshot.get("asset_id") != str(asset_id)
        or snapshot.get("plan_fingerprint") != plan_fingerprint
    ):
        raise ConflictError(
            "asset command key was already used with a different request",
            details={"code": "ASSET_COMMAND_REUSED", "node_run_id": str(run.id)},
        )
    return run


async def submit_asset_execution(
    session: AsyncSession,
    *,
    actor: User,
    project_id: UUID,
    asset_id: UUID,
    body: AssetExecutionBody,
    idempotency_key: str | None = None,
) -> ExecutionReceipt:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=actor
    )
    from app.access.egress_admission import EgressAdmission

    decision = await EgressAdmission(session).decide(
        project, purpose="image_generation", processing_location="external"
    )
    if not decision.allowed:
        raise ValidationAppError(
            "项目外发策略不允许本次生成",
            details={"code": decision.reason_code},
        )
    service = WorkbenchExecutionService(session, user_id=actor.id)
    await service.lock_command_scope(project_id=project.id)
    key = _asset_idempotency_key(
        asset_id=asset_id, override=idempotency_key, plan_fingerprint=body.plan_fingerprint
    )
    existing = await _find_receipt(
        session,
        project_id=project.id,
        asset_id=asset_id,
        key=key,
        plan_fingerprint=body.plan_fingerprint,
    )
    if existing is not None:
        return ExecutionReceipt(
            node_run_id=existing.id,
            graph_id=await _graph_id(session, existing),
            graph_version_id=existing.graph_version_id,
            status=existing.status,
            plan_fingerprint=body.plan_fingerprint,
        )
    asset = await session.get(
        Asset, asset_id, with_for_update=True, populate_existing=True
    )
    if asset is None or asset.project_id != project.id:
        raise NotFoundError("Asset not found")
    if asset.version != body.expected_asset_version:
        raise ConflictError(
            "asset changed since plan preview",
            details={"code": "ASSET_VERSION_CONFLICT", "current": asset.version},
        )
    plan = await build_asset_image_plan(
        session, project=project, asset_id=asset.id, body=body
    )
    if plan.plan_fingerprint != body.plan_fingerprint:
        raise ValidationAppError(
            "plan fingerprint mismatch: inputs changed since preview",
            details={"code": "PLAN_FINGERPRINT_MISMATCH"},
        )
    graphs = GraphService(session)
    graph = await session.scalar(
        select(ProductionGraph).where(
            ProductionGraph.project_id == project.id,
            ProductionGraph.scope_type == "asset",
            ProductionGraph.scope_entity_id == asset.id,
        )
    )
    if graph is None:
        graph = await graphs.create_graph(
            project_id=project.id,
            scope_type="asset",
            scope_entity_id=asset.id,
            template_key=ASSET_IMAGE_TEMPLATE_KEY,
            created_by=actor.id,
            definition={
                "nodes": [
                    {"key": _ASSET_NODE_KEY, "type": "keyframe"},
                    {"key": "voice", "type": "voice"},
                ],
                "edges": [],
            },
        )
    assert graph.current_version_id is not None
    materialized = await graphs.materialize_definition(version_id=graph.current_version_id)
    version = materialized.version
    if version.status == GraphStatus.DRAFT.value:
        version = await graphs.publish(version_id=version.id, published_by=actor.id)
    node = materialized.nodes[_ASSET_NODE_KEY]
    previous_run = await session.scalar(
        select(NodeRun)
        .where(NodeRun.graph_node_id == node.id)
        .order_by(NodeRun.attempt_no.desc())
        .limit(1)
    )
    attempt_no = (previous_run.attempt_no if previous_run is not None else 0) + 1
    resolution = plan.resolution
    snapshot: dict[str, object] = {
        "workbench_request_hash": fingerprint_plan(body.model_dump(mode="json")),
        "plan_fingerprint": plan.plan_fingerprint,
        "stage": "image_keyframe",
        "mode_id": body.mode_id,
        "prompt": plan.prompt,
        "project_id": str(project.id),
        "asset_id": str(asset.id),
        "target": {"kind": "asset", "id": str(asset.id)},
        "node_key": _ASSET_NODE_KEY,
        "professional_unified": True,
        "execution_path": "unified-v1",
        "model_binding_id": str(plan.binding_id),
        "capability_manifest_hash": resolution.get("manifest_hash"),
        "connection_revision_id": resolution.get("provider_connection_revision_id"),
        "credential_revision_id": resolution.get("credential_revision_id"),
        "execution_model_resolution": resolution,
        "references": [item.model_dump(mode="json") for item in plan.references],
        "effective_options": dict(plan.parameters),
        "selection_plan": {
            "purpose": "keyframe",
            "mode": body.mode_id,
            "mode_id": body.mode_id,
            "model_binding_id": str(plan.binding_id),
        },
    }
    run = NodeRun(
        project_id=project.id,
        graph_version_id=version.id,
        graph_node_id=node.id,
        attempt_no=attempt_no,
        idempotency_key=key,
        input_hash=_input_hash(snapshot),
        status="queued",
        input_snapshot=snapshot,
        created_by=actor.id,
    )
    session.add(run)
    await session.flush()
    from app.contracts.domain_events import ExecutionAccepted
    from app.production.application.events import append_production_notice

    await append_production_notice(
        session,
        project_id=project.id,
        actor_id=actor.id,
        notice=ExecutionAccepted(asset_id=asset.id, node_run_id=run.id),
    )
    return ExecutionReceipt(
        node_run_id=run.id,
        graph_id=graph.id,
        graph_version_id=version.id,
        status=run.status,
        plan_fingerprint=plan.plan_fingerprint,
    )


async def _graph_id(session: AsyncSession, run: NodeRun) -> UUID:
    graph_id = await session.scalar(
        select(GraphVersion.graph_id).where(GraphVersion.id == run.graph_version_id)
    )
    if graph_id is None:
        raise NotFoundError("Graph not found")
    return graph_id


__all__ = [
    "ASSET_IMAGE_TEMPLATE_KEY",
    "AssetVideoExecutionBody",
    "AssetVoiceExecutionBody",
    "submit_asset_voice_batch",
    "submit_asset_voice_execution",
    "AssetExecutionRead",
    "list_asset_executions",
    "submit_asset_execution",
]

class AssetExecutionRead(BaseModel):
    node_run_id: UUID
    graph_id: UUID
    graph_version_id: UUID
    attempt_no: int
    status: str
    plan_fingerprint: str | None = None
    created_at: datetime | None = None


async def list_asset_executions(
    session: AsyncSession,
    *,
    actor: User,
    project_id: UUID,
    asset_id: UUID,
) -> list[AssetExecutionRead]:
    """Read the asset's NodeRuns; never resolves a model or calls a Provider."""
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=actor
    )
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.project_id != project.id:
        raise NotFoundError("Asset not found")
    rows = (
        await session.execute(
            select(NodeRun, GraphVersion.graph_id)
            .join(GraphVersion, GraphVersion.id == NodeRun.graph_version_id)
            .join(ProductionGraph, ProductionGraph.id == GraphVersion.graph_id)
            .where(
                NodeRun.project_id == project.id,
                ProductionGraph.scope_type == "asset",
                ProductionGraph.scope_entity_id == asset.id,
            )
            .order_by(NodeRun.created_at.desc())
        )
    ).all()
    return [
        AssetExecutionRead(
            node_run_id=run.id,
            graph_id=graph_id,
            graph_version_id=run.graph_version_id,
            attempt_no=run.attempt_no,
            status=run.status,
            plan_fingerprint=(run.input_snapshot or {}).get("plan_fingerprint"),
            created_at=run.created_at,
        )
        for run, graph_id in rows
    ]

class AssetVoiceExecutionBody(AssetVoicePlanBody):
    """One explicit asset voice command: the previewed plan plus its fingerprint."""

    plan_fingerprint: str = Field(min_length=64, max_length=64)


async def submit_asset_voice_execution(
    session: AsyncSession,
    *,
    actor: User,
    project_id: UUID,
    asset_id: UUID,
    body: AssetVoiceExecutionBody,
    idempotency_key: str | None = None,
) -> ExecutionReceipt:
    from app.access.egress_admission import EgressAdmission
    from app.providers.voice_binding import resolve_voice_binding
    from app.providers.voice_config import freeze_voice_execution

    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=actor
    )
    decision = await EgressAdmission(session).decide(
        project, purpose="voice_generation", processing_location="external"
    )
    if not decision.allowed:
        raise ValidationAppError(
            "项目外发策略不允许本次生成",
            details={"code": decision.reason_code},
        )
    service = WorkbenchExecutionService(session, user_id=actor.id)
    await service.lock_command_scope(project_id=project.id)
    key = _asset_idempotency_key(
        asset_id=asset_id, override=idempotency_key, plan_fingerprint=body.plan_fingerprint
    ).replace("asset-command:", "asset-voice:", 1)
    existing = await _find_receipt(
        session,
        project_id=project.id,
        asset_id=asset_id,
        key=key,
        plan_fingerprint=body.plan_fingerprint,
    )
    if existing is not None:
        return ExecutionReceipt(
            node_run_id=existing.id,
            graph_id=await _graph_id(session, existing),
            graph_version_id=existing.graph_version_id,
            status=existing.status,
            plan_fingerprint=body.plan_fingerprint,
        )
    asset = await session.get(
        Asset, asset_id, with_for_update=True, populate_existing=True
    )
    if asset is None or asset.project_id != project.id:
        raise NotFoundError("Asset not found")
    if asset.version != body.expected_asset_version:
        raise ConflictError(
            "asset changed since plan preview",
            details={"code": "ASSET_VERSION_CONFLICT", "current": asset.version},
        )
    plan = await build_asset_voice_plan(
        session, project=project, asset_id=asset.id, body=body
    )
    if plan.plan_fingerprint != body.plan_fingerprint:
        raise ValidationAppError(
            "plan fingerprint mismatch: inputs changed since preview",
            details={"code": "PLAN_FINGERPRINT_MISMATCH"},
        )
    if plan.requires_concat:
        raise ValidationAppError(
            "长文本需分段批量提交；单命令只受理一个分段。",
            details={
                "code": "ASSET_VOICE_SEGMENTED_BATCH_REQUIRED",
                "segments": len(plan.segments),
            },
        )
    status = await resolve_voice_binding(session, project=project)
    spec = freeze_voice_execution(
        {"voice": {"voice_id": plan.voice_options.get("voice_id")}},
        binding=status,
    )
    graphs = GraphService(session)
    graph = await session.scalar(
        select(ProductionGraph).where(
            ProductionGraph.project_id == project.id,
            ProductionGraph.scope_type == "asset",
            ProductionGraph.scope_entity_id == asset.id,
        )
    )
    if graph is None:
        graph = await graphs.create_graph(
            project_id=project.id,
            scope_type="asset",
            scope_entity_id=asset.id,
            template_key=ASSET_IMAGE_TEMPLATE_KEY,
            created_by=actor.id,
            definition={
                "nodes": [
                    {"key": _ASSET_NODE_KEY, "type": "keyframe"},
                    {"key": "voice", "type": "voice"},
                ],
                "edges": [],
            },
        )
    assert graph.current_version_id is not None
    materialized = await graphs.materialize_definition(version_id=graph.current_version_id)
    version = materialized.version
    if version.status == GraphStatus.DRAFT.value:
        version = await graphs.publish(version_id=version.id, published_by=actor.id)
    node = materialized.nodes["voice"]
    previous_run = await session.scalar(
        select(NodeRun)
        .where(NodeRun.graph_node_id == node.id)
        .order_by(NodeRun.attempt_no.desc())
        .limit(1)
    )
    attempt_no = (previous_run.attempt_no if previous_run is not None else 0) + 1
    snapshot: dict[str, object] = {
        "voice_execution": spec.model_dump(mode="json"),
        "workbench_request_hash": fingerprint_plan(body.model_dump(mode="json")),
        "plan_fingerprint": plan.plan_fingerprint,
        "stage": "voice",
        "prompt": plan.text,
        "project_id": str(project.id),
        "asset_id": str(asset.id),
        "target": {"kind": "asset", "id": str(asset.id)},
        "node_key": "voice",
        "professional_unified": True,
        "execution_path": "unified-v1",
        "model_binding_id": str(plan.binding_id),
    }
    run = NodeRun(
        project_id=project.id,
        graph_version_id=version.id,
        graph_node_id=node.id,
        attempt_no=attempt_no,
        idempotency_key=key,
        input_hash=_input_hash(snapshot),
        status="queued",
        input_snapshot=snapshot,
        created_by=actor.id,
    )
    session.add(run)
    await session.flush()
    from app.contracts.domain_events import ExecutionAccepted
    from app.production.application.events import append_production_notice

    await append_production_notice(
        session,
        project_id=project.id,
        actor_id=actor.id,
        notice=ExecutionAccepted(asset_id=asset.id, node_run_id=run.id),
    )
    return ExecutionReceipt(
        node_run_id=run.id,
        graph_id=graph.id,
        graph_version_id=version.id,
        status=run.status,
        plan_fingerprint=plan.plan_fingerprint,
    )

class AssetVideoExecutionBody(AssetVideoPlanBody):
    """One explicit asset video command: the previewed plan plus its fingerprint."""

    plan_fingerprint: str = Field(min_length=64, max_length=64)


async def submit_asset_video_execution(
    session: AsyncSession,
    *,
    actor: User,
    project_id: UUID,
    asset_id: UUID,
    body: AssetVideoExecutionBody,
    idempotency_key: str | None = None,
) -> ExecutionReceipt:
    from app.access.egress_admission import EgressAdmission
    from app.production.asset_plan import build_asset_video_plan

    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=actor
    )
    decision = await EgressAdmission(session).decide(
        project, purpose="video_generation", processing_location="external"
    )
    if not decision.allowed:
        raise ValidationAppError(
            "项目外发策略不允许本次生成",
            details={"code": decision.reason_code},
        )
    service = WorkbenchExecutionService(session, user_id=actor.id)
    await service.lock_command_scope(project_id=project.id)
    key = _asset_idempotency_key(
        asset_id=asset_id, override=idempotency_key, plan_fingerprint=body.plan_fingerprint
    ).replace("asset-command:", "asset-video:", 1)
    existing = await _find_receipt(
        session,
        project_id=project.id,
        asset_id=asset_id,
        key=key,
        plan_fingerprint=body.plan_fingerprint,
    )
    if existing is not None:
        return ExecutionReceipt(
            node_run_id=existing.id,
            graph_id=await _graph_id(session, existing),
            graph_version_id=existing.graph_version_id,
            status=existing.status,
            plan_fingerprint=body.plan_fingerprint,
        )
    asset = await session.get(
        Asset, asset_id, with_for_update=True, populate_existing=True
    )
    if asset is None or asset.project_id != project.id:
        raise NotFoundError("Asset not found")
    if asset.version != body.expected_asset_version:
        raise ConflictError(
            "asset changed since plan preview",
            details={"code": "ASSET_VERSION_CONFLICT", "current": asset.version},
        )
    plan = await build_asset_video_plan(
        session, project=project, asset_id=asset.id, body=body
    )
    if plan.plan_fingerprint != body.plan_fingerprint:
        raise ValidationAppError(
            "plan fingerprint mismatch: inputs changed since preview",
            details={"code": "PLAN_FINGERPRINT_MISMATCH"},
        )
    duration = plan.duration_seconds
    if duration is None:
        raise ValidationAppError(
            "视频命令需要明确的时长参数。",
            details={"code": "ASSET_VIDEO_DURATION_REQUIRED"},
        )
    graphs = GraphService(session)
    graph = await session.scalar(
        select(ProductionGraph).where(
            ProductionGraph.project_id == project.id,
            ProductionGraph.scope_type == "asset",
            ProductionGraph.scope_entity_id == asset.id,
        )
    )
    if graph is None:
        graph = await graphs.create_graph(
            project_id=project.id,
            scope_type="asset",
            scope_entity_id=asset.id,
            template_key=ASSET_IMAGE_TEMPLATE_KEY,
            created_by=actor.id,
            definition={
                "nodes": [
                    {"key": _ASSET_NODE_KEY, "type": "keyframe"},
                    {"key": "voice", "type": "voice"},
                    {"key": "video", "type": "video"},
                ],
                "edges": [],
            },
        )
    assert graph.current_version_id is not None
    materialized = await graphs.materialize_definition(version_id=graph.current_version_id)
    version = materialized.version
    if version.status == GraphStatus.DRAFT.value:
        version = await graphs.publish(version_id=version.id, published_by=actor.id)
    node = materialized.nodes["video"]
    previous_run = await session.scalar(
        select(NodeRun)
        .where(NodeRun.graph_node_id == node.id)
        .order_by(NodeRun.attempt_no.desc())
        .limit(1)
    )
    attempt_no = (previous_run.attempt_no if previous_run is not None else 0) + 1
    resolution = plan.resolution
    snapshot: dict[str, object] = {
        "workbench_request_hash": fingerprint_plan(body.model_dump(mode="json")),
        "plan_fingerprint": plan.plan_fingerprint,
        "stage": "video",
        "mode_id": body.mode_id,
        "prompt": plan.prompt,
        "duration_seconds": duration,
        "project_id": str(project.id),
        "asset_id": str(asset.id),
        "target": {"kind": "asset", "id": str(asset.id)},
        "node_key": "video",
        "professional_unified": True,
        "execution_path": "unified-v1",
        "model_binding_id": str(plan.binding_id),
        "capability_manifest_hash": resolution.get("manifest_hash"),
        "connection_revision_id": resolution.get("provider_connection_revision_id"),
        "credential_revision_id": resolution.get("credential_revision_id"),
        "execution_model_resolution": resolution,
        "references": [item.model_dump(mode="json") for item in plan.references],
        "effective_options": dict(plan.parameters),
        "selection_plan": {
            "purpose": "video",
            "mode": body.mode_id,
            "mode_id": body.mode_id,
            "model_binding_id": str(plan.binding_id),
        },
    }
    run = NodeRun(
        project_id=project.id,
        graph_version_id=version.id,
        graph_node_id=node.id,
        attempt_no=attempt_no,
        idempotency_key=key,
        input_hash=_input_hash(snapshot),
        status="queued",
        input_snapshot=snapshot,
        created_by=actor.id,
    )
    session.add(run)
    await session.flush()
    from app.contracts.domain_events import ExecutionAccepted
    from app.production.application.events import append_production_notice

    await append_production_notice(
        session,
        project_id=project.id,
        actor_id=actor.id,
        notice=ExecutionAccepted(asset_id=asset.id, node_run_id=run.id),
    )
    return ExecutionReceipt(
        node_run_id=run.id,
        graph_id=graph.id,
        graph_version_id=version.id,
        status=run.status,
        plan_fingerprint=plan.plan_fingerprint,
    )

async def submit_asset_voice_batch(
    session: AsyncSession,
    *,
    actor: User,
    project_id: UUID,
    asset_id: UUID,
    body: AssetVoiceExecutionBody,
    idempotency_key: str | None = None,
) -> ExecutionReceipt:
    """Segmented speech: one voice run per segment plus a local concat dependency."""
    from app.access.egress_admission import EgressAdmission
    from app.providers.voice_binding import resolve_voice_binding
    from app.providers.voice_config import freeze_voice_execution

    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=actor
    )
    decision = await EgressAdmission(session).decide(
        project, purpose="voice_generation", processing_location="external"
    )
    if not decision.allowed:
        raise ValidationAppError(
            "项目外发策略不允许本次生成",
            details={"code": decision.reason_code},
        )
    service = WorkbenchExecutionService(session, user_id=actor.id)
    await service.lock_command_scope(project_id=project.id)
    key = _asset_idempotency_key(
        asset_id=asset_id, override=idempotency_key, plan_fingerprint=body.plan_fingerprint
    ).replace("asset-command:", "asset-voice-batch:", 1)
    existing = await _find_receipt(
        session,
        project_id=project.id,
        asset_id=asset_id,
        key=key,
        plan_fingerprint=body.plan_fingerprint,
    )
    if existing is not None:
        return ExecutionReceipt(
            node_run_id=existing.id,
            graph_id=await _graph_id(session, existing),
            graph_version_id=existing.graph_version_id,
            status=existing.status,
            plan_fingerprint=body.plan_fingerprint,
        )
    asset = await session.get(
        Asset, asset_id, with_for_update=True, populate_existing=True
    )
    if asset is None or asset.project_id != project.id:
        raise NotFoundError("Asset not found")
    if asset.version != body.expected_asset_version:
        raise ConflictError(
            "asset changed since plan preview",
            details={"code": "ASSET_VERSION_CONFLICT", "current": asset.version},
        )
    plan = await build_asset_voice_plan(
        session, project=project, asset_id=asset.id, body=body
    )
    if plan.plan_fingerprint != body.plan_fingerprint:
        raise ValidationAppError(
            "plan fingerprint mismatch: inputs changed since preview",
            details={"code": "PLAN_FINGERPRINT_MISMATCH"},
        )
    if len(plan.segments) < 2:
        raise ValidationAppError(
            "single-segment text uses the single voice command",
            details={"code": "ASSET_VOICE_SINGLE_SEGMENT"},
        )
    status = await resolve_voice_binding(session, project=project)
    spec = freeze_voice_execution(
        {"voice": {"voice_id": plan.voice_options.get("voice_id")}},
        binding=status,
    )
    graphs = GraphService(session)
    graph = await session.scalar(
        select(ProductionGraph).where(
            ProductionGraph.project_id == project.id,
            ProductionGraph.scope_type == "asset",
            ProductionGraph.scope_entity_id == asset.id,
        )
    )
    if graph is None:
        graph = await graphs.create_graph(
            project_id=project.id,
            scope_type="asset",
            scope_entity_id=asset.id,
            template_key=ASSET_IMAGE_TEMPLATE_KEY,
            created_by=actor.id,
            definition={
                "nodes": [
                    {"key": _ASSET_NODE_KEY, "type": "keyframe"},
                    {"key": "voice", "type": "voice"},
                    {"key": "video", "type": "video"},
                ],
                "edges": [],
            },
        )
    assert graph.current_version_id is not None
    materialized = await graphs.materialize_definition(version_id=graph.current_version_id)
    version = materialized.version
    if version.status == GraphStatus.DRAFT.value:
        version = await graphs.publish(version_id=version.id, published_by=actor.id)
    # Segment and concat nodes are added as a new published version when absent.
    existing_keys = set(materialized.nodes)
    segment_keys = [f"voice_seg_{index}" for index in range(len(plan.segments))]
    missing = [key for key in [*segment_keys, "voice_concat"] if key not in existing_keys]
    if missing:
        definition: dict[str, object] = {
            "nodes": [
                {"key": key, "type": "voice"} for key in [*existing_keys, *segment_keys]
            ]
            + [{"key": "voice_concat", "type": "voice_concat"}],
            "edges": [[key, "voice_concat"] for key in segment_keys],
        }
        new_version = await graphs.create_version(
            graph_id=graph.id, definition=definition, created_by=actor.id
        )
        materialized = await graphs.materialize_definition(version_id=new_version.id)
        version = materialized.version
        if version.status == GraphStatus.DRAFT.value:
            version = await graphs.publish(version_id=version.id, published_by=actor.id)
    segment_run_ids: list[UUID] = []
    for index, segment in enumerate(plan.segments):
        node = materialized.nodes[segment_keys[index]]
        previous = await session.scalar(
            select(NodeRun)
            .where(NodeRun.graph_node_id == node.id)
            .order_by(NodeRun.attempt_no.desc())
            .limit(1)
        )
        attempt_no = (previous.attempt_no if previous is not None else 0) + 1
        snapshot: dict[str, object] = {
            "voice_execution": spec.model_dump(mode="json"),
            "plan_fingerprint": plan.plan_fingerprint,
            "stage": "voice",
            "prompt": segment.text,
            "segment_index": index,
            "project_id": str(project.id),
            "asset_id": str(asset.id),
            "target": {"kind": "asset", "id": str(asset.id)},
            "node_key": segment_keys[index],
            "professional_unified": True,
            "execution_path": "unified-v1",
            "model_binding_id": str(plan.binding_id),
        }
        segment_run = NodeRun(
            project_id=project.id,
            graph_version_id=version.id,
            graph_node_id=node.id,
            attempt_no=attempt_no,
            idempotency_key=f"{key}:seg{index}",
            input_hash=_input_hash(snapshot),
            status="queued",
            input_snapshot=snapshot,
            created_by=actor.id,
        )
        session.add(segment_run)
        await session.flush()
        segment_run_ids.append(segment_run.id)
    concat_node = materialized.nodes["voice_concat"]
    previous_concat = await session.scalar(
        select(NodeRun)
        .where(NodeRun.graph_node_id == concat_node.id)
        .order_by(NodeRun.attempt_no.desc())
        .limit(1)
    )
    concat_attempt = (
        previous_concat.attempt_no if previous_concat is not None else 0
    ) + 1
    concat_snapshot: dict[str, object] = {
        "plan_fingerprint": plan.plan_fingerprint,
        "stage": "voice",
        "project_id": str(project.id),
        "asset_id": str(asset.id),
        "target": {"kind": "asset", "id": str(asset.id)},
        "node_key": "voice_concat",
        "segment_run_ids": [str(item) for item in segment_run_ids],
        "segment_count": len(segment_run_ids),
    }
    concat_run = NodeRun(
        project_id=project.id,
        graph_version_id=version.id,
        graph_node_id=concat_node.id,
        attempt_no=concat_attempt,
        idempotency_key=key,
        input_hash=_input_hash(concat_snapshot),
        status="queued",
        input_snapshot=concat_snapshot,
        created_by=actor.id,
    )
    session.add(concat_run)
    await session.flush()
    from app.contracts.domain_events import ExecutionAccepted
    from app.production.application.events import append_production_notice

    await append_production_notice(
        session,
        project_id=project.id,
        actor_id=actor.id,
        notice=ExecutionAccepted(asset_id=asset.id, node_run_id=concat_run.id),
    )
    return ExecutionReceipt(
        node_run_id=concat_run.id,
        graph_id=graph.id,
        graph_version_id=version.id,
        status=concat_run.status,
        plan_fingerprint=plan.plan_fingerprint,
    )