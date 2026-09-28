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
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.assets.models import Shot
from app.delivery.models import ReviewAnnotation
from app.execution.models import NodeRun
from app.production.execution_plan import WorkbenchExecutionPlan
from app.production.models import RepairRequest, RepairStep
from app.production.review_gate import evaluate_artifact_admission
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
    node_run_error_code: str | None = None
    result_artifact_id: UUID | None
    confirmed_at: datetime | None
    adopted_artifact_id: UUID | None
    review_decision_id: UUID | None
    next_action: str


class RepairStepPlanRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repair_id: UUID
    step_ordinal: int
    stage: str
    plan: WorkbenchExecutionPlan


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
    next_step_ordinal: int | None


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
                "annotations": [
                    {
                        "id": str(item.id),
                        "note": item.note,
                        "severity": item.severity,
                        **{
                            key: float(value) if value is not None else None
                            for key, value in {
                                "time_start": item.time_start,
                                "time_end": item.time_end,
                                "x": item.x,
                                "y": item.y,
                                "width": item.width,
                                "height": item.height,
                            }.items()
                        },
                    }
                    for item in annotations
                ],
                "formal_keyframe_artifact_id": (
                    str(shot.formal_keyframe_artifact_id)
                    if shot.formal_keyframe_artifact_id
                    else None
                ),
                "formal_video_artifact_id": (
                    str(shot.formal_video_artifact_id) if shot.formal_video_artifact_id else None
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
        await WorkbenchExecutionService(self._session, user_id=user.id).lock_command_scope(
            project_id=project.id
        )
        existing = await self._request_by_key(project=project, request_key=key)
        if existing is not None:
            if existing.shot_id != shot_id or existing.request_hash != repair_request_hash(
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
        active_id = await self._session.scalar(
            select(RepairRequest.id)
            .where(
                RepairRequest.project_id == project.id,
                RepairRequest.shot_id == shot_id,
                RepairRequest.closed_at.is_(None),
            )
            .limit(1)
        )
        if active_id is not None:
            raise ConflictError(
                "this shot already has an active repair; resume or close it first",
                details={"code": "REPAIR_ALREADY_ACTIVE", "repair_id": str(active_id)},
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

    async def build_step_plan(
        self,
        *,
        project: Project,
        user: User,
        shot_id: UUID,
        repair_id: UUID,
        accept_approximations: bool = False,
    ) -> RepairStepPlanRead:
        """Preview the next actual media command without queuing or contacting a provider."""
        request = await self._require_request(
            project=project,
            shot_id=shot_id,
            repair_id=repair_id,
        )
        state = await self._read(request)
        ordinal = self._require_executable(state)
        stage = STEP_STAGE_BY_OPTION[request.option][ordinal]
        service = WorkbenchExecutionService(self._session, user_id=user.id)
        execution_input = await self._execution_input(
            project=project,
            request=request,
            ordinal=ordinal,
            service=service,
            accept_approximations=accept_approximations,
        )
        plan = await service.build_plan(
            project=project,
            execution_input=execution_input,
            allow_unaccepted_approximations=True,
        )
        return RepairStepPlanRead(
            repair_id=request.id,
            step_ordinal=ordinal,
            stage=stage,
            plan=plan,
        )

    async def execute_step(
        self,
        *,
        project: Project,
        user: User,
        shot_id: UUID,
        repair_id: UUID,
        expected_plan_fingerprint: str,
        expected_step_ordinal: int,
        idempotency_key: str,
        accept_approximations: bool = False,
    ) -> tuple[RepairRequest, RepairStep, NodeRun]:
        """Recheck the displayed plan; one command creates at most one media run.

        Return durable receipts BEFORE inspecting current progress or mutable
        model settings. A lost response must never become the next paid step.
        """
        command_key = idempotency_key.strip()
        if not command_key:
            raise ValidationAppError("Idempotency-Key must not be blank")
        service = WorkbenchExecutionService(self._session, user_id=user.id)
        await service.lock_command_scope(project_id=project.id)
        request = await self._require_request(
            project=project,
            shot_id=shot_id,
            repair_id=repair_id,
        )
        steps = await self._steps(request=request)
        for step in steps:
            if step.command_key != command_key:
                continue
            if (
                step.ordinal != expected_step_ordinal
                or step.plan_fingerprint != expected_plan_fingerprint
            ):
                raise ConflictError(
                    "repair command key was used for a different step or plan",
                    details={"code": "REPAIR_COMMAND_REUSED"},
                )
            run = (
                await self._session.get(
                    NodeRun,
                    step.node_run_id,
                    populate_existing=True,
                )
                if step.node_run_id
                else None
            )
            if run is None:
                raise ConflictError(
                    "repair receipt is unavailable", details={"code": "REPAIR_RECEIPT_MISSING"}
                )
            return request, step, run

        state = await self._read(request)
        ordinal = self._require_executable(state)
        if ordinal != expected_step_ordinal:
            raise ConflictError(
                "repair advanced since preview; preview the next step",
                details={"code": "REPAIR_STEP_STALE"},
            )
        execution_input = await self._execution_input(
            project=project,
            request=request,
            ordinal=ordinal,
            service=service,
            accept_approximations=accept_approximations,
        )
        plan = await service.build_plan(project=project, execution_input=execution_input)
        if plan.plan_fingerprint != expected_plan_fingerprint:
            raise ConflictError(
                "repair inputs or model changed; preview and confirm the step again",
                details={"code": "REPAIR_STEP_PLAN_MISMATCH"},
            )
        run = await service.create_and_dispatch(
            project=project,
            execution_input=execution_input,
            prepared_plan=plan,
            idempotency_key_override=f"repair:{request.id}:{command_key}",
        )
        step = RepairStep(
            repair_request_id=request.id,
            project_id=project.id,
            ordinal=ordinal,
            stage=STEP_STAGE_BY_OPTION[request.option][ordinal],
            plan_fingerprint=plan.plan_fingerprint,
            command_key=command_key,
            node_run_id=run.id,
            confirmed_by=user.id,
            confirmed_at=datetime.now(UTC),
        )
        self._session.add(step)
        await self._session.flush()
        return request, step, run

    async def _execution_input(
        self,
        *,
        project: Project,
        request: RepairRequest,
        ordinal: int,
        service: WorkbenchExecutionService,
        accept_approximations: bool = False,
    ) -> WorkbenchExecutionInput:
        shot = await self._require_shot(project=project, shot_id=request.shot_id)
        image = STEP_STAGE_BY_OPTION[request.option][ordinal] == "keyframe_regenerate"
        if not image and shot.formal_keyframe_artifact_id is None:
            raise ValidationAppError(
                "video repair requires a formal keyframe", details={"code": "NO_FORMAL_KEYFRAME"}
            )
        stage: Literal["image_keyframe", "video"] = "image_keyframe" if image else "video"
        return WorkbenchExecutionInput(
            project_id=project.id,
            shot_id=shot.id,
            stage=stage,
            prompt=(
                (shot.image_prompt if image else shot.video_prompt) or shot.visual_description
            ).strip(),
            semantic_intent={
                "intent": "shot_keyframe" if image else "shot_video",
                "repair": request.option,
                "repair_request_id": str(request.id),
                "repair_step": ordinal,
            },
            mode_id="explicit_binding",
            expected_shot_version=shot.version,
            accept_approximations=accept_approximations,
            references=await service.saved_shot_references(
                project=project,
                shot_id=shot.id,
                stage=stage,
            ),
        )

    @staticmethod
    def _require_executable(state: RepairRequestRead) -> int:
        if state.next_action == "execute_step" and state.next_step_ordinal is not None:
            return state.next_step_ordinal
        if state.next_action == "human_decision":
            raise ValidationAppError(
                "review and explicitly adopt this exact candidate before continuing",
                details={"code": "REPAIR_STEP_REQUIRES_REVIEW"},
            )
        raise ConflictError(
            "repair has no executable step in its current state",
            details={"code": "REPAIR_NOT_EXECUTABLE", "next_action": state.next_action},
        )

    async def close_repair(
        self,
        *,
        project: Project,
        shot_id: UUID,
        repair_id: UUID,
        reason: Literal["completed", "abandoned"],
    ) -> RepairRequestRead:
        """Explicitly finish or abandon; never cancel/retry a remote operation."""
        if reason not in {"completed", "abandoned"}:
            raise ValidationAppError("unsupported repair close reason")
        await self._session.execute(
            select(Project.id).where(Project.id == project.id).with_for_update()
        )
        request = await self._require_request(
            project=project,
            shot_id=shot_id,
            repair_id=repair_id,
        )
        state = await self._read(request)
        if request.closed_reason is not None:
            if request.closed_reason == reason:
                return state
            raise ConflictError("repair is already closed", details={"code": "REPAIR_CLOSED"})
        if any(step.node_run_error_code == "PROVIDER_SUBMISSION_UNKNOWN" for step in state.steps):
            raise ConflictError(
                "reconcile the unknown provider submission before ending this repair",
                details={"code": "REPAIR_SUBMISSION_UNKNOWN"},
            )
        if state.next_action == "wait":
            raise ConflictError(
                "wait for the active run or cancel it from production first",
                details={"code": "REPAIR_RUN_ACTIVE"},
            )
        if reason == "completed" and state.next_action != "ready_to_close":
            raise ConflictError(
                "the final repair candidate has not been reviewed and adopted",
                details={"code": "REPAIR_NOT_COMPLETE"},
            )
        request.closed_reason = reason
        request.closed_at = datetime.now(UTC)
        if reason == "completed" and request.annotation_ids:
            await self._session.execute(
                update(ReviewAnnotation)
                .where(
                    ReviewAnnotation.project_id == project.id,
                    ReviewAnnotation.shot_id == shot_id,
                    ReviewAnnotation.id.in_([UUID(value) for value in request.annotation_ids]),
                    ReviewAnnotation.status == "open",
                )
                .values(status="resolved")
            )
        await self._session.flush()
        return await self._read(request)

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
        existing_steps = await self._steps(request=request)
        if existing_steps:
            first = existing_steps[0]
            fingerprint = first.plan_fingerprint or ""
            ordinal = first.ordinal
        else:
            preview = await self.build_step_plan(
                project=project,
                user=user,
                shot_id=shot_id,
                repair_id=request.id,
            )
            fingerprint = preview.plan.plan_fingerprint or ""
            ordinal = preview.step_ordinal
        return await self.execute_step(
            project=project,
            user=user,
            shot_id=shot_id,
            repair_id=request.id,
            expected_plan_fingerprint=fingerprint,
            expected_step_ordinal=ordinal,
            idempotency_key=idempotency_key,
        )

    async def list_repairs(self, *, project: Project, shot_id: UUID) -> list[RepairRequestRead]:
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
        request = await self._require_request(project=project, shot_id=shot_id, repair_id=repair_id)
        return await self._read(request)

    # ---------------------------------------------------------------- helpers

    async def _require_shot(self, *, project: Project, shot_id: UUID) -> Shot:
        shot = await self._session.scalar(
            select(Shot).where(Shot.id == shot_id).execution_options(populate_existing=True)
        )
        if shot is None or shot.project_id != project.id:
            raise ValidationAppError("shot not found", details={"code": "SHOT_NOT_FOUND"})
        return shot

    async def _open_annotations(self, *, project: Project, shot_id: UUID) -> list[ReviewAnnotation]:
        return list(
            (
                await self._session.execute(
                    select(ReviewAnnotation)
                    .where(
                        ReviewAnnotation.project_id == project.id,
                        ReviewAnnotation.shot_id == shot_id,
                        ReviewAnnotation.status == "open",
                    )
                    .order_by(ReviewAnnotation.id)
                )
            )
            .scalars()
            .all()
        )

    async def _request_by_key(self, *, project: Project, request_key: str) -> RepairRequest | None:
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
                select(RepairRequest)
                .where(
                    RepairRequest.id == repair_id,
                    RepairRequest.project_id == project.id,
                    RepairRequest.shot_id == shot_id,
                )
                .execution_options(populate_existing=True)
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
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )

    async def _read(self, request: RepairRequest) -> RepairRequestRead:
        steps = await self._steps(request=request)
        shot = await self._session.get(Shot, request.shot_id, populate_existing=True)
        step_reads: list[RepairStepRead] = []
        for step in steps:
            run = (
                await self._session.get(NodeRun, step.node_run_id, populate_existing=True)
                if step.node_run_id
                else None
            )
            status = run.status if run else None
            artifact_id = run.result_artifact_id if run else None
            if run is not None and run.error_code == "PROVIDER_SUBMISSION_UNKNOWN":
                action = "reconcile_submission"
            elif status in {"queued", "running", "cancel_requested"}:
                action = "wait"
            elif (
                status not in {"completed", "cached", "completed_after_cancel"}
                or artifact_id is None
            ):
                action = "close_or_replan"
            elif step.adopted_artifact_id != artifact_id or step.review_decision_id is None:
                action = "review_candidate"
            elif request.closed_at is not None:
                # Completed repairs are historical receipts, not live Formal pointers.
                # A later revision must not retroactively turn their adoption into failure.
                action = "adopted"
            else:
                image = step.stage == "keyframe_regenerate"
                formal_id = (
                    (shot.formal_keyframe_artifact_id if image else shot.formal_video_artifact_id)
                    if shot
                    else None
                )
                action = "close_or_replan"
                if formal_id == artifact_id:
                    try:
                        admission = await evaluate_artifact_admission(
                            self._session,
                            project_id=request.project_id,
                            shot_id=request.shot_id,
                            artifact_id=artifact_id,
                            stage="formal_keyframe" if image else "formal_video",
                        )
                    except ValidationAppError:
                        admission = None
                    if (
                        admission is not None
                        and admission.allowed
                        and any(
                            item.decision_id == step.review_decision_id
                            for item in admission.requirements
                        )
                    ):
                        action = "adopted"
            step_reads.append(
                RepairStepRead(
                    id=step.id,
                    ordinal=step.ordinal,
                    stage=step.stage,
                    plan_fingerprint=step.plan_fingerprint,
                    command_key=step.command_key,
                    node_run_id=step.node_run_id,
                    node_run_status=status,
                    node_run_error_code=run.error_code if run else None,
                    result_artifact_id=artifact_id,
                    confirmed_at=step.confirmed_at,
                    adopted_artifact_id=step.adopted_artifact_id,
                    review_decision_id=step.review_decision_id,
                    next_action=action,
                )
            )
        next_action, ordinal = self._progress(request=request, steps=step_reads)
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
            next_action=next_action,
            next_step_ordinal=ordinal,
        )

    @staticmethod
    def _progress(
        *,
        request: RepairRequest,
        steps: list[RepairStepRead],
    ) -> tuple[str, int | None]:
        if request.closed_at is not None:
            return "closed", None
        # Even if an earlier formal was replaced, an active later command must
        # settle before abandoning. Closing does not cancel provider work.
        if any(step.next_action == "reconcile_submission" for step in steps):
            return "reconcile_submission", None
        if any(step.next_action == "wait" for step in steps):
            return "wait", None
        by_ordinal = {step.ordinal: step for step in steps}
        for ordinal, stage in STEP_STAGE_BY_OPTION[request.option].items():
            if stage in {"keyframe_review", "video_review"}:
                continue
            step = by_ordinal.get(ordinal)
            if step is None:
                return "execute_step", ordinal
            if step.next_action == "review_candidate":
                return "human_decision", None
            if step.next_action != "adopted":
                return "close_or_replan", None
        return "ready_to_close", None


async def record_repair_adoption(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    artifact_id: UUID,
    review_decision_id: UUID | None = None,
) -> int:
    """Record an exact successful, approved and explicitly Formal candidate.

    Reuse the production review gate; a stray decision id or a different
    candidate cannot advance a repair. Closed requests retain their history.
    """
    shot = await session.get(Shot, shot_id, populate_existing=True)
    if shot is None or shot.project_id != project_id:
        return 0
    rows = (
        await session.execute(
            select(RepairStep, NodeRun)
            .join(RepairRequest, RepairRequest.id == RepairStep.repair_request_id)
            .join(NodeRun, NodeRun.id == RepairStep.node_run_id)
            .where(
                RepairStep.project_id == project_id,
                RepairRequest.project_id == project_id,
                RepairRequest.shot_id == shot_id,
                RepairRequest.closed_at.is_(None),
                NodeRun.project_id == project_id,
                NodeRun.result_artifact_id == artifact_id,
                NodeRun.status.in_(("completed", "cached", "completed_after_cancel")),
            )
        )
    ).all()
    updated = 0
    for step, _run in rows:
        image = step.stage == "keyframe_regenerate"
        if step.stage not in {"keyframe_regenerate", "video_rerun"}:
            continue
        formal_id = shot.formal_keyframe_artifact_id if image else shot.formal_video_artifact_id
        if formal_id != artifact_id:
            continue
        admission = await evaluate_artifact_admission(
            session,
            project_id=project_id,
            shot_id=shot_id,
            artifact_id=artifact_id,
            stage="formal_keyframe" if image else "formal_video",
        )
        if not admission.allowed:
            continue
        decision_id = next(
            (
                item.decision_id
                for item in admission.requirements
                if item.applies and item.decision == "approved"
            ),
            None,
        )
        if decision_id is None or (
            review_decision_id is not None and review_decision_id != decision_id
        ):
            continue
        if step.adopted_artifact_id == artifact_id and step.review_decision_id == decision_id:
            continue
        step.adopted_artifact_id = artifact_id
        step.review_decision_id = decision_id
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
    "RepairStepPlanRead",
    "record_repair_adoption",
    "repair_request_hash",
]
