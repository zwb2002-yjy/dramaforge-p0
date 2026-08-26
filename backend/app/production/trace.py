"""P4-10 Execution trace (03 §40).

Builds a structured, secret-free trace of one NodeRun from:
- NodeRun.input_snapshot["workbench_plan"] (Director Intent, Prompt, Resolved
  Asset Versions, Model Binding, Capability, Approximation),
- ProviderOperation (actual provider/model, redacted request summary),
- Artifact produced by the run.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.models import Artifact, NodeRun, ProviderOperation
from app.shared.errors import NotFoundError


class ExecutionTraceRead(BaseModel):
    """Secret-free execution trace response."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    node_key: str | None = None
    status: str
    director_intent: dict[str, JsonValue] = Field(default_factory=dict)
    prompt: str | None = None
    resolved_asset_versions: list[dict[str, JsonValue]] = Field(default_factory=list)
    model_binding: dict[str, JsonValue] = Field(default_factory=dict)
    capability: str | None = None
    approximations: list[str] = Field(default_factory=list)
    actual_provider: str | None = None
    actual_model: str | None = None
    effective_request_redacted: dict[str, JsonValue] = Field(default_factory=dict)
    artifact: dict[str, JsonValue] | None = None


def _plan_of(run: NodeRun) -> dict[str, Any]:
    snapshot = run.input_snapshot or {}
    raw = snapshot.get("workbench_plan")
    return raw if isinstance(raw, dict) else {}


async def build_execution_trace(
    session: AsyncSession,
    *,
    project_id: UUID,
    run_id: UUID,
) -> ExecutionTraceRead:
    """Assemble the execution trace for one NodeRun (03 §40)."""
    run = await session.scalar(
        select(NodeRun).where(NodeRun.id == run_id, NodeRun.project_id == project_id)
    )
    if run is None:
        raise NotFoundError("node run not found")

    plan = _plan_of(run)
    resolved_model = plan.get("resolved_model")
    if not isinstance(resolved_model, dict):
        resolved_model = {}

    # Actual provider/model from the latest ProviderOperation of this run.
    operation = (
        await session.execute(
            select(ProviderOperation)
            .where(ProviderOperation.node_run_id == run.id)
            .order_by(ProviderOperation.attempt_no.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    artifact = (
        await session.execute(
            select(Artifact).where(Artifact.produced_by_run_id == run.id).limit(1)
        )
    ).scalars().first()

    references = plan.get("planned_references")
    resolved_versions: list[dict[str, JsonValue]] = []
    if isinstance(references, list):
        for reference in references:
            if not isinstance(reference, dict):
                continue
            item: dict[str, JsonValue] = {
                "purpose": reference.get("purpose") or "",
                "role": reference.get("role") or "",
                "delivery": reference.get("delivery") or "",
            }
            if reference.get("artifact_id") is not None:
                item["artifact_id"] = str(reference["artifact_id"])
            if reference.get("asset_version_id") is not None:
                item["asset_version_id"] = str(reference["asset_version_id"])
            if reference.get("fingerprint") is not None:
                item["fingerprint"] = reference["fingerprint"]
            resolved_versions.append(item)

    return ExecutionTraceRead(
        run_id=run.id,
        node_key=(
            str(run.input_snapshot["node_key"])
            if isinstance(run.input_snapshot, dict)
            and isinstance(run.input_snapshot.get("node_key"), str)
            else None
        ),
        status=run.status,
        director_intent=plan.get("semantic_intent") or {},
        prompt=plan.get("prompt"),
        resolved_asset_versions=resolved_versions,
        model_binding={
            "resolved_model_id": resolved_model.get("resolved_model_id") or "",
            "provider_model_binding_id": str(resolved_model["provider_model_binding_id"])
            if resolved_model.get("provider_model_binding_id")
            else "",
            "manifest_hash": resolved_model.get("manifest_hash") or "",
            "invoke_model_value": resolved_model.get("invoke_model_value") or "",
        },
        capability=plan.get("capability"),
        approximations=list(plan.get("accepted_approximations") or []),
        actual_provider=operation.actual_provider if operation else None,
        actual_model=operation.actual_model if operation else None,
        effective_request_redacted=(
            cast(dict[str, JsonValue], operation.request_summary) if operation else {}
        ),
        artifact=(
            {
                "artifact_id": str(artifact.id),
                "artifact_type": artifact.artifact_type,
                "storage_state": artifact.storage_state,
                "mime_type": artifact.mime_type,
                "content_hash": artifact.content_hash,
            }
            if artifact is not None
            else None
        ),
    )
