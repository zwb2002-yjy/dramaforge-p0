"""P4-05 WorkbenchExecutionService (07 §16 / 03 §35).

Orchestrates one Professional shot execution without any legacy gate:

- Build Plan  (ExecutionModelResolver + P4-02 reference compiler + P4-01 plan)
- Freeze inputs (deterministic plan fingerprint)
- Resolve graph (GraphService, scope_type=shot)
- Create NodeRun (status=queued, worker picks it up)
- Persist snapshot (plan + identity, never secrets)
- Dispatch worker (queued NodeRun -> Worker)

Forbidden here: direct Provider HTTP, ``require_legacy_execution_allowed``,
BudgetAuthorization, automatic model fallback, Agent approval.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.assets.models import Shot
from app.config import get_settings
from app.execution.models import NodeRun
from app.execution.shot_pipeline import (
    SHOT_PIPELINE_TEMPLATE_KEY,
    shot_pipeline_definition,
)
from app.production.execution_plan import (
    WorkbenchExecutionPlan,
)
from app.production.formal_selection import require_formal_keyframe
from app.production.models import ProductionGraph
from app.production.reference_intents import (
    ShotReferenceIntent,
    compile_references,
)
from app.production.service import GraphService
from app.providers.capabilities import Capability
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.manifest import ModelCapabilityManifest, to_v3_model_manifest
from app.providers.model_profiles.slots import ModelSlot
from app.providers.model_resolution import ExecutionModelResolver
from app.providers.models import ProviderConnection, ProviderConnectionRevision
from app.shared.enums import GraphStatus
from app.shared.errors import ValidationAppError

PlanStage = Literal["image_keyframe", "video"]

_STAGE_CONTRACT: Final[dict[PlanStage, tuple[ModelSlot, Capability, str, str]]] = {
    "image_keyframe": (
        ModelSlot.VISUAL_KEYFRAME,
        Capability.IMAGE_GENERATE,
        "keyframe",
        "keyframe",
    ),
    "video": (
        ModelSlot.VIDEO_SHOT,
        Capability.VIDEO_IMAGE_TO_VIDEO,
        "video",
        "video",
    ),
}


class WorkbenchExecutionError(ValidationAppError):
    """Raised when a workbench plan cannot be built or dispatched."""


class WorkbenchExecutionInput(BaseModel):
    """Inputs for one shot execution (image keyframe or video)."""

    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    shot_id: UUID
    shot_experiment_id: UUID | None = None
    stage: PlanStage
    prompt: str = Field(min_length=1)
    semantic_intent: dict[str, JsonValue] = Field(default_factory=dict)
    mode_id: str = Field(min_length=1, max_length=120)
    requested_model_id: str | None = None
    requested_binding_id: UUID | None = None
    accept_approximations: bool = False
    references: list[ShotReferenceIntent] = Field(default_factory=list)
    expected_shot_version: int | None = None


def _node_run_input_hash(snapshot: dict[str, object]) -> str:
    canonical = json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class WorkbenchExecutionService:
    """Professional workbench execution orchestration (P4-05)."""

    def __init__(self, session: AsyncSession, *, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    async def build_plan(
        self,
        *,
        project: Project,
        execution_input: WorkbenchExecutionInput,
    ) -> WorkbenchExecutionPlan:
        """Resolve model, compile references and freeze a WorkbenchExecutionPlan.

        Fails closed (raises) when the model is unavailable or when capability
        gaps remain (unsupported references are never silently dropped).
        """
        slot, capability, purpose, _node_key = _STAGE_CONTRACT[execution_input.stage]
        resolution = await ExecutionModelResolver(self._session).resolve(
            project=project,
            slot=slot,
            capability=capability,
            purpose=purpose,
            mode_id=execution_input.mode_id,
            requested_model_id=execution_input.requested_model_id,
            requested_binding_id=execution_input.requested_binding_id,
        )
        if resolution.status != "RESOLVED" or resolution.catalog_entry_id is None:
            raise WorkbenchExecutionError(
                "selected execution model is unavailable: "
                f"{resolution.reason or resolution.status}"
            )

        # Connection / credential revision identity for the plan (07 §16).
        connection_revision_id: UUID | None = None
        credential_revision_id: UUID | None = None
        if resolution.provider_connection_id is not None:
            connection = await self._session.get(
                ProviderConnection, resolution.provider_connection_id
            )
            if connection is None or connection.workspace_id != project.workspace_id:
                raise WorkbenchExecutionError(
                    "resolved provider connection is unavailable"
                )
            current_revision = await self._session.scalar(
                select(ProviderConnectionRevision)
                .where(
                    ProviderConnectionRevision.connection_id
                    == resolution.provider_connection_id
                )
                .order_by(ProviderConnectionRevision.revision_no.desc())
                .limit(1)
            )
            if current_revision is not None:
                connection_revision_id = current_revision.id
                credential_revision_id = current_revision.credential_revision_id
        if connection_revision_id is None or credential_revision_id is None:
            raise WorkbenchExecutionError(
                "resolved provider connection revision is unavailable"
            )
        # Carry the immutable revision identity with the typed model
        # resolution.  The worker must be able to reconstruct the exact
        # Provider runtime without resolving the mutable connection again.
        resolution = resolution.model_copy(
            update={
                "provider_connection_revision_id": connection_revision_id,
                "credential_revision_id": credential_revision_id,
            }
        )

        entry = await self._session.get(ModelCatalogEntry, resolution.catalog_entry_id)
        if entry is None:
            raise WorkbenchExecutionError("resolved catalog entry not found")
        capability_manifest = ModelCapabilityManifest.model_validate(
            entry.capability_manifest_json
        )
        v3_manifest = to_v3_model_manifest(
            capability_manifest,
            transport_profile_id="workbench",
        )

        references = list(execution_input.references)
        if execution_input.stage == "video":
            # Video execution requires the shot formal keyframe; the latest
            # image must never be used as a fallback (03 §38/§39).
            shot = await self._session.get(Shot, execution_input.shot_id)
            if shot is None or shot.project_id != project.id:
                raise WorkbenchExecutionError("shot not found")
            try:
                formal = await require_formal_keyframe(
                    self._session,
                    project_id=project.id,
                    shot_id=execution_input.shot_id,
                )
            except ValidationAppError as exc:
                raise WorkbenchExecutionError(str(exc)) from exc
            if not any(ref.artifact_id == formal.id for ref in references):
                references.insert(
                    0,
                    ShotReferenceIntent(
                        purpose="first_frame",
                        artifact_id=formal.id,
                        mime_type=formal.mime_type,
                    ),
                )

        compiled = compile_references(
            manifest=v3_manifest,
            capability=capability,
            references=references,
            mode_id=execution_input.mode_id,
            accept_approximations=execution_input.accept_approximations,
        )

        plan = WorkbenchExecutionPlan(
            project_id=project.id,
            shot_id=execution_input.shot_id,
            shot_experiment_id=execution_input.shot_experiment_id,
            stage=execution_input.stage,
            prompt=execution_input.prompt,
            semantic_intent=execution_input.semantic_intent,
            mode_id=execution_input.mode_id,
            resolved_model=resolution,
            capability=capability,
            planned_references=compiled.planned_references,
            capability_gaps=compiled.capability_gaps,
            semantic_request_preview={
                "intent": execution_input.semantic_intent,
                "references": len(compiled.planned_references),
            },
            connection_revision_id=connection_revision_id,
            credential_revision_id=credential_revision_id,
            accepted_approximations=compiled.accepted_approximations,
            expected_shot_version=execution_input.expected_shot_version,
        ).freeze()

        # Fail closed on any remaining capability gap (fatal gaps always remain;
        # warning gaps disappear only when the caller accepted approximations).
        if plan.capability_gaps:
            reasons = "; ".join(gap.reason for gap in plan.capability_gaps)
            raise WorkbenchExecutionError(f"workbench plan has capability gaps: {reasons}")
        return plan

    async def create_and_dispatch(
        self,
        *,
        project: Project,
        execution_input: WorkbenchExecutionInput,
        idempotency_key_override: str | None = None,
    ) -> NodeRun:
        """Resolve the shot graph, create a queued NodeRun and persist the
        frozen plan snapshot for the worker.

        The NodeRun ``status="queued"`` is the dispatch: the worker claims and
        executes it. No direct Provider HTTP, no legacy budget / agent gate.
        """
        plan = await self.build_plan(project=project, execution_input=execution_input)
        _slot, _capability, _purpose, node_key = _STAGE_CONTRACT[execution_input.stage]

        graphs = GraphService(self._session)
        # One graph per shot scope (P4-06): reuse the existing shot graph when
        # present, otherwise create it.
        graph = await self._session.scalar(
            select(ProductionGraph).where(
                ProductionGraph.project_id == project.id,
                ProductionGraph.scope_type == "shot",
                ProductionGraph.scope_entity_id == execution_input.shot_id,
            )
        )
        if graph is None:
            graph = await graphs.create_graph(
                project_id=project.id,
                scope_type="shot",
                scope_entity_id=execution_input.shot_id,
                template_key=SHOT_PIPELINE_TEMPLATE_KEY,
                created_by=self._user_id,
                definition=shot_pipeline_definition(
                    shot_id=str(execution_input.shot_id),
                    shot={"prompt": execution_input.prompt},
                    workbench_plan=plan.model_dump(mode="json"),
                ),
            )
        assert graph.current_version_id is not None
        materialized = await graphs.materialize_definition(version_id=graph.current_version_id)
        version = materialized.version
        if version.status == GraphStatus.DRAFT.value:
            version = await graphs.publish(
                version_id=version.id,
                published_by=self._user_id,
            )
        node = materialized.nodes[node_key]
        provider_connection_id = plan.resolved_model.provider_connection_id
        if provider_connection_id is None:
            raise WorkbenchExecutionError(
                "frozen execution model has no provider connection"
            )
        provider_connection = await self._session.get(
            ProviderConnection, provider_connection_id
        )
        if provider_connection is None or provider_connection.workspace_id != project.workspace_id:
            raise WorkbenchExecutionError(
                "frozen provider connection is unavailable"
            )

        snapshot: dict[str, object] = {
            "workbench_plan": plan.model_dump(mode="json"),
            "plan_fingerprint": plan.plan_fingerprint,
            "stage": plan.stage,
            "mode_id": plan.mode_id,
            "prompt": plan.prompt,
            "project_id": str(project.id),
            "shot_id": str(execution_input.shot_id),
            "node_key": node_key,
            "source_commit": get_settings().source_commit,
            # Professional Workbench media NodeRuns always enter the unified
            # Provider path.  These compatibility keys make the frozen
            # resolution explicit at the worker boundary; legacy NodeRuns do
            # not carry this marker and retain their old adapter path.
            "professional_unified": True,
            "execution_path": "unified-v1",
            "model_binding_id": str(plan.resolved_model.provider_model_binding_id),
            "capability_manifest_hash": plan.resolved_model.manifest_hash,
            "connection_revision_id": str(plan.connection_revision_id),
            "credential_revision_id": str(plan.credential_revision_id),
            "execution_model_resolution": plan.resolved_model.model_dump(mode="json"),
            "selection_plan": {
                "purpose": "keyframe" if plan.stage == "image_keyframe" else "video",
                "mode": plan.mode_id,
                "mode_id": plan.mode_id,
                "model_binding_id": str(plan.resolved_model.provider_model_binding_id),
                "provider_type": provider_connection.provider_type,
                "protocol_profile": provider_connection.protocol_profile,
                "catalog_entry_id": str(plan.resolved_model.catalog_entry_id),
                "model_id": plan.resolved_model.resolved_model_id.rsplit("/", 1)[-1]
                if plan.resolved_model.resolved_model_id
                else None,
                "invoke_model_value": plan.resolved_model.invoke_model_value,
                "connection_id": str(plan.resolved_model.provider_connection_id),
                "manifest_hash": plan.resolved_model.manifest_hash,
                "execution_model_resolution": plan.resolved_model.model_dump(mode="json"),
                "evidence": {"professional_unified": True},
            },
            "plan": {"prompt": plan.prompt},
        }
        if plan.stage == "video":
            # The current Workbench API intentionally exposes no separate
            # duration control.  The verified video manifests use the
            # canonical five-second product intent, which is also the safe
            # default used by the unified compiler.
            snapshot["duration_seconds"] = 5
            snapshot["aspect_ratio"] = project.aspect_ratio
        input_hash = _node_run_input_hash(snapshot)
        node_run = NodeRun(
            project_id=project.id,
            graph_version_id=version.id,
            graph_node_id=node.id,
            idempotency_key=(
                f"workbench:{plan.stage}:{idempotency_key_override}"
                if idempotency_key_override
                else f"workbench:{plan.stage}:{plan.plan_fingerprint}"
            ),
            input_hash=input_hash,
            status="queued",
            input_snapshot=snapshot,
            created_by=self._user_id,
        )
        self._session.add(node_run)
        await self._session.flush()
        return node_run

    async def get_recent_plan(
        self,
        *,
        project_id: UUID,
        shot_id: UUID,
        stage: PlanStage,
        limit: int = 20,
    ) -> list[WorkbenchExecutionPlan]:
        """Read back frozen plan snapshots (preview / trace support)."""
        rows = (
            await self._session.execute(
                select(NodeRun)
                .where(
                    NodeRun.project_id == project_id,
                    NodeRun.input_snapshot["shot_id"].as_string() == str(shot_id),
                )
                .order_by(NodeRun.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        plans: list[WorkbenchExecutionPlan] = []
        for run in rows:
            raw = (run.input_snapshot or {}).get("workbench_plan")
            if not isinstance(raw, dict):
                continue
            try:
                plans.append(WorkbenchExecutionPlan.model_validate(raw))
            except Exception:  # noqa: BLE001 - tolerate malformed historical rows
                continue
        return plans
