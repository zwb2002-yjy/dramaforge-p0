"""Worker entry: claim and dispatch NodeRuns; never submit from an HTTP request."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.consistency.identity_policy import (
    validate_identity_evidence_policy,
)
from app.execution.artifact_inputs import (
    _bind_review_input_artifacts,
    _read_bound_artifact,
)
from app.execution.local_nodes import _complete_composite_node, _complete_pure_node
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.execution.provider_execution import (
    _execute_unified_media_node_run,
)
from app.execution.run_state import UNIFIED_PATH_VERSION as UNIFIED_PATH_VERSION
from app.execution.run_state import ExecuteNodeResult as ExecuteNodeResult
from app.execution.run_state import _commit_terminal_failure, _completed_result
from app.shared.db import set_node_run_rls_context
from app.shared.errors import (
    NodeRunAlreadyClaimedError,
    ValidationAppError,
)
from app.storage.minio_store import ObjectStore, get_object_store


def identity_priority_keyframe_prompt(
    prompt: str,
    *,
    canonical_locked_prompt: str,
) -> str:
    """Preserve the planned beat while keeping Canonical evidence reviewable."""
    return (
        f"{prompt}\n"
        f"Canonical lead identity: {canonical_locked_prompt}\n"
        "Identity reference priority: depict exactly one adult lead character. "
        "Keep the requested action, wardrobe, lighting, and setting, but make the "
        "lead's unobscured face clearly visible in a front or three-quarter view. "
        "The face must be in sharp focus and occupy a substantial, recognizable "
        "portion of the vertical frame; no profile-only face, no back-facing pose, "
        "no sunglasses, mask, hands, hair, phone, or shadow obscuring the face."
    )


async def claim_media_node_run(
    session: AsyncSession,
    *,
    node_run_id: UUID,
) -> NodeRun:
    """Durably claim a queued NodeRun before any Provider side effect."""
    from datetime import UTC, datetime

    run = await session.get(NodeRun, node_run_id)
    if run is None:
        raise ValidationAppError("node_run not found")
    if run.status in {"completed", "cached", "completed_after_cancel"}:
        return run

    claimed = await session.execute(
        update(NodeRun)
        .where(NodeRun.id == node_run_id, NodeRun.status == "queued")
        .values(status="running", started_at=datetime.now(UTC))
        .returning(NodeRun.id)
    )
    if claimed.scalar_one_or_none() is None:
        await session.refresh(run)
        if run.status in {"completed", "cached", "completed_after_cancel"}:
            return run
        if run.status in {"running", "cancel_requested"}:
            resumable = await session.scalar(
                select(ProviderOperation.id).where(
                    ProviderOperation.node_run_id == run.id,
                    ProviderOperation.provider_operation_id.is_not(None),
                    ProviderOperation.status.in_(
                        {"submitted", "running", "timed_out", "cancel_requested"}
                    ),
                )
            )
            if resumable is not None:
                return run
            raise NodeRunAlreadyClaimedError()
        raise ValidationAppError(f"node_run cannot execute from status={run.status}")

    await session.commit()
    await set_node_run_rls_context(session, node_run_id=run.id)
    await session.refresh(run)
    return run


async def execute_media_node_run(
    session: AsyncSession,
    *,
    node_run_id: UUID,
    store: ObjectStore | None = None,
    require_canonical: bool = False,
    canonical_image_bytes: bytes | None = None,
    already_claimed: bool = False,
) -> ExecuteNodeResult:
    """Worker entry for shot-p0-v1 media nodes. Never called from user Route."""
    from datetime import UTC, datetime

    run = await session.get(NodeRun, node_run_id)
    if run is None:
        raise ValidationAppError("node_run not found")
    node = await session.get(GraphNode, run.graph_node_id)
    if node is None:
        raise ValidationAppError("graph_node not found")
    node_type = node.node_type

    if run.status in {"completed", "cached", "completed_after_cancel"}:
        return await _completed_result(session, run=run, node_type=node_type)

    if already_claimed:
        if run.status not in {"running", "cancel_requested"}:
            raise ValidationAppError(f"claimed node_run cannot execute from status={run.status}")
    else:
        now = datetime.now(UTC)
        claimed = await session.execute(
            update(NodeRun)
            .where(NodeRun.id == node_run_id, NodeRun.status == "queued")
            .values(status="running", started_at=now)
            .returning(NodeRun.id)
        )
        if claimed.scalar_one_or_none() is None:
            await session.refresh(run)
            if run.status in {"completed", "cached", "completed_after_cancel"}:
                return await _completed_result(session, run=run, node_type=node_type)
            if run.status == "running":
                raise NodeRunAlreadyClaimedError()
            raise ValidationAppError(f"node_run cannot execute from status={run.status}")

    obj_store = store or get_object_store()
    if node.node_key == "final_film_assembly":
        from app.production.final_film import execute_final_film_node_run

        return await execute_final_film_node_run(
            session,
            run=run,
            node=node,
            obj_store=obj_store,
        )
    if node_type == "composite":
        return await _complete_composite_node(
            session,
            run=run,
            node=node,
            obj_store=obj_store,
        )

    snap = dict(run.input_snapshot or {})
    if node.node_key in {"identity_review", "video_drift_review"}:
        snap = await _bind_review_input_artifacts(session, run=run, node=node)
    canonical_artifact: Artifact | None = None
    # Formal Worker path resolves canonical only from a complete Artifact binding.
    if canonical_image_bytes is None:
        try:
            canonical_artifact, canonical_image_bytes = await _read_bound_artifact(
                session,
                run=run,
                snapshot=snap,
                prefix="canonical",
                store=obj_store,
                artifact_type="image",
            )
        except ValidationAppError:
            canonical_image_bytes = None
    if require_canonical and canonical_image_bytes is None:
        await _commit_terminal_failure(
            session,
            run=run,
            error_code="CANONICAL_REFERENCE_REQUIRED",
            error_summary="canonical reference required",
        )
        raise ValidationAppError("CANONICAL_REFERENCE_REQUIRED")

    lead_identity_required = snap.get("lead_identity_required") is True
    canonical_artifact_id = snap.get("canonical_artifact_id")
    has_canonical_binding = isinstance(canonical_artifact_id, str) and bool(canonical_artifact_id)
    missing_bound_canonical = (
        node_type == "keyframe"
        and lead_identity_required
        and (not has_canonical_binding or canonical_image_bytes is None)
    )
    if missing_bound_canonical:
        await _commit_terminal_failure(
            session,
            run=run,
            error_code="CANONICAL_REFERENCE_REQUIRED",
            error_summary="lead keyframe requires canonical reference image",
        )
        raise ValidationAppError("CANONICAL_REFERENCE_REQUIRED")

    plan_snapshot = snap.get("plan")
    prompt = str(plan_snapshot or {})
    if isinstance(plan_snapshot, dict):
        prompt = str(plan_snapshot.get("prompt", prompt))
    else:
        prompt = str(snap.get("prompt", f"{node_type}:{run.id}"))

    # Pure review / compose nodes: no Provider, zero cost, document/image result.
    PURE_NODES = {
        "identity_review",
        "video_review",
        "continuity_review",
        "prompt_compose",
        "prompt",
        "subtitle",
    }
    if node_type in PURE_NODES or node.node_key in {
        "identity_review",
        "video_drift_review",
        "continuity_review",
        "prompt",
        "subtitle",
    }:
        if node.node_key in {"identity_review", "video_drift_review"} or node_type in {
            "identity_review",
            "video_review",
        }:
            validate_identity_evidence_policy(snap)
        return await _complete_pure_node(
            session,
            run=run,
            node=node,
            node_type=node_type,
            snap=snap,
            obj_store=obj_store,
            canonical_image_bytes=canonical_image_bytes,
            prompt=prompt,
        )

    project = await session.scalar(select(Project).where(Project.id == run.project_id))
    if project is None:
        raise ValidationAppError("project not found for node run")
    if await set_node_run_rls_context(session, node_run_id=run.id) is None:
        raise ValidationAppError("node_run ownership context unavailable")

    _unified_op = await session.scalar(
        select(ProviderOperation)
        .where(
            ProviderOperation.node_run_id == run.id,
            ProviderOperation.execution_path_version == UNIFIED_PATH_VERSION,
        )
        .order_by(ProviderOperation.attempt_no.desc(), ProviderOperation.created_at.desc())
        .limit(1)
    )
    if node_type == "voice":
        from app.execution.voice_path import execute_voice_node_run

        return await execute_voice_node_run(
            session,
            run=run,
            node=node,
            snapshot=snap,
            store=obj_store,
            prompt=prompt,
        )
    # Keyframe and video are always executed by the unified compiler/runtime.
    if _unified_op is not None or node_type in {"keyframe", "video"}:
        return await _execute_unified_media_node_run(
            session,
            run=run,
            node=node,
            node_type=node_type,
            snap=snap,
            obj_store=obj_store,
            prompt=prompt,
            canonical_image_bytes=canonical_image_bytes,
            lead_identity_required=lead_identity_required,
            has_canonical_binding=has_canonical_binding,
            canonical_artifact=canonical_artifact,
        )
    raise ValidationAppError(f"unsupported executable node type: {node_type}")
