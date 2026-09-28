"""Single creation service for isolated ExperimentBranch drafts.

Creation never queues production or adopts candidates. Those operations remain
behind the existing start and decision endpoints. Legacy experiment tables are
retained only for historical data and have no runtime writer.
"""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Shot
from app.execution.branches import experiment_id as run_experiment_id
from app.execution.models import Artifact, GraphNode, NodeRun
from app.production.models import ExperimentBranch
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

_DONE = frozenset({"completed", "cached", "completed_after_cancel"})


class ExperimentCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=160)
    branch_type: str = Field(default="model_experiment", max_length=32)
    source_shot_id: UUID | None = None
    source_artifact_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, object] = Field(default_factory=dict)
    selected_model: str | None = None


async def latest_formal_artifact_ids(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    node_key: str,
) -> list[str]:
    rows = list(
        (
            await session.execute(
                select(NodeRun, GraphNode)
                .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
                .where(
                    NodeRun.project_id == project_id,
                    GraphNode.node_key == node_key,
                    NodeRun.status.in_(_DONE),
                    NodeRun.result_artifact_id.is_not(None),
                )
            )
        )
        .tuples()
        .all()
    )
    matching = [
        run
        for run, _node in rows
        if str((run.input_snapshot or {}).get("shot_id") or "") == str(shot_id)
        and run_experiment_id(run.input_snapshot) is None
    ]
    latest = max(
        matching,
        key=lambda item: (item.attempt_no, item.created_at, str(item.id)),
        default=None,
    )
    return [str(latest.result_artifact_id)] if latest and latest.result_artifact_id else []


async def create_experiment_branch(
    session: AsyncSession,
    *,
    project_id: UUID,
    actor_id: UUID,
    body: ExperimentCreateBody,
) -> ExperimentBranch:
    if any(key.startswith("_creation_") for key in body.parameters):
        raise ValidationAppError("reserved experiment parameter")
    prompt_override = body.parameters.get("prompt_override")
    if prompt_override is not None and (
        not isinstance(prompt_override, str)
        or not prompt_override.strip()
        or len(prompt_override) > 8000
    ):
        raise ValidationAppError("experiment prompt_override must be 1 to 8000 characters")
    request_data = body.model_dump(mode="json")
    request_data["parameters"] = {
        **body.parameters,
        "target_node_key": str(body.parameters.get("target_node_key") or "video"),
    }
    fingerprint = hashlib.sha256(json.dumps(request_data, sort_keys=True).encode()).hexdigest()
    existing = (
        await session.execute(
            select(ExperimentBranch).where(
                ExperimentBranch.project_id == project_id,
                ExperimentBranch.idempotency_key == body.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        parameters = {
            **body.parameters,
            "target_node_key": str(body.parameters.get("target_node_key") or "video"),
        }
        frozen_fingerprint = existing.parameters.get("_creation_fingerprint")
        if frozen_fingerprint is not None:
            if frozen_fingerprint != fingerprint:
                raise ConflictError("experiment idempotency key reused with different inputs")
            return existing
        if (
            existing.source_shot_id != body.source_shot_id
            or existing.name != body.name
            or existing.branch_type != body.branch_type
            or existing.selected_model != body.selected_model
            or any(existing.parameters.get(key) != value for key, value in parameters.items())
            or (
                body.source_artifact_ids
                and existing.source_artifact_ids != body.source_artifact_ids
            )
        ):
            raise ConflictError("experiment idempotency key reused with different inputs")
        return existing
    if body.source_shot_id is not None:
        shot = await session.get(Shot, body.source_shot_id)
        if shot is None or shot.project_id != project_id:
            raise NotFoundError("source shot not found")
    target_node_key = str(body.parameters.get("target_node_key") or "video")
    if target_node_key not in {"keyframe", "video"}:
        raise ValidationAppError("experiment target must be keyframe or video")
    source_artifact_ids = list(body.source_artifact_ids)
    if not source_artifact_ids and body.source_shot_id is not None:
        source_artifact_ids = await latest_formal_artifact_ids(
            session,
            project_id=project_id,
            shot_id=body.source_shot_id,
            node_key=target_node_key,
        )
    for value in source_artifact_ids:
        try:
            artifact_id = UUID(value)
        except ValueError as exc:
            raise ValidationAppError("invalid source artifact id") from exc
        artifact = await session.get(Artifact, artifact_id)
        if artifact is None or artifact.project_id != project_id:
            raise NotFoundError("source artifact not found")
    row = ExperimentBranch(
        project_id=project_id,
        source_shot_id=body.source_shot_id,
        created_by=actor_id,
        idempotency_key=body.idempotency_key,
        name=body.name,
        branch_type=body.branch_type,
        source_artifact_ids=source_artifact_ids,
        parameters={
            **dict(body.parameters),
            "target_node_key": target_node_key,
            "_creation_fingerprint": fingerprint,
        },
        selected_model=body.selected_model,
    )
    session.add(row)
    await session.flush()
    return row
