"""MasterRun use cases: origin binding, immutable plans, control receipts.

The service owns only goal/plan/control facts. Execution evidence stays in the
existing Turn, BusinessFlow, NodeRun and ProviderOperation records; nothing here
creates a second runtime or a second task state machine.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.assets.models import Episode
from app.contracts.delivery_verification import (
    COMPLETION_RULES,
    BoundDeliveryOutput,
    DeliveryPlanRef,
    DeliverySlotVerifier,
    DeliveryVerifier,
    EpisodeDeliveryGoal,
    FlowCompletionGoal,
    ProjectDeliveryGoal,
)
from app.contracts.domain_events import (
    MasterRunChanged,
    MasterRunPlanApplied,
    MasterRunPlanProposed,
)
from app.director.business_flows import (
    SERIES_EXPORTS,
    BusinessFlowDefinitionRegistry,
    BusinessFlowService,
    normalize_dispositions,
    series_export_flow,
    validate_plan_flows,
)
from app.director.master_run_models import (
    DirectorMasterRun,
    DirectorMasterRunControlReceipt,
    DirectorMasterRunPlan,
)
from app.director.master_run_notices import append_master_run_notice
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.turn_models import DirectorTurn
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

PLAN_COMMAND = "director.master_run_plan_apply"
PLAN_SCHEMA_VERSION = "master_plan_v1"
PLAN_TOP_LEVEL_KEYS = frozenset(
    {"goal", "flows", "dependencies", "completion", "input_versions", "limits", "decision_basis"}
)
PLAN_OPTIONAL_KEYS = frozenset({"supersedes_plan_id", "change_reason", "flow_dispositions"})

TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})

# Frozen edges from DIRECTOR_RUNTIME; unlisted pairs are refused without a write.
ALLOWED_EDGES: dict[str, frozenset[str]] = {
    "planning": frozenset({"waiting", "paused", "stopping", "failed"}),
    "waiting": frozenset({"running", "paused", "stopping", "succeeded", "failed"}),
    "running": frozenset({"waiting", "paused", "stopping", "succeeded", "failed"}),
    "paused": frozenset({"planning", "waiting", "stopping", "failed"}),
    "stopping": frozenset({"cancelled"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}

CONTROL_OPERATIONS = frozenset({"pause", "resume", "cancel", "verify"})


class PlanConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    master_run_id: UUID
    plan_id: UUID
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_run_revision: int = Field(strict=True, ge=1)
    expected_control_epoch: int = Field(strict=True, ge=0)


def _canonical(value: object) -> str:
    """Stable JSON: sorted keys, preserved array order, no NaN/infinity."""
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    )


def plan_hash(schema_version: str, plan_data: dict[str, object]) -> str:
    return hashlib.sha256(
        _canonical({"schema_version": schema_version, "plan_data": plan_data}).encode()
    ).hexdigest()


def _request_hash(operation: str, expected_revision: int, reason: str) -> str:
    return hashlib.sha256(
        _canonical(
            {"operation": operation, "expected_revision": expected_revision, "reason": reason}
        ).encode()
    ).hexdigest()


def _state_conflict(code: str, message: str, **details: object) -> ConflictError:
    return ConflictError(message, details={"code": code, **details})


class MasterRunService:
    """Caller owns the transaction; every method re-checks project ownership first."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        actor: User,
        project: Project,
        flow_registry: BusinessFlowDefinitionRegistry | None = None,
    ) -> None:
        self._session = session
        self._actor = actor
        self._project = project
        self._flow_registry = flow_registry

    def _flows(self) -> BusinessFlowService:
        return BusinessFlowService(
            self._session,
            actor=self._actor,
            project=self._project,
            registry=self._flow_registry,
        )

    # ----- reads -----------------------------------------------------------
    async def _locked(self, run_id: UUID) -> DirectorMasterRun:
        """Project is locked first so control, plan and turn binding serialize."""
        await self._session.scalar(
            select(Project)
            .where(Project.id == self._project.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        run = await self._session.scalar(
            select(DirectorMasterRun)
            .where(
                DirectorMasterRun.id == run_id,
                DirectorMasterRun.project_id == self._project.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run is None:
            raise NotFoundError("master run not found")
        return run

    async def get(self, run_id: UUID) -> DirectorMasterRun:
        run = await self._session.scalar(
            select(DirectorMasterRun).where(
                DirectorMasterRun.id == run_id,
                DirectorMasterRun.project_id == self._project.id,
            )
        )
        if run is None:
            raise NotFoundError("master run not found")
        return run

    async def list_runs(
        self, *, status: str | None = None, include_archived: bool = False,
        limit: int = 50, offset: int = 0,
    ) -> list[DirectorMasterRun]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValidationAppError("Invalid master run page")
        query = select(DirectorMasterRun).where(
            DirectorMasterRun.project_id == self._project.id
        )
        if status is not None:
            query = query.where(DirectorMasterRun.status == status)
        if not include_archived:
            query = query.where(DirectorMasterRun.archived_at.is_(None))
        return list(
            await self._session.scalars(
                query.order_by(DirectorMasterRun.updated_at.desc(), DirectorMasterRun.id)
                .limit(limit)
                .offset(offset)
            )
        )

    async def list_plans(
        self, run_id: UUID, *, limit: int = 50, offset: int = 0,
    ) -> list[DirectorMasterRunPlan]:
        await self.get(run_id)
        if not 1 <= limit <= 100 or offset < 0:
            raise ValidationAppError("Invalid plan page")
        return list(
            await self._session.scalars(
                select(DirectorMasterRunPlan)
                .where(
                    DirectorMasterRunPlan.master_run_id == run_id,
                    DirectorMasterRunPlan.project_id == self._project.id,
                )
                .order_by(DirectorMasterRunPlan.revision.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    async def get_plan(self, run_id: UUID, plan_id: UUID) -> DirectorMasterRunPlan:
        await self.get(run_id)
        plan = await self._session.scalar(
            select(DirectorMasterRunPlan).where(
                DirectorMasterRunPlan.id == plan_id,
                DirectorMasterRunPlan.master_run_id == run_id,
                DirectorMasterRunPlan.project_id == self._project.id,
            )
        )
        if plan is None:
            raise NotFoundError("master run plan not found")
        return plan

    async def current_plan(self, run: DirectorMasterRun) -> DirectorMasterRunPlan | None:
        if run.current_plan_id is None:
            return None
        return await self.plan_by_id(run.current_plan_id)

    async def plan_by_id(self, plan_id: UUID) -> DirectorMasterRunPlan | None:
        return cast(
            DirectorMasterRunPlan | None,
            await self._session.scalar(
                select(DirectorMasterRunPlan).where(
                    DirectorMasterRunPlan.id == plan_id,
                    DirectorMasterRunPlan.project_id == self._project.id,
                )
            ),
        )

    # ----- goal creation ---------------------------------------------------
    async def create_for_origin_turn(
        self, *, turn_id: UUID, goal: str,
    ) -> DirectorMasterRun:
        """Bind one continuous goal to an existing Agent Turn (same transaction).

        Only a real, thread-bound Agent Turn originated by this actor may own a
        run. A second goal for the same turn returns the original binding or
        refuses a different goal; the origin can never be re-bound.
        """
        if len(goal) > 16000:
            raise ValidationAppError("创作目标必须为1至16000个字符")
        text = goal.strip()
        if not text:
            raise ValidationAppError("创作目标必须为1至16000个字符")
        turn = await self._session.scalar(
            select(DirectorTurn).where(
                DirectorTurn.id == turn_id,
                DirectorTurn.project_id == self._project.id,
            )
        )
        if turn is None:
            raise NotFoundError("director turn not found")
        if turn.turn_kind != "agent" or turn.thread_id is None:
            raise ValidationAppError(
                "只有对话中的 Agent Turn 可以建立持续目标",
                details={"code": "MASTER_RUN_ORIGIN_KIND"},
            )
        if (
            turn.actor_id != self._actor.id
            or turn.workspace_id != self._project.workspace_id
        ):
            raise ConflictError(
                "该轮次不属于当前用户或工作空间",
                details={"code": "MASTER_RUN_ORIGIN_MISMATCH"},
            )
        existing = await self._session.scalar(
            select(DirectorMasterRun).where(
                DirectorMasterRun.project_id == self._project.id,
                DirectorMasterRun.origin_turn_id == turn_id,
            )
        )
        if existing is not None:
            if existing.goal != text:
                raise ConflictError(
                    "该轮次已经绑定了另一个持续目标",
                    details={"code": "MASTER_RUN_ORIGIN_REBOUND", "run_id": str(existing.id)},
                )
            return existing
        run = DirectorMasterRun(
            project_id=self._project.id,
            workspace_id=self._project.workspace_id,
            actor_id=self._actor.id,
            source_thread_id=turn.thread_id,
            origin_turn_id=turn.id,
            origin_turn_kind="agent",
            goal=text,
            status="planning",
            desired_state="run",
            revision=1,
            control_epoch=0,
        )
        self._session.add(run)
        await self._session.flush()
        if turn.master_run_id is None:
            turn.master_run_id = run.id
        await append_master_run_notice(
            self._session, project_id=self._project.id, actor_id=self._actor.id,
            notice=MasterRunChanged(
                run_id=run.id, revision=run.revision, status=run.status,
                desired_state=run.desired_state, control_epoch=run.control_epoch,
            ),
        )
        return run

    # ----- plans -----------------------------------------------------------
    async def propose_delivery_check(
        self, turn: DirectorTurn
    ) -> tuple[DirectorMasterRunPlan, UUID]:
        """Build a technical delivery goal from project facts, without starting production."""
        if turn.master_run_id is None or turn.thread_id is None or turn.scope_type != "project":
            raise ValidationAppError("当前对话未绑定项目级持续目标")
        run = await self._locked(turn.master_run_id)
        if (
            run.actor_id != self._actor.id
            or run.source_thread_id != turn.thread_id
            or run.origin_turn_id != turn.id
            or run.current_plan_id is not None
            or run.status != "planning"
            or run.desired_state != "run"
        ):
            raise ConflictError("只有当前目标的首次规划轮次可以提出初始交付计划")
        work_type = self._project.work_type
        flows: list[dict[str, object]] = []
        future_count: int | None = None
        if work_type == "animation_promo":
            targets: list[dict[str, object]] = [{"episode_id": None}]
        else:
            episodes = list(
                await self._session.scalars(
                    select(Episode)
                    .where(
                        Episode.project_id == self._project.id,
                    )
                    .order_by(Episode.episode_number)
                    .with_for_update(read=True)
                )
            )
            if (
                work_type == "serial_comic"
                and self._project.planned_episode_count is not None
                and (
                    len(episodes) != self._project.planned_episode_count
                    or any(e.episode_number != index for index, e in enumerate(episodes, start=1))
                )
            ):
                future_count = self._project.planned_episode_count
                flows = [series_export_flow(self._project.id, future_count)]
            targets = [
                {"episode_id": str(episode.id), "episode_number": episode.episode_number}
                for episode in episodes
            ]
        completion: dict[str, object] = {
            "rule_id": "project_delivery_ready_v1",
            "work_type": work_type,
        }
        if future_count is not None:
            completion.update(
                planned_episode_count=future_count,
                output_slot={
                    "flow_key": "episode_delivery",
                    "step_key": "collect_exports",
                    "field": "episode_exports",
                },
            )
        else:
            completion["targets"] = targets
        data: dict[str, object] = {
            "goal": run.goal,
            "flows": flows,
            "dependencies": [],
            "completion": [completion],
            "input_versions": dict(turn.input_versions),
            "limits": {"max_model_calls": 0, "max_tool_calls": 0, "max_provider_calls": 0},
            "decision_basis": {
                "expected_run_revision": run.revision,
                "expected_control_epoch": run.control_epoch,
                "current_plan_id": None,
                "current_plan_revision": None,
            },
        }
        proposal = DirectorProposal(
            project_id=run.project_id,
            thread_id=turn.thread_id,
            scope_type="project",
            scope_entity_id=run.project_id,
            created_by=self._actor.id,
        )
        self._session.add(proposal)
        await self._session.flush()
        plan = await self.append_plan(
            run_id=run.id,
            proposal_id=proposal.id,
            plan_data=data,
            created_by_turn_id=turn.id,
        )
        item = await self._session.get(DirectorProposalItem, plan.decision_ref)
        assert item is not None
        if item.proposal_id != proposal.id:
            await self._session.delete(proposal)
        return plan, item.proposal_id

    @staticmethod
    def validate_plan_data(plan_data: dict[str, object]) -> None:
        keys = set(plan_data)
        if PLAN_TOP_LEVEL_KEYS - keys or keys - PLAN_TOP_LEVEL_KEYS - PLAN_OPTIONAL_KEYS:
            raise ValidationAppError(
                "计划字段不完整或包含未知字段",
                details={"code": "MASTER_RUN_PLAN_SHAPE"},
            )
        basis = plan_data.get("decision_basis")
        if not isinstance(basis, dict):
            raise ValidationAppError("计划缺少 decision_basis")
        required = {
            "expected_run_revision", "expected_control_epoch",
            "current_plan_id", "current_plan_revision",
        }
        if (
            set(basis) != required
            or type(basis.get("expected_run_revision")) is not int
            or type(basis.get("expected_control_epoch")) is not int
            or (basis.get("current_plan_revision") is not None
                and type(basis["current_plan_revision"]) is not int)
        ):
            raise ValidationAppError(
                "decision_basis 字段不正确", details={"code": "MASTER_RUN_PLAN_BASIS"},
            )
        if (basis["current_plan_id"] is None) != (basis["current_plan_revision"] is None):
            raise ValidationAppError(
                "current_plan_id 与 current_plan_revision 必须同时为空或同时存在",
                details={"code": "MASTER_RUN_PLAN_BASIS"},
            )
        try:
            declarations = COMPLETION_RULES.validate_python(plan_data.get("completion"))
        except ValidationError as exc:
            raise ValidationAppError(
                "完成条件必须是已注册的目标声明", details={"code": "MASTER_RUN_COMPLETION_SHAPE"},
            ) from exc
        # Validate the flow list early so a bad plan never reaches Apply.
        specs = validate_plan_flows(plan_data.get("flows"), allow_empty=True)
        for declaration in declarations:
            if not isinstance(declaration, ProjectDeliveryGoal) or declaration.output_slot is None:
                continue
            if not any(
                spec.flow_key == declaration.output_slot.flow_key
                and spec.definition_key == SERIES_EXPORTS.definition_key
                and spec.definition_version == SERIES_EXPORTS.definition_version
                and spec.scope_type == "project"
                and spec.input == {"planned_episode_count": declaration.planned_episode_count}
                for spec in specs
            ):
                raise ValidationAppError("输出槽必须对应计划内已注册的分集交付步骤",
                                         details={"code":"MASTER_RUN_OUTPUT_SLOT"})


    async def _basis_matches(self, run: DirectorMasterRun, basis: dict[str, object]) -> bool:
        current = await self.current_plan(run)
        return (
            basis["expected_run_revision"] == run.revision
            and basis["expected_control_epoch"] == run.control_epoch
            and (str(current.id) if current else None) == (
                str(basis["current_plan_id"]) if basis["current_plan_id"] else None
            )
            and (current.revision if current else None) == basis["current_plan_revision"]
        )

    async def append_plan(
        self,
        *,
        run_id: UUID,
        proposal_id: UUID,
        plan_data: dict[str, object],
        created_by_turn_id: UUID | None = None,
        schema_version: str = PLAN_SCHEMA_VERSION,
    ) -> DirectorMasterRunPlan:
        """Append an immutable plan candidate; the run's business revision is untouched."""
        self.validate_plan_data(plan_data)
        run = await self._locked(run_id)
        if run.status in TERMINAL_STATUSES:
            raise _state_conflict("MASTER_RUN_TERMINAL", "持续目标已结束，不能再提交计划")
        basis = plan_data["decision_basis"]
        assert isinstance(basis, dict)
        if not await self._basis_matches(run, basis):
            raise _state_conflict(
                "MASTER_RUN_PLAN_STALE",
                "计划依据已过期，请基于当前目标状态重新生成",
                run_revision=run.revision,
                control_epoch=run.control_epoch,
            )
        proposal = await self._session.scalar(
            select(DirectorProposal).where(
                DirectorProposal.id == proposal_id,
                DirectorProposal.project_id == self._project.id,
                DirectorProposal.thread_id == run.source_thread_id,
            ).with_for_update().execution_options(populate_existing=True)
        )
        if proposal is None:
            raise ValidationAppError(
                "计划提案不属于当前目标的项目对话",
                details={"code": "MASTER_RUN_PLAN_DECISION"},
            )
        digest = plan_hash(schema_version, plan_data)
        existing = await self._session.scalar(
            select(DirectorMasterRunPlan).where(
                DirectorMasterRunPlan.master_run_id == run.id,
                DirectorMasterRunPlan.plan_hash == digest,
            )
        )
        occupied = await self._session.scalar(
            select(DirectorProposalItem.id).where(
                DirectorProposalItem.proposal_id == proposal.id,
            ).limit(1)
        )
        if existing is not None and (occupied is None or existing.decision_ref == occupied):
            return existing
        if occupied is not None or proposal.status != "pending":
            raise ValidationAppError(
                "新计划需要独立的待确认提案", details={"code": "MASTER_RUN_PLAN_DECISION"},
            )
        next_revision = int(
            await self._session.scalar(
                select(func.coalesce(func.max(DirectorMasterRunPlan.revision), 0)).where(
                    DirectorMasterRunPlan.master_run_id == run.id
                )
            )
            or 0
        ) + 1
        plan_id = uuid4()
        item = DirectorProposalItem(
            id=uuid4(), proposal_id=proposal.id, project_id=run.project_id, command=PLAN_COMMAND,
            status="pending", payload=PlanConfirmation(
                master_run_id=run.id, plan_id=plan_id, plan_hash=digest,
                expected_run_revision=run.revision, expected_control_epoch=run.control_epoch,
            ).model_dump(mode="json"),
        )
        plan = DirectorMasterRunPlan(
            id=plan_id,
            project_id=self._project.id,
            master_run_id=run.id,
            revision=next_revision,
            schema_version=schema_version,
            plan_hash=digest,
            plan_data=plan_data,
            decision_ref=item.id,
            created_by_turn_id=created_by_turn_id,
            created_by_actor_id=self._actor.id,
        )
        self._session.add_all([item, plan])
        await self._session.flush()
        if created_by_turn_id is not None:
            turn = await self._session.scalar(
                select(DirectorTurn).where(
                    DirectorTurn.id == created_by_turn_id,
                    DirectorTurn.project_id == self._project.id,
                )
            )
            if turn is not None and turn.master_run_id == run.id:
                turn.plan_revision = plan.revision
        await append_master_run_notice(
            self._session, project_id=self._project.id, actor_id=self._actor.id,
            notice=MasterRunPlanProposed(
                run_id=run.id, plan_id=plan.id, plan_revision=plan.revision,
                decision_ref=item.id,
            ),
        )
        return plan

    async def apply_plan(
        self, *, run_id: UUID, plan_id: UUID, expected_revision: int,
        expected_control_epoch: int, decision_ref: UUID, expected_plan_hash: str,
    ) -> DirectorMasterRunPlan:
        """Persist the accepted plan: current pointer, epoch and revision advance."""
        run = await self._locked(run_id)
        if run.status in TERMINAL_STATUSES:
            raise _state_conflict("MASTER_RUN_TERMINAL", "持续目标已结束，不能确认计划")
        if run.revision != expected_revision:
            raise _state_conflict(
                "MASTER_RUN_VERSION_CONFLICT", "目标已变化，请刷新后重新确认",
                current_revision=run.revision,
            )
        if run.control_epoch != expected_control_epoch:
            raise _state_conflict(
                "MASTER_RUN_EPOCH_CONFLICT", "目标控制状态已变化，请重新生成计划",
                current_epoch=run.control_epoch,
            )
        plan = await self._session.scalar(
            select(DirectorMasterRunPlan).where(
                DirectorMasterRunPlan.id == plan_id,
                DirectorMasterRunPlan.master_run_id == run.id,
                DirectorMasterRunPlan.project_id == self._project.id,
            )
        )
        if plan is None:
            raise NotFoundError("master run plan not found")
        if (
            plan.decision_ref != decision_ref or plan.plan_hash != expected_plan_hash
            or plan_hash(plan.schema_version, plan.plan_data) != expected_plan_hash
        ):
            raise _state_conflict("MASTER_RUN_PLAN_DECISION", "点选的确认项与计划内容不一致")
        current = await self.current_plan(run)
        if current is not None and plan.revision < current.revision:
            raise _state_conflict(
                "MASTER_RUN_PLAN_SUPERSEDED", "不能把目标退回到更早的计划快照",
                current_plan_revision=current.revision,
            )
        basis = plan.plan_data.get("decision_basis")
        if not isinstance(basis, dict) or not await self._basis_matches(run, basis):
            raise _state_conflict("MASTER_RUN_PLAN_STALE", "计划的原始确认依据已变化，请重新预览")
        # A command rejection is returned per item. Roll back all changes made by
        # this item even when validation of a later flow fails after a flush.
        async with self._session.begin_nested():
            await self._activate_plan(run, plan)
        return plan

    async def _activate_plan(self, run: DirectorMasterRun, plan: DirectorMasterRunPlan) -> None:
        run.current_plan_id = plan.id
        run.control_epoch += 1
        run.revision += 1
        if run.status == "planning":
            run.status = "waiting"
            run.wait_reason = "production_pending"
        run.updated_at = datetime.now(UTC)
        await self._session.flush()
        # Flow dispositions must cover every prior non-terminal instance before
        # the new plan may create its own frozen instances. Retained flows keep
        # their original plan identity and are not duplicated.
        flows = self._flows()
        dispositions = await flows.apply_dispositions(
            run=run,
            plan=plan,
            dispositions=normalize_dispositions(plan.plan_data.get("flow_dispositions")),
        )
        retained = dispositions.get("retained_flow_keys")
        await flows.create_from_plan(
            run=run,
            plan=plan,
            created_by_turn_id=plan.created_by_turn_id,
            skip_flow_keys=set(retained) if isinstance(retained, list) else (),
        )
        await append_master_run_notice(
            self._session, project_id=self._project.id, actor_id=self._actor.id,
            notice=MasterRunPlanApplied(
                run_id=run.id, plan_id=plan.id, plan_revision=plan.revision,
                applied_run_revision=run.revision, control_epoch=run.control_epoch,
            ),
        )

    # ----- control ---------------------------------------------------------
    async def _receipt(
        self, run_id: UUID, operation: str, expected_revision: int,
    ) -> DirectorMasterRunControlReceipt | None:
        return cast(
            DirectorMasterRunControlReceipt | None,
            await self._session.scalar(
                select(DirectorMasterRunControlReceipt).where(
                    DirectorMasterRunControlReceipt.master_run_id == run_id,
                    DirectorMasterRunControlReceipt.expected_revision == expected_revision,
                    DirectorMasterRunControlReceipt.operation == operation,
                )
            ),
        )

    async def control(
        self,
        *,
        run_id: UUID,
        operation: str,
        expected_revision: int,
        reason: str = "",
        delivery_verifier: DeliveryVerifier | None = None,
        slot_verifier: DeliverySlotVerifier | None = None,
    ) -> dict[str, object]:
        if operation not in CONTROL_OPERATIONS:
            raise ValidationAppError("不支持的控制操作")
        if expected_revision < 1 or len(reason) > 1000:
            raise ValidationAppError("控制请求参数不正确")
        digest = _request_hash(operation, expected_revision, reason)
        run = await self._locked(run_id)
        replay = await self._receipt(run.id, operation, expected_revision)
        if replay is not None:
            if replay.request_hash != digest:
                raise _state_conflict(
                    "MASTER_RUN_RECEIPT_CONFLICT",
                    "同一版本与操作已经受理了不同的控制请求",
                    operation=operation,
                )
            return dict(replay.result_data)
        if run.revision != expected_revision:
            raise _state_conflict(
                "MASTER_RUN_VERSION_CONFLICT",
                "目标已变化，请刷新后重新确认",
                current_revision=run.revision,
            )
        result = await self._apply_control(
            run,
            operation=operation,
            reason=reason,
            delivery_verifier=delivery_verifier,
            slot_verifier=slot_verifier,
        )
        run.revision += 1
        run.updated_at = datetime.now(UTC)
        receipt = DirectorMasterRunControlReceipt(
            project_id=self._project.id,
            master_run_id=run.id,
            actor_id=self._actor.id,
            operation=operation,
            expected_revision=expected_revision,
            request_hash=digest,
            result_revision=run.revision,
            result_data=result,
        )
        self._session.add(receipt)
        await self._session.flush()
        await append_master_run_notice(
            self._session,
            project_id=self._project.id,
            actor_id=self._actor.id,
            notice=MasterRunChanged(
                run_id=run.id,
                revision=run.revision,
                status=run.status,
                desired_state=run.desired_state,
                control_epoch=run.control_epoch,
            ),
        )
        return dict(result)

    async def _apply_control(
        self,
        run: DirectorMasterRun,
        *,
        operation: str,
        reason: str,
        delivery_verifier: DeliveryVerifier | None,
        slot_verifier: DeliverySlotVerifier | None,
    ) -> dict[str, object]:
        if operation == "pause":
            self._require_edge(run, "paused")
            run.status = "paused"
            run.desired_state = "pause"
            run.control_epoch += 1
            run.wait_reason = "user_decision"
        elif operation == "resume":
            target = "waiting" if run.current_plan_id is not None else "planning"
            self._require_edge(run, target)
            run.status = target
            run.desired_state = "run"
            run.control_epoch += 1
            run.wait_reason = "production_pending" if target == "waiting" else None
        elif operation == "cancel":
            self._require_edge(run, "stopping")
            run.status = "stopping"
            run.desired_state = "cancel"
            run.control_epoch += 1
            # Unfinished flows and steps are cancelled; successes stay readable.
            await self._flows().cancel_run(run, reason="cancelled")
            run.status = "cancelled"
            run.finished_at = datetime.now(UTC)
            run.wait_reason = None
        else:  # verify
            if run.desired_state != "run" or run.status != "waiting" or run.current_plan_id is None:
                raise _state_conflict(
                    "MASTER_RUN_STATE_CONFLICT",
                    "只有运行中且等待的已确认计划可以核对完成条件",
                    status=run.status,
                )
            plan = await self.current_plan(run)
            assert plan is not None
            flows = self._flows()
            flow_result = await flows.completion(run=run, plan=plan)
            verification = await self._verify_plan(
                run, plan, flow_result, delivery_verifier, slot_verifier
            )
            if verification["satisfied"] and verification.get("delivery_checked"):
                self._require_edge(run, "succeeded")
                run.status = "succeeded"
                run.wait_reason = None
                run.finished_at = datetime.now(UTC)
            progress = await flows.progress(run.id)
            return {
                "master_run_id": str(run.id),
                "operation": operation,
                "expected_revision": run.revision,
                "result_revision": run.revision + 1,
                "status": run.status,
                "desired_state": run.desired_state,
                "control_epoch": run.control_epoch,
                "unresolved_external_count": progress["unresolved_external_count"],
                "verification": verification,
            }
        return {
            "master_run_id": str(run.id),
            "operation": operation,
            "expected_revision": run.revision,
            "result_revision": run.revision + 1,
            "status": run.status,
            "desired_state": run.desired_state,
            "control_epoch": run.control_epoch,
            "unresolved_external_count": None,
            "reason": reason or None,
        }

    async def _plan_confirmed(self, plan: DirectorMasterRunPlan) -> bool:
        decision = await self._session.scalar(
            select(DirectorProposalItem)
            .where(
                DirectorProposalItem.id == plan.decision_ref,
                DirectorProposalItem.project_id == self._project.id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        return bool(
            decision
            and decision.status == "accepted"
            and decision.command == PLAN_COMMAND
            and decision.payload.get("plan_id") == str(plan.id)
            and decision.payload.get("master_run_id") == str(plan.master_run_id)
            and decision.payload.get("plan_hash") == plan.plan_hash
            and plan_hash(plan.schema_version, plan.plan_data) == plan.plan_hash
        )

    async def bind_export(
        self, requested: DeliveryPlanRef, episode_number: int
    ) -> BoundDeliveryOutput:
        run = await self._locked(requested.master_run_id)
        plan = await self.current_plan(run)
        if (
            plan is None
            or plan.id != requested.plan_id
            or run.control_epoch != requested.control_epoch
            or run.status not in {"waiting", "running"}
            or run.desired_state != "run"
            or not await self._plan_confirmed(plan)
        ):
            raise ConflictError("此目标尚未确认、已暂停或已更换计划")
        for goal in COMPLETION_RULES.validate_python(plan.plan_data.get("completion")):
            if (
                isinstance(goal, ProjectDeliveryGoal)
                and goal.output_slot is not None
                and goal.planned_episode_count is not None
                and 1 <= episode_number <= goal.planned_episode_count
                and goal.work_type == self._project.work_type
                and goal.planned_episode_count == self._project.planned_episode_count
            ):
                binding = await self._flows().delivery_output(
                    run,
                    plan,
                    goal.output_slot,
                    goal.planned_episode_count,
                )
                if binding is not None:
                    return binding
        raise ConflictError("分集不在此计划的导出范围内")

    async def _verify_plan(
        self,
        run: DirectorMasterRun,
        plan: DirectorMasterRunPlan,
        flow_result: dict[str, object],
        reader: DeliveryVerifier | None,
        slot_reader: DeliverySlotVerifier | None,
    ) -> dict[str, object]:
        try:
            goals = COMPLETION_RULES.validate_python(plan.plan_data.get("completion"))
        except ValidationError:
            return {
                "satisfied": False,
                "checks": [
                    {
                        "rule_id": "plan_completion",
                        "satisfied": False,
                        "reason_code": "MASTER_RUN_COMPLETION_SHAPE",
                    }
                ],
            }
        deliveries = [goal for goal in goals if not isinstance(goal, FlowCompletionGoal)]
        if not deliveries:
            return flow_result
        flow_checks = cast(list[dict[str, object]], flow_result["checks"])
        has_flows = bool(plan.plan_data.get("flows"))
        declared_rules = {goal.rule_id for goal in goals}
        checks = [
            check
            for check in flow_checks
            if has_flows
            or check["rule_id"] in declared_rules
            or check["rule_id"] == "no_unresolved_external"
        ]
        confirmed = await self._plan_confirmed(plan)
        checks.append(
            {
                "rule_id": "confirmed_plan",
                "satisfied": confirmed,
                "reason_code": None if confirmed else "PLAN_CONFIRMATION_UNAVAILABLE",
            }
        )
        observed = plan.plan_data.get("input_versions")
        if observed != {}:
            current_inputs = await self._delivery_inputs_match(observed)
            checks.append(
                {
                    "rule_id": "input_versions",
                    "satisfied": current_inputs,
                    "reason_code": None if current_inputs else "PLAN_INPUT_CHANGED",
                }
            )
        for goal in deliveries:
            targets = goal.targets if isinstance(goal, ProjectDeliveryGoal) else [goal.target]
            reasons: list[str] = []
            evidence: list[dict[str, Any]] = []
            if isinstance(goal, ProjectDeliveryGoal):
                if goal.work_type != self._project.work_type:
                    reasons.append("DELIVERY_WORK_TYPE_CHANGED")
                actual = self._project.planned_episode_count
                if (goal.work_type == "serial_comic" and (goal.output_slot or actual is not None)
                        and (goal.planned_episode_count or len(targets)) != actual):
                    reasons.append("DELIVERY_EPISODE_COUNT_MISMATCH")
            missing_ranges: list[tuple[int, int]] = []
            if isinstance(goal, ProjectDeliveryGoal) and goal.output_slot is not None:
                count = goal.planned_episode_count
                assert count is not None
                flows = self._flows()
                binding = await flows.delivery_output(run, plan, goal.output_slot, count)
                if binding is None or slot_reader is None:
                    reasons.append("DELIVERY_OUTPUT_SLOT_UNAVAILABLE")
                else:
                    output = await slot_reader(binding=binding, episode_count=count)
                    missing_ranges = output.missing_ranges
                    evidence.extend(p.model_dump(mode="json") for p in output.packages)
                    if missing_ranges or len(output.packages) != count:
                        reasons.append("DELIVERY_EPISODE_MISSING")
                    for package in output.packages:
                        reasons.extend(package.blockers)
                    inputs_valid = all(
                        c["satisfied"]
                        for c in checks
                        if c["rule_id"] in {"input_versions", "no_unresolved_external"}
                    )
                    if not reasons and confirmed and inputs_valid:
                        await flows.observe_episode_exports(run, binding, output)
                        refreshed = await flows.completion(run=run, plan=plan)
                        gate_results = cast(list[dict[str, object]], refreshed["checks"])
                        replacements = {c["rule_id"]: c for c in gate_results}
                        checks = [replacements.get(c["rule_id"], c) for c in checks]
            elif reader is None:
                reasons.append("DELIVERY_VERIFIER_UNAVAILABLE")
            else:
                for target in targets:
                    package = await reader(
                        project_id=self._project.id,
                        episode_id=target.episode_id,
                        edit_session_id=target.edit_session_id,
                        timeline_version=target.timeline_version,
                        export_id=target.export_id,
                    )
                    if (
                        package.episode_number is not None
                        and target.episode_number is not None
                        and package.episode_number != target.episode_number
                    ):
                        reasons.append("DELIVERY_EPISODE_CHANGED")
                    evidence.append(package.model_dump(mode="json"))
                    reasons.extend(package.blockers)
            checks.append(
                {
                    "rule_id": goal.rule_id,
                    "scope_ref": str(
                        goal.target.episode_id
                        if isinstance(goal, EpisodeDeliveryGoal)
                        else self._project.id
                    ),
                    "satisfied": not reasons,
                    "reason_code": reasons[0] if reasons else None,
                    "evidence_refs": evidence,
                    "missing_episode_ranges": missing_ranges,
                }
            )
        return {
            "satisfied": all(check["satisfied"] is True for check in checks),
            "checks": checks,
            "delivery_checked": True,
            "plan_id": str(plan.id),
            "plan_revision": plan.revision,
            "plan_hash": plan.plan_hash,
        }

    async def _delivery_inputs_match(self, observed: object) -> bool:
        from app.assets.models import Asset, Scene, Shot
        from app.editing.models import EditSession

        if not isinstance(observed, dict):
            return False
        for key, version in observed.items():
            kind, separator, raw_id = str(key).partition(":")
            if not separator or type(version) is not int:
                return False
            try:
                entity_id = UUID(raw_id)
            except ValueError:
                return False
            if kind == "project":
                if entity_id != self._project.id or version != self._project.version:
                    return False
                continue
            if kind == "scene":
                found = await self._session.scalar(select(Scene.version).join(
                    Episode, Episode.id == Scene.episode_id,
                ).where(Scene.id == entity_id, Episode.project_id == self._project.id)
                    .with_for_update(read=True))
                if found != version:
                    return False
                continue
            models: dict[str, type[Episode] | type[EditSession] | type[Shot] | type[Asset]] = {
                "episode": Episode, "edit_session": EditSession, "shot": Shot, "asset": Asset,
            }
            model = models.get(kind)
            if model is None:
                return False
            found = await self._session.scalar(select(model.version).where(
                model.id == entity_id, model.project_id == self._project.id,
            ).with_for_update(read=True))
            if found != version:
                return False
        return True

    @staticmethod
    def _require_edge(run: DirectorMasterRun, target: str) -> None:
        if target not in ALLOWED_EDGES.get(run.status, frozenset()):
            raise _state_conflict(
                "MASTER_RUN_STATE_CONFLICT",
                "当前状态不允许该操作",
                status=run.status,
                operation_target=target,
            )

    async def archive(
        self, *, run_id: UUID, expected_revision: int, archived: bool,
    ) -> DirectorMasterRun:
        run = await self._locked(run_id)
        if run.revision != expected_revision:
            raise _state_conflict(
                "MASTER_RUN_VERSION_CONFLICT", "目标已变化，请刷新后重新确认",
                current_revision=run.revision,
            )
        if archived:
            if run.status not in TERMINAL_STATUSES:
                raise _state_conflict(
                    "MASTER_RUN_STATE_CONFLICT", "只有已结束的持续目标可以归档",
                    status=run.status,
                )
            if run.archived_at is None:
                run.archived_at = datetime.now(UTC)
                run.revision += 1
        elif run.archived_at is not None:
            run.archived_at = None
            run.revision += 1
        run.updated_at = datetime.now(UTC)
        await self._session.flush()
        await append_master_run_notice(
            self._session, project_id=self._project.id, actor_id=self._actor.id,
            notice=MasterRunChanged(
                run_id=run.id, revision=run.revision, status=run.status,
                desired_state=run.desired_state, control_epoch=run.control_epoch,
            ),
        )
        return run

    async def last_verification(self, run: DirectorMasterRun) -> dict[str, object] | None:
        data = await self._session.scalar(select(DirectorMasterRunControlReceipt.result_data).where(
            DirectorMasterRunControlReceipt.master_run_id == run.id,
            DirectorMasterRunControlReceipt.project_id == self._project.id,
            DirectorMasterRunControlReceipt.operation == "verify",
        ).order_by(DirectorMasterRunControlReceipt.result_revision.desc()).limit(1))
        result = data.get("verification") if isinstance(data, dict) else None
        if isinstance(result, dict) and result.get("plan_id") == str(run.current_plan_id):
            return result
        return None

    async def summary(self, run: DirectorMasterRun) -> dict[str, Any]:
        """Counters come from original Flow/Step/Attempt facts, never a cache."""
        progress = await self._flows().progress(run.id)
        return {
            "progress": {
                "required_steps": progress["required_steps"],
                "completed_steps": progress["completed_steps"],
                "waiting_user": progress["waiting_user"],
                "waiting_execution": progress["waiting_execution"],
                "blocked_steps": progress["blocked_steps"],
            },
            "unresolved_external_count": progress["unresolved_external_count"],
            "read_blockers": [],
        }


__all__ = [
    "ALLOWED_EDGES",
    "CONTROL_OPERATIONS",
    "MasterRunService",
    "PLAN_COMMAND",
    "PLAN_SCHEMA_VERSION",
    "plan_hash",
]
