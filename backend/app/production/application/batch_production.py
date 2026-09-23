"""Application service for project/scene batch production.

The preview is read-only. Dispatch requires an exact preview fingerprint, a
positive provider-call ceiling and an explicit Owner acknowledgement. Every
shot still enters the canonical Workbench command path; there is no second
batch runtime or alternate generation truth.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.access.projects import ProjectService
from app.assets.models import Shot
from app.contracts.production_commands import ExecutionBody
from app.execution.models import Artifact, NodeRun
from app.production.application.commands import ProductionCommands
from app.production.execution_plan import WorkbenchExecutionPlan
from app.production.formal_selection import list_formal_candidates
from app.production.trace_query import load_scene_execution_traces
from app.production.workbench_execution import (
    PlanStage,
    WorkbenchExecutionInput,
    WorkbenchExecutionService,
)
from app.shared.errors import AppError, ConflictError, ValidationAppError


class BatchPreviewItemRead(BaseModel):
    shot_id: UUID
    scene_id: UUID
    shot_number: int
    ready: bool
    blocker: str | None = None
    plan_fingerprint: str | None = None
    resolved_model_id: str | None = None


class BatchProductionPreviewRead(BaseModel):
    project_id: UUID
    scene_id: UUID | None
    stage: PlanStage
    fingerprint: str
    estimated_provider_calls: int
    blocked_count: int
    currently_queued: int
    estimated_queue_seconds: int | None
    items: list[BatchPreviewItemRead]


class BatchProductionDispatchBody(BaseModel):
    stage: PlanStage
    scene_id: UUID | None = None
    preview_fingerprint: str = Field(min_length=64, max_length=64)
    batch_key: str = Field(min_length=1, max_length=120)
    max_provider_calls: int = Field(ge=1, le=500)
    max_cost_per_call: Decimal = Field(gt=0, max_digits=12, decimal_places=4)
    currency: Literal["CNY", "USD"]
    owner_authorized: Literal[True]


class BatchProductionDispatchRead(BaseModel):
    preview_fingerprint: str
    accepted_count: int
    node_run_ids: list[UUID]
    statuses: list[str]


class ProductionTodoRead(BaseModel):
    shot_id: UUID
    scene_id: UUID
    shot_number: int
    category: Literal[
        "not_generated",
        "generating",
        "awaiting_review",
        "awaiting_formal",
        "failed",
    ]
    stage: PlanStage
    detail: str
    artifact_id: UUID | None = None


class ConsistencyRiskRead(BaseModel):
    shot_id: UUID
    scene_id: UUID
    layer: str
    severity: str
    code: str
    message: str


class ProductionTodoQueueRead(BaseModel):
    project_id: UUID
    counts: dict[str, int]
    items: list[ProductionTodoRead]
    consistency_risks: list[ConsistencyRiskRead]


def _prompt(shot: Shot, stage: PlanStage) -> str:
    configured = shot.image_prompt if stage == "image_keyframe" else shot.video_prompt
    return (configured or "").strip() or shot.visual_description.strip()


def _reason(error: Exception) -> str:
    if isinstance(error, AppError):
        code = error.details.get("code")
        if isinstance(code, str) and code:
            return code
        return error.code
    return "BATCH_PREFLIGHT_UNAVAILABLE"


def _consistency_facts(shot: Shot) -> dict[str, str]:
    """Return only explicitly frozen facts; absence never becomes a risk."""

    state = dict(shot.director_state or {})
    visual = state.get("visual_style")
    visual_state = visual if isinstance(visual, dict) else {}

    def scalar(*values: object) -> str | None:
        for value in values:
            if isinstance(value, (str, int, float)) and str(value).strip():
                return str(value).strip()
        return None

    facts: dict[str, str] = {}
    direct = {
        "era": scalar(state.get("era"), state.get("period"), visual_state.get("era")),
        "tone": scalar(
            state.get("tone"),
            state.get("color_tone"),
            state.get("palette"),
            visual_state.get("tone"),
            visual_state.get("palette"),
        ),
        "aspect_ratio": scalar(state.get("aspect_ratio"), visual_state.get("aspect_ratio")),
    }
    facts.update({key: value for key, value in direct.items() if value is not None})
    return facts


async def _queue_estimate(session: AsyncSession, project_id: UUID) -> tuple[int, int | None]:
    rows = (
        (
            await session.execute(
                select(NodeRun)
                .where(NodeRun.project_id == project_id)
                .order_by(NodeRun.created_at.desc())
                .limit(2000)
            )
        )
        .scalars()
        .all()
    )
    media = [
        row
        for row in rows
        if str((row.input_snapshot or {}).get("node_key") or "") in {"keyframe", "video"}
    ]
    queued = sum(1 for row in media if row.status == "queued")
    durations = [
        (row.finished_at - row.started_at).total_seconds()
        for row in media
        if row.started_at is not None
        and row.finished_at is not None
        and row.finished_at >= row.started_at
        and row.status in {"completed", "cached", "completed_after_cancel"}
    ][:50]
    estimate = round(queued * (sum(durations) / len(durations))) if durations else None
    return queued, estimate


async def _prepare(
    session: AsyncSession,
    *,
    project: Project,
    user_id: UUID,
    stage: PlanStage,
    scene_id: UUID | None,
) -> tuple[
    BatchProductionPreviewRead,
    dict[UUID, tuple[WorkbenchExecutionInput, WorkbenchExecutionPlan]],
]:
    statement = select(Shot).where(Shot.project_id == project.id)
    if scene_id is not None:
        statement = statement.where(Shot.scene_id == scene_id)
    shots = (
        (
            await session.execute(
                statement.order_by(Shot.scene_id, Shot.sort_order, Shot.shot_number)
            )
        )
        .scalars()
        .all()
    )

    active_rows = (
        (
            await session.execute(
                select(NodeRun).where(
                    NodeRun.project_id == project.id,
                    NodeRun.status.in_(("queued", "running", "cancel_requested")),
                )
            )
        )
        .scalars()
        .all()
    )
    node_key = "keyframe" if stage == "image_keyframe" else "video"
    active_shots = {
        str((row.input_snapshot or {}).get("shot_id"))
        for row in active_rows
        if str((row.input_snapshot or {}).get("node_key") or "") == node_key
    }
    service = WorkbenchExecutionService(session, user_id=user_id)
    prepared: dict[UUID, tuple[WorkbenchExecutionInput, WorkbenchExecutionPlan]] = {}
    items: list[BatchPreviewItemRead] = []
    for shot in shots:
        already_formal = (
            shot.formal_keyframe_artifact_id is not None
            if stage == "image_keyframe"
            else shot.formal_video_artifact_id is not None
        )
        if already_formal:
            continue
        if str(shot.id) in active_shots:
            items.append(
                BatchPreviewItemRead(
                    shot_id=shot.id,
                    scene_id=shot.scene_id,
                    shot_number=shot.shot_number,
                    ready=False,
                    blocker="STAGE_ALREADY_ACTIVE",
                )
            )
            continue
        prompt = _prompt(shot, stage)
        if not prompt:
            items.append(
                BatchPreviewItemRead(
                    shot_id=shot.id,
                    scene_id=shot.scene_id,
                    shot_number=shot.shot_number,
                    ready=False,
                    blocker="SHOT_PROMPT_REQUIRED",
                )
            )
            continue
        try:
            references = await service.saved_shot_references(
                project=project, shot_id=shot.id, stage=stage
            )
            execution_input = WorkbenchExecutionInput(
                project_id=project.id,
                shot_id=shot.id,
                stage=stage,
                prompt=prompt,
                semantic_intent={},
                mode_id="text_to_image" if stage == "image_keyframe" else "first_frame",
                references=references,
                expected_shot_version=shot.version,
            )
            plan = await service.build_plan(project=project, execution_input=execution_input)
        except Exception as exc:  # noqa: BLE001 - blockers belong in the preview
            items.append(
                BatchPreviewItemRead(
                    shot_id=shot.id,
                    scene_id=shot.scene_id,
                    shot_number=shot.shot_number,
                    ready=False,
                    blocker=_reason(exc),
                )
            )
            continue
        prepared[shot.id] = (execution_input, plan)
        items.append(
            BatchPreviewItemRead(
                shot_id=shot.id,
                scene_id=shot.scene_id,
                shot_number=shot.shot_number,
                ready=True,
                plan_fingerprint=plan.plan_fingerprint,
                resolved_model_id=plan.resolved_model.resolved_model_id,
            )
        )

    fingerprint_payload = {
        "project_id": str(project.id),
        "scene_id": str(scene_id) if scene_id else None,
        "stage": stage,
        "items": [item.model_dump(mode="json") for item in items],
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    currently_queued, estimated_queue_seconds = await _queue_estimate(session, project.id)
    preview = BatchProductionPreviewRead(
        project_id=project.id,
        scene_id=scene_id,
        stage=stage,
        fingerprint=fingerprint,
        estimated_provider_calls=len(prepared),
        blocked_count=sum(1 for item in items if not item.ready),
        currently_queued=currently_queued,
        estimated_queue_seconds=estimated_queue_seconds,
        items=items,
    )
    return preview, prepared


async def preview_batch_production(
    project_id: UUID,
    user: User,
    session: AsyncSession,
    stage: PlanStage,
    scene_id: UUID | None = None,
) -> BatchProductionPreviewRead:
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    preview, _prepared = await _prepare(
        session,
        project=project,
        user_id=user.id,
        stage=stage,
        scene_id=scene_id,
    )
    return preview


async def read_production_todos(
    project_id: UUID,
    user: User,
    session: AsyncSession,
) -> ProductionTodoQueueRead:
    """Classify every unfinished shot by its next server-fact-driven action."""

    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    shots = (
        (
            await session.execute(
                select(Shot)
                .where(Shot.project_id == project.id)
                .order_by(Shot.scene_id, Shot.sort_order, Shot.shot_number)
            )
        )
        .scalars()
        .all()
    )
    shot_ids = [shot.id for shot in shots]
    candidates = await list_formal_candidates(session, project_id=project.id, shot_ids=shot_ids)
    traces = await load_scene_execution_traces(session, project_id=project.id, shot_ids=shot_ids)
    items: list[ProductionTodoRead] = []
    for shot in shots:
        if shot.formal_video_artifact_id is not None:
            continue
        stage: PlanStage = "image_keyframe" if shot.formal_keyframe_artifact_id is None else "video"
        node_key = "keyframe" if stage == "image_keyframe" else "video"
        latest = next(
            (trace for trace in traces.get(shot.id, []) if trace.node_key == node_key),
            None,
        )
        stage_candidates = [
            candidate
            for candidate in candidates.get(shot.id, [])
            if candidate.get("stage") == stage
        ]
        category: Literal[
            "not_generated",
            "generating",
            "awaiting_review",
            "awaiting_formal",
            "failed",
        ]
        if latest is not None and latest.status in {"queued", "running", "cancel_requested"}:
            category = "generating"
            detail = latest.status
        elif any(candidate.get("review_allowed") is True for candidate in stage_candidates):
            category = "awaiting_formal"
            detail = "REVIEW_APPROVED"
        elif stage_candidates:
            category = "awaiting_review"
            detail = str(stage_candidates[0].get("review_blocked_reason") or "REVIEW_REQUIRED")
        elif latest is not None and latest.status in {
            "failed",
            "blocked",
            "cancelled",
            "timed_out",
            "rejected",
        }:
            category = "failed"
            detail = latest.error_code or latest.status
        else:
            category = "not_generated"
            detail = "NO_CANDIDATE"
        items.append(
            ProductionTodoRead(
                shot_id=shot.id,
                scene_id=shot.scene_id,
                shot_number=shot.shot_number,
                category=category,
                stage=stage,
                detail=detail,
                artifact_id=(
                    UUID(str(stage_candidates[0]["artifact_id"]))
                    if stage_candidates and stage_candidates[0].get("artifact_id")
                    else None
                ),
            )
        )
    counts: dict[str, int] = {}
    for item in items:
        counts[item.category] = counts.get(item.category, 0) + 1
    risks: list[ConsistencyRiskRead] = []
    formal_ids = [
        shot.formal_keyframe_artifact_id
        for shot in shots
        if shot.formal_keyframe_artifact_id is not None
    ]
    artifacts = {
        artifact.id: artifact
        for artifact in (
            (await session.execute(select(Artifact).where(Artifact.id.in_(formal_ids))))
            .scalars()
            .all()
            if formal_ids
            else []
        )
    }
    previous_by_scene: dict[UUID, tuple[Shot, str]] = {}
    previous_facts_by_scene: dict[UUID, tuple[Shot, dict[str, str]]] = {}
    for shot in shots:
        facts = _consistency_facts(shot)
        explicit_ratio = facts.get("aspect_ratio")
        if explicit_ratio is not None and explicit_ratio != project.aspect_ratio:
            risks.append(
                ConsistencyRiskRead(
                    shot_id=shot.id,
                    scene_id=shot.scene_id,
                    layer="aspect_ratio",
                    severity="warning",
                    code="SHOT_ASPECT_RATIO_MISMATCH",
                    message=(
                        f"镜头 {shot.shot_number} 冻结画幅 {explicit_ratio}，"
                        f"与作品画幅 {project.aspect_ratio} 不一致"
                    ),
                )
            )
        previous_facts = previous_facts_by_scene.get(shot.scene_id)
        if previous_facts is not None:
            for layer in ("era", "tone", "aspect_ratio"):
                previous_value = previous_facts[1].get(layer)
                current_value = facts.get(layer)
                if (
                    previous_value is None
                    or current_value is None
                    or previous_value == current_value
                ):
                    continue
                risks.append(
                    ConsistencyRiskRead(
                        shot_id=shot.id,
                        scene_id=shot.scene_id,
                        layer=layer,
                        severity="warning",
                        code=f"ADJACENT_{layer.upper()}_MISMATCH",
                        message=(
                            f"同场景镜头 {previous_facts[0].shot_number} 与镜头 "
                            f"{shot.shot_number} 的 {layer} 冻结事实不一致"
                        ),
                    )
                )
        previous_facts_by_scene[shot.scene_id] = (shot, facts)
        formal_keyframe_id = shot.formal_keyframe_artifact_id
        if formal_keyframe_id is None:
            continue
        artifact = artifacts.get(formal_keyframe_id)
        if artifact is None:
            continue
        previous = previous_by_scene.get(shot.scene_id)
        if previous is not None and previous[1] == artifact.content_hash:
            risks.append(
                ConsistencyRiskRead(
                    shot_id=shot.id,
                    scene_id=shot.scene_id,
                    layer="visual",
                    severity="warning",
                    code="ADJACENT_KEYFRAME_DUPLICATE",
                    message=(
                        f"镜头 {previous[0].shot_number} 与镜头 {shot.shot_number} "
                        "的正式关键帧内容哈希完全相同"
                    ),
                )
            )
        previous_by_scene[shot.scene_id] = (shot, artifact.content_hash)

    continuity_runs = (
        (
            await session.execute(
                select(NodeRun)
                .where(NodeRun.project_id == project.id)
                .order_by(NodeRun.created_at.desc())
                .limit(2000)
            )
        )
        .scalars()
        .all()
    )
    seen_continuity: set[UUID] = set()
    shot_by_id = {shot.id: shot for shot in shots}
    for run in continuity_runs:
        snapshot = dict(run.input_snapshot or {})
        if snapshot.get("node_key") != "continuity_review":
            continue
        try:
            run_shot_id = UUID(str(snapshot.get("shot_id")))
        except (TypeError, ValueError):
            continue
        if run_shot_id in seen_continuity or run_shot_id not in shot_by_id:
            continue
        shot = shot_by_id[run_shot_id]
        if (
            run.status not in {"completed", "cached", "completed_after_cancel"}
            or run.result_artifact_id is None
            or run.finished_at is None
            or (shot.updated_at is not None and run.finished_at < shot.updated_at)
        ):
            continue
        seen_continuity.add(run_shot_id)
        violations = (run.output_summary or {}).get("violations")
        if not isinstance(violations, list):
            continue
        for violation in violations:
            if not isinstance(violation, dict):
                continue
            risks.append(
                ConsistencyRiskRead(
                    shot_id=shot.id,
                    scene_id=shot.scene_id,
                    layer=str(violation.get("layer") or "continuity"),
                    severity=str(violation.get("severity") or "warning"),
                    code=str(violation.get("rule_key") or "CONTINUITY_RISK"),
                    message=str(violation.get("message") or "跨镜头一致性检查发现风险"),
                )
            )
    return ProductionTodoQueueRead(
        project_id=project.id,
        counts=counts,
        items=items,
        consistency_risks=risks,
    )


async def dispatch_batch_production(
    project_id: UUID,
    body: BatchProductionDispatchBody,
    user: User,
    session: AsyncSession,
) -> BatchProductionDispatchRead:
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    preview, prepared = await _prepare(
        session,
        project=project,
        user_id=user.id,
        stage=body.stage,
        scene_id=body.scene_id,
    )
    if preview.fingerprint != body.preview_fingerprint:
        raise ConflictError(
            "batch preview changed; review the current calls and blockers",
            details={"code": "BATCH_PREVIEW_STALE", "current": preview.fingerprint},
        )
    if not prepared:
        raise ConflictError("batch has no executable shots", details={"code": "BATCH_EMPTY"})
    if len(prepared) > body.max_provider_calls:
        raise ValidationAppError(
            "batch exceeds the authorized provider-call ceiling",
            details={
                "code": "BATCH_CALL_BUDGET_EXCEEDED",
                "required_calls": len(prepared),
                "max_provider_calls": body.max_provider_calls,
            },
        )
    commands = ProductionCommands(session)
    run_ids: list[UUID] = []
    statuses: list[str] = []
    authorized_at = datetime.now(UTC).isoformat()
    authorized_count = len(prepared)
    for call_index, (shot_id, (execution_input, plan)) in enumerate(prepared.items(), start=1):
        if not plan.plan_fingerprint:
            raise ValidationAppError("batch plan has no fingerprint")
        receipt = await commands.submit_user_execution(
            actor=user,
            project_id=project.id,
            shot_id=shot_id,
            body=ExecutionBody(
                **execution_input.model_dump(
                    exclude={"project_id", "shot_id", "shot_experiment_id"}
                ),
                plan_fingerprint=plan.plan_fingerprint,
                accepted_approximations=plan.accepted_approximations,
            ),
            command_key=f"batch:{body.batch_key}:{shot_id}",
        )
        run = await session.get(NodeRun, receipt.node_run_id)
        if run is None:
            raise ConflictError(
                "accepted batch run could not be loaded",
                details={"code": "BATCH_RUN_MISSING", "node_run_id": str(receipt.node_run_id)},
            )
        # Paid authorization is persisted on every concrete operation. A batch
        # acknowledgement is never treated as open-ended or reusable consent.
        snapshot = dict(run.input_snapshot or {})
        snapshot["paid_authorization"] = {
            "kind": "batch_owner_authorization",
            "batch_key": body.batch_key,
            "authorized_by": str(user.id),
            "authorized_at": authorized_at,
            "call_index": call_index,
            "authorized_call_count": authorized_count,
            "max_cost_per_call": str(body.max_cost_per_call),
            "currency": body.currency,
        }
        run.input_snapshot = snapshot
        run_ids.append(receipt.node_run_id)
        statuses.append(receipt.status)
    await session.commit()
    return BatchProductionDispatchRead(
        preview_fingerprint=preview.fingerprint,
        accepted_count=len(run_ids),
        node_run_ids=run_ids,
        statuses=statuses,
    )
