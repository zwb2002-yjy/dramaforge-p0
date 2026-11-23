"""Registered BusinessFlow definitions and their durable coordination service.

Definitions are versioned code registrations: key, version, contract hash, step
specs, completion rules and a LangGraph entrypoint name. Clients never supply
function names or arbitrary DAGs. The service owns instance/step/attempt
coordination only; every action runs through the existing controlled tool
registry, and Production receipts stay in the original NodeRun facts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.assets.models import Episode, Scene, Shot
from app.contracts.domain_events import BusinessFlowChanged, BusinessStepChanged
from app.director.agent_tools import ToolRegistry
from app.director.business_flow_models import (
    FLOW_TERMINAL_STATUSES,
    DirectorBusinessFlowInstance,
    DirectorBusinessFlowStep,
    DirectorBusinessFlowStepAttempt,
)
from app.director.master_run_models import DirectorMasterRun, DirectorMasterRunPlan
from app.director.master_run_notices import append_master_run_notice
from app.director.turn_models import DirectorTurn
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

STEP_ACTION_KINDS = frozenset({"read", "proposal", "apply", "production", "repair", "review"})
INSTANCE_TERMINAL = FLOW_TERMINAL_STATUSES
STEP_TERMINAL = frozenset({"succeeded", "failed", "skipped", "cancelled", "superseded"})
FLOW_SCOPE_TYPES = frozenset({"project", "scene", "shot"})
# Read/proposal actions are database-only; a running attempt older than this lost
# its owner. It is failed, never replayed (a proposal may already be committed).
FLOW_ATTEMPT_STALE_SECONDS = 300
COMPLETION_RULE_IDS = frozenset(
    {"all_required_steps_succeeded", "no_unresolved_external", "business_flow_completed_v1"}
)
RESUME_RULE_IDS = frozenset({"retain_completed_steps"})
PLAN_FLOW_KEYS = frozenset(
    {"flow_key", "definition_key", "definition_version", "scope_type", "scope_entity_id", "input"}
)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    )


def content_hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FlowStepSpec:
    """One registered step; the tool name must exist in the controlled registry."""

    step_key: str
    tool_name: str
    action_kind: Literal["read", "proposal", "apply", "production", "repair", "review"]
    required: bool = True
    dependencies: tuple[str, ...] = ()
    input_keys: tuple[str, ...] = ()
    completion_rule_id: str = "tool_receipt_ok"

    def contract(self) -> dict[str, object]:
        return {
            "step_key": self.step_key,
            "tool_name": self.tool_name,
            "action_kind": self.action_kind,
            "required": self.required,
            "dependencies": list(self.dependencies),
            "input_keys": list(self.input_keys),
            "completion_rule_id": self.completion_rule_id,
        }


@dataclass(frozen=True)
class BusinessFlowDefinition:
    """One frozen flow contract registered in code."""

    flow_key: str
    definition_key: str
    definition_version: str
    state_schema_version: str
    scope_type: Literal["project", "scene", "shot"]
    steps: tuple[FlowStepSpec, ...]
    completion_rule_ids: tuple[str, ...]
    resume_rule_id: str
    graph_entrypoint: str
    contract_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_definition(self)
        object.__setattr__(self, "contract_hash", content_hash(self.contract()))

    def contract(self) -> dict[str, object]:
        return {
            "flow_key": self.flow_key,
            "definition_key": self.definition_key,
            "definition_version": self.definition_version,
            "state_schema_version": self.state_schema_version,
            "scope_type": self.scope_type,
            "steps": [step.contract() for step in self.steps],
            "completion_rule_ids": list(self.completion_rule_ids),
            "resume_rule_id": self.resume_rule_id,
            "graph_entrypoint": self.graph_entrypoint,
        }


def _validate_definition(definition: BusinessFlowDefinition) -> None:
    if not definition.flow_key.strip() or len(definition.flow_key) > 120:
        raise ValueError("flow_key must contain 1 to 120 characters")
    if definition.scope_type not in FLOW_SCOPE_TYPES:
        raise ValueError("unsupported flow scope")
    if not definition.steps:
        raise ValueError("a flow definition needs at least one step")
    keys = [step.step_key for step in definition.steps]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate step_key in flow definition")
    known = set(keys)
    for step in definition.steps:
        if step.action_kind not in STEP_ACTION_KINDS:
            raise ValueError(f"unsupported action_kind {step.action_kind!r}")
        unknown = set(step.dependencies) - known
        if unknown:
            raise ValueError(f"unknown dependency {sorted(unknown)[0]!r}")
        if step.step_key in step.dependencies:
            raise ValueError("a step cannot depend on itself")
    _require_acyclic(definition.steps)
    if not definition.completion_rule_ids:
        raise ValueError("a flow definition needs completion rules")
    unknown_rules = set(definition.completion_rule_ids) - COMPLETION_RULE_IDS
    if unknown_rules:
        raise ValueError(f"unknown completion rule {sorted(unknown_rules)[0]!r}")
    if definition.resume_rule_id not in RESUME_RULE_IDS:
        raise ValueError("unknown resume rule")


def _require_acyclic(steps: Sequence[FlowStepSpec]) -> None:
    by_key = {step.step_key: step for step in steps}
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(key: str) -> None:
        if key in done:
            return
        if key in visiting:
            raise ValueError("flow definition contains a dependency cycle")
        visiting.add(key)
        for dependency in by_key[key].dependencies:
            visit(dependency)
        visiting.discard(key)
        done.add(key)

    for key in by_key:
        visit(key)


class BusinessFlowDefinitionRegistry:
    """Version-frozen registry; a different contract cannot overwrite a version."""

    def __init__(self, definitions: Iterable[BusinessFlowDefinition] = ()) -> None:
        self._entries: dict[str, dict[str, BusinessFlowDefinition]] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: BusinessFlowDefinition) -> BusinessFlowDefinition:
        versions = self._entries.setdefault(definition.definition_key, {})
        existing = versions.get(definition.definition_version)
        if existing is not None and existing.contract_hash != definition.contract_hash:
            raise ValueError(
                f"definition contract mismatch for {definition.definition_key}@"
                f"{definition.definition_version}"
            )
        versions[definition.definition_version] = definition
        return definition

    def get_versioned(
        self, definition_key: str, definition_version: str
    ) -> BusinessFlowDefinition | None:
        return self._entries.get(definition_key, {}).get(definition_version)

    def require(self, definition_key: str, definition_version: str) -> BusinessFlowDefinition:
        definition = self.get_versioned(definition_key, definition_version)
        if definition is None:
            raise ValidationAppError(
                "业务定义未注册或版本不受支持",
                details={
                    "code": "BUSINESS_FLOW_DEFINITION_UNKNOWN",
                    "definition_key": definition_key,
                    "definition_version": definition_version,
                },
            )
        return definition

    def definitions(self) -> list[BusinessFlowDefinition]:
        return [
            definition
            for versions in self._entries.values()
            for definition in versions.values()
        ]

    def keys(self) -> list[str]:
        return sorted(self._entries)


SHOT_PROMPT_REVIEW_V1 = BusinessFlowDefinition(
    flow_key="shot_prompt_review",
    definition_key="shot_prompt_review",
    definition_version="1",
    state_schema_version="business-flow-state-v1",
    scope_type="shot",
    steps=(
        FlowStepSpec(
            step_key="read_shot",
            tool_name="shot_get",
            action_kind="read",
            input_keys=("shot_id",),
        ),
        FlowStepSpec(
            step_key="propose_prompt",
            tool_name="shot_prompt_propose",
            action_kind="proposal",
            dependencies=("read_shot",),
            input_keys=("shot_id", "expected_version", "image_prompt", "rationale"),
        ),
    ),
    completion_rule_ids=("all_required_steps_succeeded", "no_unresolved_external"),
    resume_rule_id="retain_completed_steps",
    graph_entrypoint="shot_prompt_review_v1",
)


SCENE_PROMPT_REVIEW_V1 = BusinessFlowDefinition(
    flow_key="scene_prompt_review",
    definition_key="scene_prompt_review",
    definition_version="1",
    state_schema_version="business-flow-state-v1",
    scope_type="scene",
    steps=(
        FlowStepSpec(
            step_key="read_scene",
            tool_name="scene_get",
            action_kind="read",
            input_keys=("scene_id",),
        ),
        FlowStepSpec(
            step_key="list_shots",
            tool_name="shots_list",
            action_kind="read",
            dependencies=("read_scene",),
            input_keys=("scene_id", "limit"),
        ),
        FlowStepSpec(
            step_key="propose_prompt",
            tool_name="shot_prompt_propose",
            action_kind="proposal",
            dependencies=("list_shots",),
            input_keys=("shot_id", "expected_version", "image_prompt", "rationale"),
        ),
    ),
    completion_rule_ids=("all_required_steps_succeeded", "no_unresolved_external"),
    resume_rule_id="retain_completed_steps",
    graph_entrypoint="scene_prompt_review_v1",
)

SHOT_MODEL_CONTRACT_REVIEW_V1 = BusinessFlowDefinition(
    flow_key="shot_model_contract_review",
    definition_key="shot_model_contract_review",
    definition_version="1",
    state_schema_version="business-flow-state-v1",
    scope_type="shot",
    steps=(
        FlowStepSpec(
            step_key="read_shot",
            tool_name="shot_get",
            action_kind="read",
            input_keys=("shot_id",),
        ),
        FlowStepSpec(
            step_key="read_capabilities",
            tool_name="model_capabilities",
            action_kind="read",
            dependencies=("read_shot",),
            input_keys=("shot_id", "stage"),
        ),
        FlowStepSpec(
            step_key="compile_preview",
            tool_name="model_compile_preview",
            action_kind="read",
            dependencies=("read_capabilities",),
            input_keys=("shot_id", "stage", "binding_id", "manifest_hash"),
        ),
    ),
    completion_rule_ids=("all_required_steps_succeeded", "no_unresolved_external"),
    resume_rule_id="retain_completed_steps",
    graph_entrypoint="shot_model_contract_review_v1",
)

PROJECT_ASSET_AUDIT_V1 = BusinessFlowDefinition(
    flow_key="project_asset_audit",
    definition_key="project_asset_audit",
    definition_version="1",
    state_schema_version="business-flow-state-v1",
    scope_type="project",
    steps=(
        FlowStepSpec(
            step_key="list_assets",
            tool_name="assets_list",
            action_kind="read",
            input_keys=("limit",),
        ),
        FlowStepSpec(
            step_key="read_asset",
            tool_name="asset_get",
            action_kind="read",
            dependencies=("list_assets",),
            input_keys=("asset_id",),
        ),
    ),
    completion_rule_ids=("all_required_steps_succeeded", "no_unresolved_external"),
    resume_rule_id="retain_completed_steps",
    graph_entrypoint="project_asset_audit_v1",
)

DEFAULT_DEFINITIONS = BusinessFlowDefinitionRegistry(
    (
        SHOT_PROMPT_REVIEW_V1,
        SCENE_PROMPT_REVIEW_V1,
        SHOT_MODEL_CONTRACT_REVIEW_V1,
        PROJECT_ASSET_AUDIT_V1,
    )
)

_registry = DEFAULT_DEFINITIONS


def definition_registry() -> BusinessFlowDefinitionRegistry:
    """Process-wide registry; tests may register fixtures on a private instance."""

    return _registry


# ---------------------------------------------------------------------------
# Action execution port
# ---------------------------------------------------------------------------


class FlowActionError(Exception):
    """A bounded action failure; ``unknown_submission`` keeps its slot."""

    def __init__(self, code: str, *, unknown_submission: bool = False) -> None:
        self.code = code
        self.unknown_submission = unknown_submission
        super().__init__(code)


class FlowActionExecutor(Protocol):
    """Executes one registered controlled tool for a flow attempt."""

    async def execute(
        self,
        *,
        action_key: str,
        arguments: Mapping[str, object],
        call_id: str,
        scope_type: str,
        scope_entity_id: UUID,
        attempt_id: UUID,
        thread_id: UUID | None,
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class PlanFlowSpec:
    flow_key: str
    definition_key: str
    definition_version: str
    scope_type: str
    scope_entity_id: UUID
    input: dict[str, object]


def normalize_dispositions(value: object) -> dict[str, str] | None:
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


def validate_plan_flows(value: object, *, allow_empty: bool = False) -> list[PlanFlowSpec]:
    """Validate the plan's ``flows`` array before any instance is created."""
    if not isinstance(value, list):
        raise ValidationAppError(
            "计划的 flows 必须是数组", details={"code": "BUSINESS_FLOW_PLAN_SHAPE"},
        )
    if not value:
        if allow_empty:
            return []
        raise ValidationAppError(
            "计划必须列出至少一个业务流程", details={"code": "BUSINESS_FLOW_PLAN_EMPTY"},
        )
    specs: list[PlanFlowSpec] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) - PLAN_FLOW_KEYS or not {
            "flow_key", "definition_key", "definition_version", "scope_type",
            "scope_entity_id", "input",
        } <= set(raw):
            raise ValidationAppError(
                "计划中的流程字段不完整或包含未知字段",
                details={"code": "BUSINESS_FLOW_PLAN_SHAPE"},
            )
        scope_type = raw["scope_type"]
        if not isinstance(scope_type, str) or scope_type not in FLOW_SCOPE_TYPES:
            raise ValidationAppError(
                "流程作用域不受支持", details={"code": "BUSINESS_FLOW_SCOPE"},
            )
        try:
            scope_entity_id = UUID(str(raw["scope_entity_id"]))
        except ValueError as exc:
            raise ValidationAppError(
                "流程作用域标识无效", details={"code": "BUSINESS_FLOW_SCOPE"},
            ) from exc
        flow_key = raw["flow_key"]
        if not isinstance(flow_key, str) or not flow_key.strip() or len(flow_key) > 120:
            raise ValidationAppError(
                "流程键无效", details={"code": "BUSINESS_FLOW_PLAN_SHAPE"},
            )
        if flow_key in seen:
            raise ValidationAppError(
                "同一计划内流程键必须唯一", details={"code": "BUSINESS_FLOW_PLAN_DUPLICATE"},
            )
        seen.add(flow_key)
        definition_key = raw["definition_key"]
        definition_version = raw["definition_version"]
        if not isinstance(definition_key, str) or not isinstance(definition_version, str):
            raise ValidationAppError(
                "业务定义标识无效", details={"code": "BUSINESS_FLOW_PLAN_SHAPE"},
            )
        input_data = raw["input"]
        if not isinstance(input_data, dict):
            raise ValidationAppError(
                "流程输入必须是对象", details={"code": "BUSINESS_FLOW_PLAN_SHAPE"},
            )
        specs.append(
            PlanFlowSpec(
                flow_key=flow_key,
                definition_key=definition_key,
                definition_version=definition_version,
                scope_type=scope_type,
                scope_entity_id=scope_entity_id,
                input=dict(input_data),
            )
        )
    return specs


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class BusinessFlowService:
    """Caller owns the transaction; every method re-checks project ownership."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        actor: User,
        project: Project,
        registry: BusinessFlowDefinitionRegistry | None = None,
    ) -> None:
        self._session = session
        self._actor = actor
        self._project = project
        self._registry = registry or _registry

    # ----- reads -----------------------------------------------------------
    async def list_for_run(self, run_id: UUID) -> list[DirectorBusinessFlowInstance]:
        return list(
            await self._session.scalars(
                select(DirectorBusinessFlowInstance)
                .where(
                    DirectorBusinessFlowInstance.project_id == self._project.id,
                    DirectorBusinessFlowInstance.supervisor_run_id == run_id,
                )
                .order_by(
                    DirectorBusinessFlowInstance.created_at,
                    DirectorBusinessFlowInstance.id,
                )
            )
        )

    async def get(self, instance_id: UUID) -> DirectorBusinessFlowInstance:
        instance = await self._session.scalar(
            select(DirectorBusinessFlowInstance).where(
                DirectorBusinessFlowInstance.id == instance_id,
                DirectorBusinessFlowInstance.project_id == self._project.id,
            )
        )
        if instance is None:
            raise NotFoundError("business flow not found")
        return instance

    async def steps(self, instance_id: UUID) -> list[DirectorBusinessFlowStep]:
        await self.get(instance_id)
        return list(
            await self._session.scalars(
                select(DirectorBusinessFlowStep)
                .where(
                    DirectorBusinessFlowStep.instance_id == instance_id,
                    DirectorBusinessFlowStep.project_id == self._project.id,
                )
                .order_by(DirectorBusinessFlowStep.step_key)
            )
        )

    async def attempts(self, step_id: UUID) -> list[DirectorBusinessFlowStepAttempt]:
        return list(
            await self._session.scalars(
                select(DirectorBusinessFlowStepAttempt)
                .where(
                    DirectorBusinessFlowStepAttempt.step_id == step_id,
                    DirectorBusinessFlowStepAttempt.project_id == self._project.id,
                )
                .order_by(DirectorBusinessFlowStepAttempt.attempt_no)
            )
        )

    # ----- creation --------------------------------------------------------
    async def create_from_plan(
        self,
        *,
        run: DirectorMasterRun,
        plan: DirectorMasterRunPlan,
        created_by_turn_id: UUID | None = None,
        skip_flow_keys: Collection[str] = (),
    ) -> list[DirectorBusinessFlowInstance]:
        """Create one frozen instance per plan flow; idempotent per (run, plan, key).

        ``skip_flow_keys`` names flows retained from an earlier plan: their
        instance keeps its original plan identity, so no duplicate is created.
        """
        if plan.master_run_id != run.id or plan.project_id != self._project.id:
            raise ConflictError(
                "计划不属于该持续目标", details={"code": "BUSINESS_FLOW_PLAN_SCOPE"},
            )
        specs = validate_plan_flows(plan.plan_data.get("flows"), allow_empty=True)
        controlled = {spec.name for spec in ToolRegistry().specs()}
        created: list[DirectorBusinessFlowInstance] = []
        for spec in specs:
            if spec.flow_key in skip_flow_keys:
                continue
            definition = self._registry.require(spec.definition_key, spec.definition_version)
            if definition.scope_type != spec.scope_type:
                raise ValidationAppError(
                    "流程作用域与注册定义不一致",
                    details={"code": "BUSINESS_FLOW_SCOPE"},
                )
            unknown_tools = sorted(
                {step.tool_name for step in definition.steps} - controlled
            )
            if unknown_tools:
                raise ValidationAppError(
                    "流程引用了未注册的受控工具",
                    details={
                        "code": "BUSINESS_FLOW_TOOL_UNKNOWN",
                        "tool_name": unknown_tools[0],
                    },
                )
            await self._require_scope(spec.scope_type, spec.scope_entity_id)
            existing = await self._session.scalar(
                select(DirectorBusinessFlowInstance).where(
                    DirectorBusinessFlowInstance.project_id == self._project.id,
                    DirectorBusinessFlowInstance.supervisor_run_id == run.id,
                    DirectorBusinessFlowInstance.plan_id == plan.id,
                    DirectorBusinessFlowInstance.flow_key == spec.flow_key,
                )
            )
            if existing is not None:
                created.append(existing)
                continue
            instance = DirectorBusinessFlowInstance(
                project_id=self._project.id,
                supervisor_run_id=run.id,
                plan_id=plan.id,
                plan_revision=plan.revision,
                flow_key=spec.flow_key,
                definition_key=definition.definition_key,
                definition_version=definition.definition_version,
                contract_hash=definition.contract_hash,
                input_hash=content_hash(spec.input),
                input_data=spec.input,
                scope_type=spec.scope_type,
                scope_entity_id=spec.scope_entity_id,
                created_by_turn_id=created_by_turn_id,
                status="pending",
                revision=1,
            )
            self._session.add(instance)
            await self._session.flush()
            for step_spec in definition.steps:
                self._session.add(
                    DirectorBusinessFlowStep(
                        project_id=self._project.id,
                        instance_id=instance.id,
                        supervisor_run_id=run.id,
                        plan_id=plan.id,
                        plan_revision=plan.revision,
                        step_key=step_spec.step_key,
                        scope_type=spec.scope_type,
                        scope_entity_id=spec.scope_entity_id,
                        required=step_spec.required,
                        input_refs={
                            key: spec.input[key]
                            for key in step_spec.input_keys
                            if key in spec.input
                        },
                        completion_spec={"rule_id": step_spec.completion_rule_id},
                        dependencies=list(step_spec.dependencies),
                        result_refs=[],
                        status="pending",
                    )
                )
            await self._session.flush()
            await self._notify_instance(instance)
            created.append(instance)
        return created

    async def _require_scope(self, scope_type: str, scope_entity_id: UUID) -> None:
        if scope_type == "project":
            if scope_entity_id != self._project.id:
                raise NotFoundError("flow scope not found")
            return
        if scope_type == "scene":
            found = await self._session.scalar(
                select(Scene.id)
                .join(Episode, Episode.id == Scene.episode_id)
                .where(
                    Scene.id == scope_entity_id,
                    Episode.project_id == self._project.id,
                )
            )
        else:
            found = await self._session.scalar(
                select(Shot.id).where(
                    Shot.id == scope_entity_id,
                    Shot.project_id == self._project.id,
                )
            )
        if found is None:
            raise NotFoundError("flow scope not found")

    # ----- dispositions ----------------------------------------------------
    async def apply_dispositions(
        self,
        *,
        run: DirectorMasterRun,
        plan: DirectorMasterRunPlan,
        dispositions: Mapping[str, str] | None,
    ) -> dict[str, object]:
        """Retain/supersede/cancel every prior non-terminal instance exactly once."""
        instances = await self.list_for_run(run.id)
        prior = [
            instance
            for instance in instances
            if instance.plan_id != plan.id and instance.status not in INSTANCE_TERMINAL
        ]
        chosen = dict(dispositions or {})
        unknown = set(chosen) - {str(instance.id) for instance in prior}
        if unknown:
            raise ValidationAppError(
                "flow_dispositions 只能引用当前计划之前的非终态流程",
                details={"code": "BUSINESS_FLOW_DISPOSITION_UNKNOWN"},
            )
        missing = [str(instance.id) for instance in prior if str(instance.id) not in chosen]
        if missing:
            raise ConflictError(
                "新计划必须为每个既有非终态流程给出 retain/supersede/cancel",
                details={
                    "code": "BUSINESS_FLOW_DISPOSITION_REQUIRED",
                    "missing": missing,
                },
            )
        counts = {"retain": 0, "supersede": 0, "cancel": 0}
        retained: list[str] = []
        current = {
            spec.flow_key: spec
            for spec in validate_plan_flows(plan.plan_data.get("flows"), allow_empty=True)
        }
        for instance in prior:
            decision = chosen[str(instance.id)]
            if decision == "retain":
                spec = current.get(instance.flow_key)
                if (
                    spec is None
                    or spec.definition_key != instance.definition_key
                    or spec.definition_version != instance.definition_version
                    or spec.scope_type != instance.scope_type
                    or spec.scope_entity_id != instance.scope_entity_id
                    or content_hash(spec.input) != instance.input_hash
                ):
                    raise ConflictError(
                        "输入或定义已变化的流程不能 retain",
                        details={
                            "code": "BUSINESS_FLOW_RETAIN_INELIGIBLE",
                            "instance_id": str(instance.id),
                        },
                    )
                counts["retain"] += 1
                retained.append(instance.flow_key)
                continue
            if decision not in {"supersede", "cancel"}:
                raise ValidationAppError(
                    "不支持的流程处置", details={"code": "BUSINESS_FLOW_DISPOSITION_UNKNOWN"},
                )
            await self._cancel_instance(
                instance,
                terminal_reason="superseded" if decision == "supersede" else "cancelled",
            )
            counts[decision] += 1
        result: dict[str, object] = dict(counts)
        result["retained_flow_keys"] = retained
        return result

    async def _cancel_instance(
        self, instance: DirectorBusinessFlowInstance, *, terminal_reason: str,
    ) -> None:
        now = datetime.now(UTC)
        instance.status = "cancelled"
        instance.terminal_reason = terminal_reason
        instance.wait_reason = None
        instance.finished_at = now
        instance.revision += 1
        instance.updated_at = now
        for step in await self._steps_of(instance.id):
            if step.status in STEP_TERMINAL:
                continue
            step.status = "cancelled"
            step.wait_reason = None
            step.revision += 1
            step.updated_at = now
            await self._notify_step(step)
        await self._session.flush()
        await self._notify_instance(instance)

    async def cancel_run(self, run: DirectorMasterRun, *, reason: str) -> int:
        """Cancel unfinished flows of a stopped run; successes stay readable."""
        cancelled = 0
        for instance in await self.list_for_run(run.id):
            if instance.status in INSTANCE_TERMINAL:
                continue
            await self._cancel_instance(instance, terminal_reason=reason or "cancelled")
            cancelled += 1
        return cancelled

    # ----- execution -------------------------------------------------------
    async def ready_steps(
        self, instance: DirectorBusinessFlowInstance
    ) -> list[DirectorBusinessFlowStep]:
        steps = await self._steps_of(instance.id)
        by_key = {step.step_key: step for step in steps}
        ready: list[DirectorBusinessFlowStep] = []
        for step in steps:
            if step.status != "pending":
                continue
            dependencies = [str(key) for key in (step.dependencies or [])]
            if all(
                by_key.get(key) is not None
                and by_key[key].status in {"succeeded", "skipped"}
                for key in dependencies
            ):
                ready.append(step)
        return ready

    async def advance(
        self,
        instance: DirectorBusinessFlowInstance,
        *,
        executor: FlowActionExecutor,
        max_parallel: int = 2,
    ) -> DirectorBusinessFlowInstance:
        """Run dependency-ready steps through the controlled tool registry.

        Read/proposal/apply actions are database-only in this batch, so the
        caller's transaction stays short. Production/repair actions are recorded
        as waiting until the authorized admission port is wired (I6b); this
        service never submits a Provider create on its own.
        """
        if not 1 <= max_parallel <= 4:
            raise ValidationAppError("max_parallel must be between 1 and 4")
        if instance.status in INSTANCE_TERMINAL:
            return instance
        definition = self._registry.require(
            instance.definition_key, instance.definition_version
        )
        specs = {spec.step_key: spec for spec in definition.steps}
        semaphore = asyncio.Semaphore(max_parallel)
        await self._recover_stuck_attempts(instance)
        if instance.status in INSTANCE_TERMINAL:
            return instance

        async def invoke(
            step: DirectorBusinessFlowStep,
            spec: FlowStepSpec,
            attempt: DirectorBusinessFlowStepAttempt,
            thread_id: UUID | None,
        ) -> dict[str, object] | FlowActionError:
            async with semaphore:
                try:
                    return await executor.execute(
                        action_key=spec.tool_name,
                        arguments=dict(step.input_refs or {}),
                        call_id=attempt.command_key,
                        scope_type=step.scope_type,
                        scope_entity_id=step.scope_entity_id,
                        attempt_id=attempt.id,
                        thread_id=thread_id,
                    )
                except FlowActionError as exc:
                    return exc

        # Each wave prepares attempts in the session, runs the tool calls
        # concurrently without touching it, then records results sequentially.
        # SQLAlchemy sessions are not concurrency-safe, so this is the only
        # supported shape for controlled parallelism.
        for _wave in range(len(definition.steps) + 1):
            ready = await self.ready_steps(instance)
            if not ready:
                break
            instance.status = "running"
            instance.wait_reason = "flow_running"
            instance.revision += 1
            instance.updated_at = datetime.now(UTC)
            await self._session.flush()
            await self._notify_instance(instance)
            prepared: list[
                tuple[
                    DirectorBusinessFlowStep,
                    FlowStepSpec,
                    DirectorBusinessFlowStepAttempt,
                    UUID | None,
                ]
            ] = []
            thread_id = await self._origin_thread_id(instance)
            for step in ready:
                spec = specs[step.step_key]
                attempt = await self._prepare_attempt(instance, step, spec)
                if attempt is not None:
                    prepared.append((step, spec, attempt, thread_id))
            await self._session.flush()
            if not prepared:
                continue
            outcomes = await asyncio.gather(
                *(invoke(step, spec, attempt, thread) for step, spec, attempt, thread in prepared)
            )
            for (step, _spec, attempt, _thread), outcome in zip(
                prepared, outcomes, strict=True
            ):
                if isinstance(outcome, FlowActionError):
                    await self._record_failure(attempt, step, outcome)
                else:
                    await self._record_result(attempt, step, outcome)
        return await self._settle_instance(instance)

    async def _origin_thread_id(
        self, instance: DirectorBusinessFlowInstance
    ) -> UUID | None:
        if instance.created_by_turn_id is None:
            return None
        turn = await self._session.get(DirectorTurn, instance.created_by_turn_id)
        return turn.thread_id if turn is not None else None

    async def _recover_stuck_attempts(
        self, instance: DirectorBusinessFlowInstance
    ) -> None:
        """Fail attempts whose owner vanished; never replay their side effects."""
        cutoff = datetime.now(UTC) - timedelta(seconds=FLOW_ATTEMPT_STALE_SECONDS)
        stuck = [
            attempt
            for attempt in await self._session.scalars(
                select(DirectorBusinessFlowStepAttempt).where(
                    DirectorBusinessFlowStepAttempt.instance_id == instance.id,
                    DirectorBusinessFlowStepAttempt.project_id == self._project.id,
                    DirectorBusinessFlowStepAttempt.status == "running",
                )
            )
            if attempt.updated_at is not None and _utc(attempt.updated_at) < cutoff
        ]
        if not stuck:
            return
        now = datetime.now(UTC)
        for attempt in stuck:
            attempt.status = "failed"
            attempt.error_code = "FLOW_ATTEMPT_STALE"
            attempt.revision += 1
            attempt.updated_at = now
            step = await self._session.get(DirectorBusinessFlowStep, attempt.step_id)
            if step is not None and step.status == "running":
                step.status = "failed"
                step.wait_reason = None
                step.revision += 1
                step.updated_at = now
                await self._notify_step(step)
        await self._session.flush()
        await self._settle_instance(instance)

    async def _prepare_attempt(
        self,
        instance: DirectorBusinessFlowInstance,
        step: DirectorBusinessFlowStep,
        spec: FlowStepSpec,
    ) -> DirectorBusinessFlowStepAttempt | None:
        if spec.action_kind in {"production", "repair"}:
            # Authorized production admission belongs to I6b; never create here.
            step.status = "waiting_execution"
            step.wait_reason = "production_admission_pending"
            step.revision += 1
            step.updated_at = datetime.now(UTC)
            await self._notify_step(step)
            return None
        attempt_no = int(
            await self._session.scalar(
                select(func.coalesce(func.max(DirectorBusinessFlowStepAttempt.attempt_no), 0))
                .where(DirectorBusinessFlowStepAttempt.step_id == step.id)
            )
            or 0
        ) + 1
        attempt = DirectorBusinessFlowStepAttempt(
            project_id=self._project.id,
            step_id=step.id,
            instance_id=instance.id,
            supervisor_run_id=instance.supervisor_run_id,
            plan_id=instance.plan_id,
            plan_revision=instance.plan_revision,
            scope_type=step.scope_type,
            scope_entity_id=step.scope_entity_id,
            attempt_no=attempt_no,
            control_epoch=0,
            input_hash=content_hash(dict(step.input_refs or {})),
            payload_hash=content_hash({"tool": spec.tool_name, "input": step.input_refs}),
            input_snapshot=dict(step.input_refs or {}),
            action_kind=spec.action_kind,
            action_key=spec.tool_name,
            command_key=f"flow:{step.id}:{attempt_no}",
            status="running",
            revision=1,
        )
        self._session.add(attempt)
        step.status = "running"
        step.revision += 1
        step.updated_at = datetime.now(UTC)
        await self._notify_step(step)
        return attempt

    async def _record_result(
        self,
        attempt: DirectorBusinessFlowStepAttempt,
        step: DirectorBusinessFlowStep,
        result: Mapping[str, object],
    ) -> None:
        now = datetime.now(UTC)
        ok = result.get("ok") is True
        attempt.receipt_ref = dict(result)
        attempt.status = "succeeded" if ok else "failed"
        attempt.error_code = None if ok else str(result.get("error_code") or "ACTION_FAILED")[:80]
        attempt.result_refs = _result_refs(result)
        attempt.revision += 1
        attempt.updated_at = now
        step.result_refs = attempt.result_refs
        if ok:
            raw_ids = result.get("proposal_ids")
            proposal_ids = (
                [str(value) for value in raw_ids if value is not None]
                if isinstance(raw_ids, list)
                else []
            )
            step.status = "waiting_user" if proposal_ids else "succeeded"
            step.wait_reason = "proposal_pending" if proposal_ids else None
        else:
            denied = attempt.error_code == "ToolPermissionDenied"
            step.status = "blocked" if denied else "failed"
            step.wait_reason = "permission_denied" if denied else None
        step.revision += 1
        step.updated_at = now
        await self._session.flush()
        await self._notify_step(step)

    async def _record_failure(
        self,
        attempt: DirectorBusinessFlowStepAttempt,
        step: DirectorBusinessFlowStep,
        error: FlowActionError,
    ) -> None:
        now = datetime.now(UTC)
        attempt.error_code = error.code[:80]
        attempt.status = "unknown_submission" if error.unknown_submission else "failed"
        attempt.unresolved_external = error.unknown_submission
        attempt.revision += 1
        attempt.updated_at = now
        step.status = "waiting_execution" if error.unknown_submission else "failed"
        step.wait_reason = "unknown_submission" if error.unknown_submission else None
        step.revision += 1
        step.updated_at = now
        await self._session.flush()
        await self._notify_step(step)

    async def _settle_instance(
        self, instance: DirectorBusinessFlowInstance
    ) -> DirectorBusinessFlowInstance:
        if instance.status in INSTANCE_TERMINAL:
            return instance
        steps = await self._steps_of(instance.id)
        required = [step for step in steps if step.required]
        now = datetime.now(UTC)
        if required and all(step.status == "succeeded" for step in required):
            instance.status = "succeeded"
            instance.terminal_reason = "all_required_steps_succeeded"
            instance.wait_reason = None
            instance.finished_at = now
        elif any(step.status in {"failed", "blocked"} for step in steps):
            instance.status = "failed"
            instance.terminal_reason = "step_failed"
            instance.wait_reason = None
            instance.finished_at = now
        elif any(step.status == "waiting_user" for step in steps):
            instance.status = "waiting"
            instance.wait_reason = "user_decision"
        elif any(step.status == "waiting_execution" for step in steps):
            instance.status = "waiting"
            instance.wait_reason = "production_pending"
        elif required and all(step.status in STEP_TERMINAL for step in required):
            instance.status = "succeeded"
            instance.terminal_reason = "required_steps_terminal"
            instance.wait_reason = None
            instance.finished_at = now
        else:
            instance.status = "waiting"
            instance.wait_reason = "flow_progress_pending"
        instance.revision += 1
        instance.updated_at = now
        await self._session.flush()
        await self._notify_instance(instance)
        return instance

    # ----- projections -----------------------------------------------------
    async def _effective_instances(
        self, *, run: DirectorMasterRun, plan: DirectorMasterRunPlan,
    ) -> list[DirectorBusinessFlowInstance]:
        """Plan flows plus instances retained from an earlier plan (same identity)."""
        instances = await self.list_for_run(run.id)
        dispositions = normalize_dispositions(plan.plan_data.get("flow_dispositions")) or {}
        effective: list[DirectorBusinessFlowInstance] = []
        for spec in validate_plan_flows(plan.plan_data.get("flows"), allow_empty=True):
            definition = self._registry.get_versioned(spec.definition_key, spec.definition_version)
            matches = [
                item for item in instances
                if (item.plan_id == plan.id or dispositions.get(str(item.id)) == "retain")
                and item.flow_key == spec.flow_key and item.definition_key == spec.definition_key
                and item.definition_version == spec.definition_version
                and definition is not None and item.contract_hash == definition.contract_hash
                and item.scope_type == spec.scope_type
                and item.scope_entity_id == spec.scope_entity_id
                and item.input_hash == content_hash(spec.input)
            ]
            if len(matches) == 1:
                effective.append(matches[0])
        return effective

    async def progress(self, run_id: UUID) -> dict[str, int]:
        steps = list(
            await self._session.scalars(
                select(DirectorBusinessFlowStep).where(
                    DirectorBusinessFlowStep.project_id == self._project.id,
                    DirectorBusinessFlowStep.supervisor_run_id == run_id,
                )
            )
        )
        required = [step for step in steps if step.required]
        unresolved = int(
            await self._session.scalar(
                select(func.count(DirectorBusinessFlowStepAttempt.id)).where(
                    DirectorBusinessFlowStepAttempt.project_id == self._project.id,
                    DirectorBusinessFlowStepAttempt.supervisor_run_id == run_id,
                    DirectorBusinessFlowStepAttempt.unresolved_external.is_(True),
                )
            )
            or 0
        )
        return {
            "required_steps": len(required),
            "completed_steps": sum(1 for step in required if step.status == "succeeded"),
            "waiting_user": sum(
                1 for step in required if step.status in {"waiting_user", "waiting_execution"}
            ),
            "waiting_execution": sum(
                1 for step in required if step.status == "waiting_execution"
            ),
            "blocked_steps": sum(1 for step in required if step.status == "blocked"),
            "unresolved_external_count": unresolved,
        }

    async def completion(
        self, *, run: DirectorMasterRun, plan: DirectorMasterRunPlan,
    ) -> dict[str, object]:
        """Evaluate registered completion rules over the plan's flow facts."""
        instances = await self._effective_instances(run=run, plan=plan)
        steps = [
            step
            for instance in instances
            for step in await self._steps_of(instance.id)
        ]
        required = [step for step in steps if step.required]
        unresolved = int(
            await self._session.scalar(
                select(func.count(DirectorBusinessFlowStepAttempt.id)).where(
                    DirectorBusinessFlowStepAttempt.project_id == self._project.id,
                    DirectorBusinessFlowStepAttempt.supervisor_run_id == run.id,
                    DirectorBusinessFlowStepAttempt.unresolved_external.is_(True),
                )
            )
            or 0
        )
        specs = validate_plan_flows(plan.plan_data.get("flows"), allow_empty=True)
        complete_scope = bool(instances) and len(instances) == len(specs)
        required_keys = {
            (instance.id, spec.step_key)
            for instance in instances
            for spec in self._registry.require(
                instance.definition_key, instance.definition_version,
            ).steps
            if spec.required
        }
        all_succeeded = (
            complete_scope and bool(required)
            and {(step.instance_id, step.step_key) for step in required} == required_keys
            and all(step.status == "succeeded" for step in required)
        )
        flows_completed = complete_scope and all(
            instance.status == "succeeded" for instance in instances
        )
        checks = [
            {
                "rule_id": "all_required_steps_succeeded",
                "satisfied": all_succeeded,
                "required_steps": len(required),
                "completed_steps": sum(
                    1 for step in required if step.status == "succeeded"
                ),
            },
            {
                "rule_id": "no_unresolved_external",
                "satisfied": unresolved == 0,
                "unresolved_external_count": unresolved,
            },
            {
                "rule_id": "business_flow_completed_v1",
                "satisfied": flows_completed,
                "flows": len(instances),
                "completed_flows": sum(
                    1 for instance in instances if instance.status == "succeeded"
                ),
            },
        ]
        return {
            "satisfied": all(bool(check["satisfied"]) for check in checks),
            "checks": checks,
        }

    # ----- helpers ---------------------------------------------------------
    async def _steps_of(self, instance_id: UUID) -> list[DirectorBusinessFlowStep]:
        return list(
            await self._session.scalars(
                select(DirectorBusinessFlowStep)
                .where(
                    DirectorBusinessFlowStep.instance_id == instance_id,
                    DirectorBusinessFlowStep.project_id == self._project.id,
                )
                .order_by(DirectorBusinessFlowStep.step_key)
            )
        )

    async def _notify_instance(self, instance: DirectorBusinessFlowInstance) -> None:
        await append_master_run_notice(
            self._session,
            project_id=self._project.id,
            actor_id=self._actor.id,
            notice=BusinessFlowChanged(
                run_id=instance.supervisor_run_id,
                instance_id=instance.id,
                revision=instance.revision,
                status=instance.status,
            ),
        )

    async def _notify_step(self, step: DirectorBusinessFlowStep) -> None:
        await append_master_run_notice(
            self._session,
            project_id=self._project.id,
            actor_id=self._actor.id,
            notice=BusinessStepChanged(
                instance_id=step.instance_id,
                step_id=step.id,
                revision=step.revision,
                status=step.status,
            ),
        )


def _result_refs(result: Mapping[str, object]) -> list[object]:
    refs: list[object] = []
    for key in ("proposal_ids", "artifact_ids", "asset_version_ids", "node_run_ids"):
        values = result.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if value is not None:
                refs.append({"kind": key.removesuffix("_ids"), "id": str(value)})
    return refs


def with_step(
    definition: BusinessFlowDefinition, step: FlowStepSpec
) -> BusinessFlowDefinition:
    """Return a copy with one step replaced (test fixtures and versioning)."""
    steps = tuple(step if item.step_key == step.step_key else item for item in definition.steps)
    return replace(definition, steps=steps)


__all__ = [
    "BusinessFlowDefinition",
    "BusinessFlowDefinitionRegistry",
    "BusinessFlowService",
    "COMPLETION_RULE_IDS",
    "DEFAULT_DEFINITIONS",
    "FlowActionError",
    "FlowActionExecutor",
    "FlowStepSpec",
    "PlanFlowSpec",
    "SHOT_PROMPT_REVIEW_V1",
    "content_hash",
    "definition_registry",
    "validate_plan_flows",
    "with_step",
]
