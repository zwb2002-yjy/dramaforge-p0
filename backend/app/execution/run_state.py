"""Shared execution outcomes and durable terminal state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.models import Artifact, NodeRun
from app.shared.db import set_node_run_rls_context
from app.shared.errors import (
    ValidationAppError,
)

UNIFIED_PATH_VERSION = "unified-v1"


@dataclass(frozen=True)
class ExecuteNodeResult:
    node_run_id: UUID
    artifact_id: UUID
    object_key: str
    content_hash: str
    byte_size: int
    identity_status: str | None
    provider_operation_id: UUID | None
    node_type: str


async def _commit_terminal_failure(
    session: AsyncSession,
    *,
    run: NodeRun,
    error_code: str,
    error_summary: str,
    status: str = "failed",
) -> None:
    """Commit a terminal state before the Worker exception boundary rolls back."""
    from datetime import UTC, datetime

    run.status = status
    run.error_code = error_code
    run.error_summary = error_summary[:500]
    run.finished_at = datetime.now(UTC)
    run.output_summary = {
        "status": "failed",
        "error_code": error_code,
    }
    await session.flush()
    await session.commit()
    await set_node_run_rls_context(session, node_run_id=run.id)


async def _completed_result(
    session: AsyncSession,
    *,
    run: NodeRun,
    node_type: str,
) -> ExecuteNodeResult:
    art = await session.get(Artifact, run.result_artifact_id) if run.result_artifact_id else None
    if art is None:
        raise ValidationAppError("completed run missing artifact")
    output = run.output_summary or {}
    return ExecuteNodeResult(
        node_run_id=run.id,
        artifact_id=art.id,
        object_key=art.object_key,
        content_hash=art.content_hash,
        byte_size=art.byte_size,
        identity_status=(
            str(output.get("identity_review_status"))
            if output.get("identity_review_status") is not None
            else None
        ),
        provider_operation_id=None,
        node_type=node_type,
    )
