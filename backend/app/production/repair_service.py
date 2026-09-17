"""P6-04/05/06 Manual repair service (03 §56-58).

A repair is a user-confirmed staged workflow, never a background rewrite of
production truth. Each confirmed step dispatches one queued NodeRun through the
WorkbenchExecutionService and is persisted so the page can be reopened at any
point. No local inpaint / splice, no automatic Formal replacement.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.assets.models import Shot
from app.delivery.models import ReviewAnnotation
from app.execution.models import NodeRun
from app.production.models import RepairRequest, RepairStep
from app.production.workbench_execution import (
    WorkbenchExecutionInput,
    WorkbenchExecutionService,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

RepairOption = Literal["rerun_video", "regenerate_keyframe_then_video"]

# The staged vocabulary. A step is a product step; execution state still lives
# in its NodeRun, and "needs human decision" is derived from stored facts.
RepairStage = Literal[
    "keyframe_regenerate",
    "keyframe_review",
    "video_rerun",
    "video_review",
    "done",
]

PLAN_SCHEMA_VERSION = 1

STEP_STAGE_BY_OPTION: dict[str, dict[int, str]] = {
    "rerun_video": {1: "video_rerun", 2: "video_review"},
    "regenerate_keyframe_then_video": {
        1: "keyframe_regenerate",
        2: "keyframe_review",
        3: "video_rerun",
        4: "video_review",
    },
}


class RepairPlanRead(BaseModel):
    """Repair plan computed from open annotations (03 §57)."""

    model_config = ConfigDict(extra="forbid")

    shot_id: UUID
    repair_options: list[RepairOption]
    suggested_option: RepairOption
    affected_nodes: list[str]
    retained_assets: list[str]
    expected_rerun_scope: str
    annotation_count: int
    annotation_ids: list[UUID]
    plan_hash: str
    plan_schema_version: int
    steps: list[str]
    cost_estimate_note: str


class RepairStepRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    ordinal: int
    stage: str
    plan_fingerprint: str | None
    command_key: str | None
    node_run_id: UUID | None
    node_run_status: str | None
    result_artifact_id: UUID | None
    confirmed_at: datetime | None
    adopted_artifact_id: UUID | None
    review_decision_id: UUID | None
    next_action: str


class RepairRequestRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    shot_id: UUID
    option: RepairOption
    plan_hash: str
    plan_schema_version: int
    annotation_ids: list[UUID]
    source_formal_artifact_id: UUID | None
    closed_reason: str | None
    created_at: datetime
    steps: list[RepairStepRead]
    next_action: str


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def repair_request_hash(*, plan_hash: str, option: str, annotation_ids: list[str]) -> str:
    return _canonical_hash(
        {"plan_hash": plan_hash, "option": option, "annotation_ids": sorted(annotation_ids)}
    )


class RepairService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build_repair_plan(
        self,
        *,
        project: Project,
        shot_id: UUID,
    ) -> RepairPlanRead:
        """Derive a repair plan from open annotations on the shot."""
        shot = await self._require_shot(project=project, shot_id=shot_id)
        annotations = await self._open_annotations(project=project, shot_id=shot_id)

        has_video_range = any(
            annotation.time_start is not None or annotation.time_end is not None
            for annotation in annotations
        )
        has_region = any(
            annotation.x is not None or annotation.width is not None for annotation in annotations
        )
        has_keyframe = shot.formal_keyframe_artifact_id is not None

        if has_video_range:
            suggested: RepairOption = "regenerate_keyframe_then_video"
            affected = ["keyframe", "video"]
            retained: list[str] = []
            scope = "keyframe_then_video"
        elif has_region and has_keyframe:
            suggested = "rerun_video"
            affected = ["video"]
            retained = ["formal_keyframe"]
            scope = "video"
        else:
            suggested = "rerun_video"
            affected = ["video"]
            retained = []
            scope = "video"

        annotation_ids = [annotation.id for annotation in annotations]
        plan_hash = _canonical_hash(
            {
                "shot_id": str(shot_id),
                "shot_version": shot.version,
                "annotation_ids": [str(value) for value in annotation_ids],
                "formal_keyframe_artifact_id": (
                    str(shot.formal_keyframe_artifact_id)
                    if shot.formal_keyframe_artifact_id
                    else None
                ),
                "formal_video_artifact_id": (
                    str(shot.formal_video_artifact_id)
                    if shot.formal_video_artifact_id
                    else None
                ),
                "option": suggested,
                "schema_version": PLAN_SCHEMA_VERSION,
            }
        )
        return RepairPlanRead(
            shot_id=shot_id,
            repair_options=["rerun_video", "regenerate_keyframe_then_video"],
            suggested_option=suggested,
            affected_nodes=affected,
            retained_assets=retained,
            expected_rerun_scope=scope,
            annotation_count=len(annotations),
            annotation_ids=annotation_ids,
            plan_hash=plan_hash,
            plan_schema_version=PLAN_SCHEMA_VERSION,
            steps=list(STEP_STAGE_BY_OPTION[suggested].values()),
            cost_estimate_note=(
                "修复执行会真实调用已绑定的媒体模型；具体金额取决于所选模型与时长，"
                "此处不做确定性报价。执行前需要本次操作的正数预算授权。"
            ),
        )

    async def create_repair(
        self,
        *,
        project: Project,
        user: User,
        shot_id: UUID,
        option: RepairOption,
        plan_hash: str,
        request_key: str,
    ) -> RepairRequest:
        """Persist a confirmed repair intent after re-checking the plan."""
        if option not in STEP_STAGE_BY_OPTION:
            raise ValidationAppError(
                f"unsupported repair option: {option}",
                details={"code": "REPAIR_OPTION_UNSUPPORTED"},
            )
        key = request_key.strip()
        if not key:
            raise ValidationAppError("Idempotency-Key must not be blank")
        existing = await self._request_by_key(project=project, request_key=key)
        if existing is not None:
            if existing.request_hash != repair_request_hash(
                plan_hash=plan_hash, option=option, annotation_ids=existing.annotation_ids
            ):
                raise ConflictError(
                    "this repair request key was already used with a different request",
                    details={"code": "REPAIR_REQUEST_REUSED", "repair_id": str(existing.id)},
                )
            return existing

        shot = await self._require_shot(project=project, shot_id=shot_id)
        plan = await self.build_repair_plan(project=project, shot_id=shot_id)
        if plan.plan_hash != plan_hash:
            # The annotations, the source assets or the design changed since the
            # preview: the confirmed plan is no longer valid.
            raise ConflictError(
                "repair plan changed since it was previewed; preview it again",
                details={
                    "code": "REPAIR_PLAN_STALE",
                    "expected_plan_hash": plan_hash,
                    "actual_plan_hash": plan.plan_hash,
                },
            )
        request = RepairRequest(
            project_id=project.id,
            shot_id=shot_id,
            created_by=user.id,
            option=option,
            plan_schema_version=PLAN_SCHEMA_VERSION,
            plan_hash=plan.plan_hash,
            annotation_ids=[str(value) for value in plan.annotation_ids],
            annotation_summary={
                "count": plan.annotation_count,
                "affected_nodes": plan.affected_nodes,
                "retained_assets": plan.retained_assets,
            },
            source_formal_artifact_id=(
                shot.formal_video_artifact_id
                if option == "rerun_video"
                else shot.formal_keyframe_artifact_id
            ),
            input_fingerprint=_canonical_hash(
                {
                    "shot_version": shot.version,
                    "image_prompt": shot.image_prompt,
                    "video_prompt": shot.video_prompt,
                    "formal_keyframe_artifact_id": (
                        str(shot.formal_keyframe_artifact_id)
                        if shot.formal_keyframe_artifact_id
                        else None
                    ),
                }
            ),
            request_key=key,
            request_hash=repair_request_hash(
                plan_hash=plan.plan_hash,
                option=option,
                annotation_ids=[str(value) for value in plan.annotation_ids],
            ),
        )
        self._session.add(request)
        await self._session.flush()
        return request

    async def execute_step(
        self,
        *,
        project: Project,
        user: User,
        shot_id: UUID,
        repair_id: UUID,
        expected_plan_fingerprint: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[RepairRequest, RepairStep, NodeRun]:
        """Dispatch the next confirmed step of a repair.

        Keyframe-then-video repairs stop after the keyframe candidate: promoting
        it to Formal and reviewing it stay explicit user actions.
        """
        request = await self._require_request(
            project=project, shot_id=shot_id, repair_id=repair_id
        )
        if request.closed_at is not None:
            raise ConflictError(
                "repair request is closed",
                details={"code": "REPAIR_CLOSED", "reason": request.closed_reason},
            )
        shot = await self._require_shot(project=project, shot_id=shot_id)
        steps = await self._steps(request=request)
        ordinal = len(steps) + 1
        stage = STEP_STAGE_BY_OPTION[request.option].get(ordinal)
        if stage is None:
            raise ConflictError(
                "repair has no further step",
                details={"code": "REPAIR_NO_NEXT_STEP", "option": request.option},
            )
        if stage in {"keyframe_review", "video_review"}:
            raise ValidationAppError(
                "this step is a human decision, not a media action; review it in the review page",
                details={"code": "REPAIR_STEP_REQUIRES_REVIEW", "stage": stage},
            )
        if stage == "video_rerun" and shot.formal_keyframe_artifact_id is None:
            raise ValidationAppError(
                "rerun_video requires a formal keyframe",
                details={"code": "NO_FORMAL_KEYFRAME"},
            )
        if expected_plan_fingerprint and any(
            step.plan_fingerprint and step.plan_fingerprint != expected_plan_fingerprint
            for step in steps
        ):
            raise ConflictError(
                "the confirmed repair plan fingerprint does not match the stored steps",
                details={"code": "REPAIR_STEP_PLAN_MISMATCH"},
            )

        service = WorkbenchExecutionService(self._session, user_id=user.id)
        command_key = idempotency_key or f"{request.id}:{ordinal}"
        node_key = "keyframe" if stage == "keyframe_regenerate" else "video"
        execution_input = WorkbenchExecutionInput(
            project_id=project.id,
            shot_id=shot_id,
            stage="image_keyframe" if node_key == "keyframe" else "video",
            prompt=(
                (shot.image_prompt or shot.visual_description).strip()
                if node_key == "keyframe"
                else (shot.video_prompt or shot.visual_description).strip()
            ),
            semantic_intent={
                "intent": "shot_keyframe" if node_key == "keyframe" else "shot_video",
                "repair": request.option,
                "repair_request_id": str(request.id),
                "repair_step": ordinal,
            },
            mode_id="explicit_binding",
            expected_shot_version=shot.version,
        )
        run = await service.create_and_dispatch(
            project=project,
            execution_input=execution_input,
            idempotency_key_override=f"repair:{command_key}",
        )
        step = RepairStep(
            repair_request_id=request.id,
            project_id=project.id,
            ordinal=ordinal,
            stage=stage,
            plan_fingerprint=run.input_snapshot.get("plan_fingerprint")
            if isinstance(run.input_snapshot, dict)
            else None,
            command_key=command_key,
            node_run_id=run.id,
            confirmed_by=user.id,
            confirmed_at=datetime.now(UTC),
        )
        self._session.add(step)
        await self._session.flush()
        return request, step, run

    async def execute_repair(
        self,
        *,
        project: Project,
        user: User,
        shot_id: UUID,
        repair_option: RepairOption,
        idempotency_key: str,
    ) -> NodeRun:
        """Confirm the current plan and dispatch its first step; return that run.

        Kept for callers that predate staged repairs. New callers should use
        :meth:`create_repair` + :meth:`execute_step` so each staged step and its
        receipt are addressable.
        """
        _request, _step, run = await self.create_and_execute_first_step(
            project=project,
            user=user,
            shot_id=shot_id,
            option=repair_option,
            idempotency_key=idempotency_key,
        )
        return run

    async def create_and_execute_first_step(
        self,
        *,
        project: Project,
        user: User,
        shot_id: UUID,
        option: RepairOption,
        idempotency_key: str,
    ) -> tuple[RepairRequest, RepairStep, NodeRun]:
        """Legacy single-call path: confirm the current plan and dispatch step 1.

        Kept so callers that predate staged repairs keep working; the result is a
        normal repair request whose later steps stay resumable.
        """
        plan = await self.build_repair_plan(project=project, shot_id=shot_id)
        request = await self.create_repair(
            project=project,
            user=user,
            shot_id=shot_id,
            option=option,
            plan_hash=plan.plan_hash,
            request_key=f"repair-plan:{idempotency_key}",
        )
        return await self.execute_step(
            project=project,
            user=user,
            shot_id=shot_id,
            repair_id=request.id,
            idempotency_key=idempotency_key,
        )

    async def list_repairs(
        self, *, project: Project, shot_id: UUID
    ) -> list[RepairRequestRead]:
        requests = (
            (
                await self._session.execute(
                    select(RepairRequest)
                    .where(
                        RepairRequest.project_id == project.id,
                        RepairRequest.shot_id == shot_id,
                    )
                    .order_by(RepairRequest.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return [await self._read(request) for request in requests]

    async def read_repair(
        self, *, project: Project, shot_id: UUID, repair_id: UUID
    ) -> RepairRequestRead:
        request = await self._require_request(
            project=project, shot_id=shot_id, repair_id=repair_id
        )
        return await self._read(request)

    # ---------------------------------------------------------------- helpers

    async def _require_shot(self, *, project: Project, shot_id: UUID) -> Shot:
        shot = await self._session.get(Shot, shot_id)
        if shot is None or shot.project_id != project.id:
            raise ValidationAppError("shot not found", details={"code": "SHOT_NOT_FOUND"})
        return shot

    async def _open_annotations(
        self, *, project: Project, shot_id: UUID
    ) -> list[ReviewAnnotation]:
        return list(
            (
                await self._session.execute(
                    select(ReviewAnnotation).where(
                        ReviewAnnotation.project_id == project.id,
                        ReviewAnnotation.shot_id == shot_id,
                        ReviewAnnotation.status == "open",
                    )
                )
            )
            .scalars()
            .all()
        )

    async def _request_by_key(
        self, *, project: Project, request_key: str
    ) -> RepairRequest | None:
        return (
            await self._session.execute(
                select(RepairRequest).where(
                    RepairRequest.project_id == project.id,
                    RepairRequest.request_key == request_key,
                )
            )
        ).scalar_one_or_none()

    async def _require_request(
        self, *, project: Project, shot_id: UUID, repair_id: UUID
    ) -> RepairRequest:
        request = (
            await self._session.execute(
                select(RepairRequest).where(
                    RepairRequest.id == repair_id,
                    RepairRequest.project_id == project.id,
                    RepairRequest.shot_id == shot_id,
                )
            )
        ).scalar_one_or_none()
        if request is None:
            raise NotFoundError("repair request not found")
        return request

    async def _steps(self, *, request: RepairRequest) -> list[RepairStep]:
        return list(
            (
                await self._session.execute(
                    select(RepairStep)
                    .where(RepairStep.repair_request_id == request.id)
                    .order_by(RepairStep.ordinal)
                )
            )
            .scalars()
            .all()
        )

    async def _read(self, request: RepairRequest) -> RepairRequestRead:
        steps = await self._steps(request=request)
        step_reads: list[RepairStepRead] = []
        for step in steps:
            status = None
            result_artifact_id = None
            if step.node_run_id is not None:
                run = await self._session.get(NodeRun, step.node_run_id)
                status = run.status if run is not None else None
                result_artifact_id = run.result_artifact_id if run is not None else None
            step_reads.append(
                RepairStepRead(
                    id=step.id,
                    ordinal=step.ordinal,
                    stage=step.stage,
                    plan_fingerprint=step.plan_fingerprint,
                    command_key=step.command_key,
                    node_run_id=step.node_run_id,
                    node_run_status=status,
                    result_artifact_id=result_artifact_id,
                    confirmed_at=step.confirmed_at,
                    adopted_artifact_id=step.adopted_artifact_id,
                    review_decision_id=step.review_decision_id,
                    next_action=self._step_next_action(stage=step.stage, status=status),
                )
            )
        return RepairRequestRead(
            id=request.id,
            shot_id=request.shot_id,
            option=request.option,  # type: ignore[arg-type]
            plan_hash=request.plan_hash,
            plan_schema_version=request.plan_schema_version,
            annotation_ids=[UUID(value) for value in request.annotation_ids],
            source_formal_artifact_id=request.source_formal_artifact_id,
            closed_reason=request.closed_reason,
            created_at=request.created_at,
            steps=step_reads,
            next_action=self._next_action(request=request, steps=steps),
        )

    @staticmethod
    def _step_next_action(*, stage: str, status: str | None) -> str:
        if status in {"queued", "running", "cancel_requested"}:
            return "wait"
        if status in {"failed", "blocked", "cancelled", "timed_out"}:
            return "retry_or_close"
        if stage in {"keyframe_regenerate", "video_rerun"}:
            return "review_candidate"
        if stage in {"keyframe_review", "video_review"}:
            return "human_decision"
        return "none"

    def _next_action(self, *, request: RepairRequest, steps: list[RepairStep]) -> str:
        if request.closed_at is not None:
            return "closed"
        stages = STEP_STAGE_BY_OPTION[request.option]
        ordinal = len(steps) + 1
        stage = stages.get(ordinal)
        if stage is None:
            return "closed"
        if stage in {"keyframe_review", "video_review"}:
            return "human_decision"
        return "execute_step"


async def record_repair_adoption(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    artifact_id: UUID,
    review_decision_id: UUID | None = None,
) -> int:
    """Link the adopted Artifact (and decision) back to the repair step that produced it.

    Called after a user action takes a repair candidate further (promoting it to
    Formal, or recording a human decision). Returns how many steps were updated;
    steps that already carry the link are left untouched, so this is safe to call
    repeatedly.
    """
    from app.execution.models import NodeRun

    steps = list(
        (
            await session.execute(
                select(RepairStep)
                .join(RepairRequest, RepairRequest.id == RepairStep.repair_request_id)
                .where(
                    RepairStep.project_id == project_id,
                    RepairRequest.shot_id == shot_id,
                    RepairStep.adopted_artifact_id.is_(None),
                    RepairStep.node_run_id.isnot(None),
                )
            )
        )
        .scalars()
        .all()
    )
    updated = 0
    for step in steps:
        run = await session.get(NodeRun, step.node_run_id) if step.node_run_id else None
        if run is None or run.result_artifact_id != artifact_id:
            continue
        step.adopted_artifact_id = artifact_id
        if review_decision_id is not None:
            step.review_decision_id = review_decision_id
        updated += 1
    if updated:
        await session.flush()
    return updated


__all__ = [
    "PLAN_SCHEMA_VERSION",
    "STEP_STAGE_BY_OPTION",
    "RepairOption",
    "RepairPlanRead",
    "RepairRequestRead",
    "RepairService",
    "RepairStage",
    "RepairStepRead",
    "record_repair_adoption",
    "repair_request_hash",
]
