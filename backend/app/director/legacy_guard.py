"""Prevent legacy paid commands from bypassing the Director fact model."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.director.models import DirectorWorkflowRun
from app.shared.errors import ValidationAppError


async def require_legacy_execution_allowed(
    session: AsyncSession,
    *,
    project_id: UUID,
    action: str,
) -> None:
    """Fail before a legacy command can create work, outbox rows, or Provider calls.

    The presence of a Director workflow permanently selects the controlled fact
    model for that project.  Completed/cancelled workflows remain auditable and
    must not silently fall back to the old media path.
    """
    workflow_id = await session.scalar(
        select(DirectorWorkflowRun.id).where(
            DirectorWorkflowRun.project_id == project_id
        )
    )
    if workflow_id is None:
        return
    raise ValidationAppError(
        "This project is controlled by the AI Director; use an authorized "
        "Director production or repair command.",
        details={
            "code": "DIRECTOR_COMMAND_REQUIRED",
            "action": action,
            "workflow_run_id": str(workflow_id),
        },
    )
