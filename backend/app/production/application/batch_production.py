"""Application service for project/scene batch production ("补齐").

The preview is read-only and classifies every shot in scope as ``ready``,
``skipped`` or ``blocked``. Dispatch requires an exact preview fingerprint, a
positive ceiling on newly created provider operations and an explicit Owner
acknowledgement. Provider pricing is managed by the provider account;
DramaForge only bounds how many new operations one confirmation may create.
Every shot still enters the canonical Workbench command path; there is no
second batch runtime or alternate generation truth.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
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

BatchDisposition = Literal["ready", "skipped", "blocked"]


class BatchPreviewItemRead(BaseModel):
    shot_id: UUID
    scene_id: UUID
    shot_number: int
    disposition: BatchDisposition
    # ``None`` only for ready items. Skipped reasons are fixed codes
    # (ALREADY_FORMAL, STAGE_ALREADY_ACTIVE, CANDIDATE_AWAITING_REVIEW,
    # CANDIDATE_AWAITING_FORMAL, FORMAL_KEYFRAME_REQUIRED);
    # blocked reasons carry the preflight / resolver error code.
    reason: str | None = None
    plan_fingerprint: str | None = None
    resolved_model_id: str | None = None


class BatchProductionPreviewRead(BaseModel):
    project_id: UUID
    scene_id: UUID | None
    stage: PlanStage
    fingerprint: str
    ready_count: int
    skipped_count: int
    blocked_count: int
    items: list[BatchPreviewItemRead]


class BatchProductionDispatchBody(BaseModel):
    stage: PlanStage
    scene_id: UUID | None = None
    preview_fingerprint: str = Field(min_length=64, max_length=64)
    batch_key: str = Field(min_length=1, max_length=120)
    max_provider_calls: int = Field(ge=1, le=500)
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


async def _prepare(
    session: AsyncSession,
    *,
    project: Project,
    user_id: UUID,
    stage: PlanStage,
    scene_id: UUID | None,
) -> tuple[
    BatchProductionPreviewRead,
    dict[UUID, tuple[WorkbenchExecutionInput, WorkbenchExecutionPlan, str]],
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
    candidates = await list_formal_candidates(
        session, project_id=project.id, shot_ids=[shot.id for shot in shots]
    )
    service = WorkbenchExecutionService(session, user_id=user_id)
    prepared: dict[UUID, tuple[WorkbenchExecutionInput, WorkbenchExecutionPlan, str]] = {}
    items: list[BatchPreviewItemRead] = []

    def not_ready(shot: Shot, disposition: BatchDisposition, reason: str) -> None:
        items.append(
            BatchPreviewItemRead(
                shot_id=shot.id,
                scene_id=shot.scene_id,
                shot_number=shot.shot_number,
                disposition=disposition,
                reason=reason,
            )
        )

    for shot in shots:
        # "补齐" only fills gaps: shots that already have the stage's formal
        # output, a successful candidate, or an in-flight run are skipped.
        already_formal = (
            shot.formal_keyframe_artifact_id is not None
            if stage == "image_keyframe"
            else shot.formal_video_artifact_id is not None
        )
        if already_formal:
            not_ready(shot, "skipped", "ALREADY_FORMAL")
            continue
        if str(shot.id) in active_shots:
            not_ready(shot, "skipped", "STAGE_ALREADY_ACTIVE")
            continue
        stage_candidates = [
            candidate
            for candidate in candidates.get(shot.id, [])
            if candidate.get("stage") == stage
        ]
        if stage_candidates:
            # "补齐" only fills gaps, so a stage holding any candidate stays
            # skipped — including human-rejected ones: replacing a rejected
            # artifact is a paid create and must stay an explicit single
            # create decision, never an implicit batch overwrite. The reason
            # distinguishes what the user is actually looking at.
            if any(candidate.get("review_allowed") is True for candidate in stage_candidates):
                reason = "CANDIDATE_AWAITING_FORMAL"
            elif all(
                candidate.get("review_decision") == "rejected" for candidate in stage_candidates
            ):
                reason = "CANDIDATE_REJECTED"
            else:
                reason = "CANDIDATE_AWAITING_REVIEW"
            not_ready(shot, "skipped", reason)
            continue
        if stage == "video" and shot.formal_keyframe_artifact_id is None:
            not_ready(shot, "skipped", "FORMAL_KEYFRAME_REQUIRED")
            continue
        prompt = _prompt(shot, stage)
        if not prompt:
            not_ready(shot, "blocked", "SHOT_PROMPT_REQUIRED")
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
            compiler = await service.preview_compiler_contract(project=project, plan=plan)
            if (
                compiler is None
                or compiler.readiness != "contract_validated"
                or compiler.wire_fingerprint is None
            ):
                raise ValidationAppError(
                    "batch model Compiler proof is not ready",
                    details={"code": "COMPILER_WIRE_CONFIRMATION_REQUIRED"},
                )
        except Exception as exc:  # noqa: BLE001 - blockers belong in the preview
            not_ready(shot, "blocked", _reason(exc))
            continue
        prepared[shot.id] = (execution_input, plan, compiler.wire_fingerprint)
        items.append(
            BatchPreviewItemRead(
                shot_id=shot.id,
                scene_id=shot.scene_id,
                shot_number=shot.shot_number,
                disposition="ready",
                plan_fingerprint=plan.plan_fingerprint,
                resolved_model_id=plan.resolved_model.resolved_model_id,
            )
        )

    fingerprint_payload = {
        "project_id": str(project.id),
        "scene_id": str(scene_id) if scene_id else None,
        "stage": stage,
        "items": [item.model_dump(mode="json") for item in items],
        # Bind invisible, immutable Compiler proof into the Owner-approved
        # preview hash without exposing a second wire contract in the API.
        "compiler_proofs": {
            str(shot_id): proof for shot_id, (_input, _plan, proof) in prepared.items()
        },
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    preview = BatchProductionPreviewRead(
        project_id=project.id,
        scene_id=scene_id,
        stage=stage,
        fingerprint=fingerprint,
        ready_count=len(prepared),
        skipped_count=sum(1 for item in items if item.disposition == "skipped"),
        blocked_count=sum(1 for item in items if item.disposition == "blocked"),
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
        selected_candidate = next(
            (
                candidate
                for candidate in stage_candidates
                if candidate.get("review_allowed") is True
            ),
            None,
        )
        if selected_candidate is None:
            selected_candidate = next(
                (
                    candidate
                    for candidate in stage_candidates
                    if candidate.get("review_decision") != "rejected"
                ),
                stage_candidates[0] if stage_candidates else None,
            )
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
        elif selected_candidate is not None and selected_candidate.get("review_allowed") is True:
            category = "awaiting_formal"
            detail = "REVIEW_APPROVED"
        elif selected_candidate is not None:
            category = "awaiting_review"
            if selected_candidate.get("review_decision") == "rejected":
                detail = "CANDIDATE_REJECTED"
            else:
                detail = str(selected_candidate.get("review_blocked_reason") or "REVIEW_REQUIRED")
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
                    UUID(str(selected_candidate["artifact_id"]))
                    if selected_candidate is not None and selected_candidate.get("artifact_id")
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


async def _recorded_batch_runs(
    session: AsyncSession,
    *,
    project_id: UUID,
    field: Literal["batch_key", "preview_fingerprint"],
    value: str,
) -> list[NodeRun]:
    """Read the frozen authorization journal without inventing a second table."""
    column = NodeRun.input_snapshot["paid_authorization"][field].as_string()
    return list(
        (
            await session.scalars(
                select(NodeRun)
                .where(NodeRun.project_id == project_id, column == value)
                .order_by(NodeRun.created_at, NodeRun.id)
            )
        ).all()
    )


async def dispatch_batch_production(
    project_id: UUID,
    body: BatchProductionDispatchBody,
    user: User,
    session: AsyncSession,
) -> BatchProductionDispatchRead:
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    # Ownership is authenticated by the session, not by owner_authorized's
    # client-supplied acknowledgement. The project lock covers replay lookup,
    # preview recomputation and acceptance in one serialized transaction.
    await WorkbenchExecutionService(session, user_id=user.id).lock_command_scope(
        project_id=project.id,
    )
    prior = await _recorded_batch_runs(
        session,
        project_id=project.id,
        field="batch_key",
        value=body.batch_key,
    )
    if prior:
        frozen = [(run.input_snapshot or {}).get("paid_authorization") for run in prior]
        if not all(isinstance(item, dict) for item in frozen):
            raise ConflictError(
                "batch contains invalid frozen authorization facts",
                details={"code": "BATCH_AUTHORIZATION_REPLAY_CONFLICT"},
            )
        verified = [item for item in frozen if isinstance(item, dict)]
        if (
            any(
                item.get("preview_fingerprint") != body.preview_fingerprint
                or item.get("stage") != body.stage
                or item.get("authorized_by") != str(user.id)
                or item.get("authorized_call_count") != len(prior)
                for item in verified
            )
            or {item.get("call_index") for item in verified} != set(range(1, len(prior) + 1))
            or len(prior) > body.max_provider_calls
        ):
            raise ConflictError(
                "batch key has already been used for a different confirmation",
                details={"code": "BATCH_AUTHORIZATION_REPLAY_CONFLICT"},
            )
        return BatchProductionDispatchRead(
            preview_fingerprint=body.preview_fingerprint,
            accepted_count=len(prior),
            node_run_ids=[run.id for run in prior],
            statuses=[run.status for run in prior],
        )

    # Check the frozen confirmation before recomputing: the winning dispatch
    # changes shot state, so a competing key must report an already-consumed
    # confirmation rather than letting that state change hide the journal.
    already_accepted = await _recorded_batch_runs(
        session,
        project_id=project.id,
        field="preview_fingerprint",
        value=body.preview_fingerprint,
    )
    if already_accepted:
        raise ConflictError(
            "this batch preview has already been authorized",
            details={"code": "BATCH_PREVIEW_ALREADY_AUTHORIZED"},
        )

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
            "batch exceeds the authorized provider-operation limit",
            details={
                "code": "BATCH_CALL_LIMIT_EXCEEDED",
                "required_calls": len(prepared),
                "max_provider_calls": body.max_provider_calls,
            },
        )
    commands = ProductionCommands(session)
    run_ids: list[UUID] = []
    statuses: list[str] = []
    authorized_at = datetime.now(UTC).isoformat()
    authorized_count = len(prepared)
    for call_index, (shot_id, (execution_input, plan, compiler_proof)) in enumerate(
        prepared.items(), start=1
    ):
        if not plan.plan_fingerprint:
            raise ValidationAppError("batch plan has no fingerprint")
        receipt = await commands.submit_user_execution(
            actor=user,
            project_id=project.id,
            shot_id=shot_id,
            body=ExecutionBody(
                **execution_input.model_dump(
                    exclude={"project_id", "shot_id", "experiment_branch_id"}
                ),
                plan_fingerprint=plan.plan_fingerprint,
                compiler_wire_fingerprint=compiler_proof,
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
        # Owner authorization is persisted on every concrete operation. A batch
        # acknowledgement covers exactly this preview and operation count; it is
        # never open-ended or reusable consent. Pricing stays with the provider.
        snapshot = dict(run.input_snapshot or {})
        if "paid_authorization" in snapshot:
            raise ConflictError(
                "run already has a frozen paid authorization",
                details={"code": "BATCH_AUTHORIZATION_ALREADY_FROZEN"},
            )
        snapshot["paid_authorization"] = {
            "kind": "batch_owner_authorization",
            "batch_key": body.batch_key,
            "stage": body.stage,
            "preview_fingerprint": preview.fingerprint,
            "authorized_by": str(user.id),
            "authorized_at": authorized_at,
            "call_index": call_index,
            "authorized_call_count": authorized_count,
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
