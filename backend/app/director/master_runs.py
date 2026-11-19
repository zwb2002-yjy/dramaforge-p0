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
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.contracts.domain_events import (
    MasterRunChanged,
    MasterRunPlanApplied,
    MasterRunPlanProposed,
)
from app.director.business_flows import (
    BusinessFlowDefinitionRegistry,
    BusinessFlowService,
    validate_plan_flows,
)
from app.director.master_run_models import (
    DirectorMasterRun,
    DirectorMasterRunControlReceipt,
    DirectorMasterRunPlan,
)
from app.director.master_run_notices import append_master_run_notice
from app.director.proposal_models import DirectorProposalItem
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
    @staticmethod
    def validate_plan_data(plan_data: dict[str, object]) -> None:
        keys = set(plan_data)
        if PLAN_TOP_LEVEL_KEYS - keys or keys - PLAN_TOP_LEVEL_KEYS - PLAN_OPTIONAL_KEYS:
            raise ValidationAppError(
                "计划字段不完整或包含未知字段", details={"code": "MASTER_RUN_PLAN_SHAPE"},
            )
        basis = plan_data.get("decision_basis")
        if not isinstance(basis, dict):
            raise ValidationAppError("计划缺少 decision_basis")
        required = {
            "expected_run_revision", "expected_control_epoch",
            "current_plan_id", "current_plan_revision",
        }
        if set(basis) != required:
            raise ValidationAppError(
                "decision_basis 字段不正确", details={"code": "MASTER_RUN_PLAN_BASIS"},
            )
        if (basis["current_plan_id"] is None) != (basis["current_plan_revision"] is None):
            raise ValidationAppError(
                "current_plan_id 与 current_plan_revision 必须同时为空或同时存在",
                details={"code": "MASTER_RUN_PLAN_BASIS"},
            )
        # Validate the flow list early so a bad plan never reaches Apply.
        validate_plan_flows(plan_data.get("flows"), allow_empty=True)

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
        decision_ref: UUID,
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
        item = await self._session.scalar(
            select(DirectorProposalItem).where(
                DirectorProposalItem.id == decision_ref,
                DirectorProposalItem.project_id == self._project.id,
                DirectorProposalItem.command == PLAN_COMMAND,
            )
        )
        if item is None:
            raise ValidationAppError(
                "计划必须绑定本项目的一个 typed 计划确认项",
                details={"code": "MASTER_RUN_PLAN_DECISION"},
            )
        digest = plan_hash(schema_version, plan_data)
        existing = await self._session.scalar(
            select(DirectorMasterRunPlan).where(
                DirectorMasterRunPlan.master_run_id == run.id,
                DirectorMasterRunPlan.plan_hash == digest,
            )
        )
        if existing is not None:
            return existing
        next_revision = int(
            await self._session.scalar(
                select(func.coalesce(func.max(DirectorMasterRunPlan.revision), 0)).where(
                    DirectorMasterRunPlan.master_run_id == run.id
                )
            )
            or 0
        ) + 1
        plan = DirectorMasterRunPlan(
            project_id=self._project.id,
            master_run_id=run.id,
            revision=next_revision,
            schema_version=schema_version,
            plan_hash=digest,
            plan_data=plan_data,
            decision_ref=decision_ref,
            created_by_turn_id=created_by_turn_id,
            created_by_actor_id=self._actor.id,
        )
        self._session.add(plan)
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
                decision_ref=decision_ref,
            ),
        )
        return plan

    async def apply_plan(
        self, *, run_id: UUID, plan_id: UUID, expected_revision: int,
        expected_control_epoch: int,
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
        current = await self.current_plan(run)
        if current is not None and plan.revision < current.revision:
            raise _state_conflict(
                "MASTER_RUN_PLAN_SUPERSEDED", "不能把目标退回到更早的计划快照",
                current_plan_revision=current.revision,
            )
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
            dispositions=_normalize_dispositions(plan.plan_data.get("flow_dispositions")),
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
        return plan

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
        self, *, run_id: UUID, operation: str, expected_revision: int, reason: str = "",
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
                "MASTER_RUN_VERSION_CONFLICT", "目标已变化，请刷新后重新确认",
                current_revision=run.revision,
            )
        result = await self._apply_control(run, operation=operation, reason=reason)
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
            self._session, project_id=self._project.id, actor_id=self._actor.id,
            notice=MasterRunChanged(
                run_id=run.id, revision=run.revision, status=run.status,
                desired_state=run.desired_state, control_epoch=run.control_epoch,
            ),
        )
        return dict(result)

    async def _apply_control(
        self, run: DirectorMasterRun, *, operation: str, reason: str,
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
            verification = await flows.completion(run=run, plan=plan)
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


def _normalize_dispositions(value: object) -> dict[str, str] | None:
    """Accept the frozen plan shape: ``[{instance_id, disposition}]`` or a mapping."""
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    if isinstance(value, list):
        result: dict[str, str] = {}
        for item in value:
            if not isinstance(item, dict) or set(item) != {"instance_id", "disposition"}:
                raise ValidationAppError(
                    "flow_dispositions 项必须只含 instance_id 与 disposition",
                    details={"code": "BUSINESS_FLOW_DISPOSITION_SHAPE"},
                )
            result[str(item["instance_id"])] = str(item["disposition"])
        return result
    raise ValidationAppError(
        "flow_dispositions 必须是列表或对象",
        details={"code": "BUSINESS_FLOW_DISPOSITION_SHAPE"},
    )


__all__ = [
    "ALLOWED_EDGES",
    "CONTROL_OPERATIONS",
    "MasterRunService",
    "PLAN_COMMAND",
    "PLAN_SCHEMA_VERSION",
    "plan_hash",
]
