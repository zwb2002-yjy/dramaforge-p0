"""Prevent legacy paid commands from bypassing the Director fact model."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import UserProjectPreference
from app.director.models import DirectorWorkflowRun
from app.shared.enums import ExperienceMode
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


async def require_recovery_only_project(
    session: AsyncSession,
    *,
    user_id: UUID,
    project_id: UUID,
    action: str,
) -> None:
    """Refuse the legacy materialization path for a canonical Professional project.

    Workflow Expansion (WF1) makes the legacy ``confirm_plan`` /
    ``confirm_plan_and_materialize`` path ``recovery-only``: it may complete an
    already-existing historical ``QUICK`` project, but a new Professional
    (``WORKBENCH``) project must never enter legacy materialization.

    This is the architectural gate (G-WF-01): a new professional project
    reaches ``legacy execution call count = 0``.  A ``WORKBENCH`` preference
    marks the canonical path unconditionally.
    """
    pref = await session.scalar(
        select(UserProjectPreference).where(
            UserProjectPreference.user_id == user_id,
            UserProjectPreference.project_id == project_id,
        )
    )
    if pref is None:
        # No user preference recorded => project was not created through a
        # controlled professional workflow; allow historical recovery.
        return
    try:
        mode = ExperienceMode(str(pref.experience_mode))
    except ValueError:
        # Unknown persisted mode: fail closed rather than guess.
        raise ValidationAppError(
            "Unknown experience mode; cannot determine recovery eligibility.",
            details={"code": "UNKNOWN_EXPERIENCE_MODE", "action": action},
        ) from None
    if mode.is_professional:
        raise ValidationAppError(
            "Legacy plan materialization is recovery-only; this project uses the "
            "canonical Professional path. Use the Professional workbench.",
            details={
                "code": "PROFESSIONAL_PATH_ONLY",
                "action": action,
                "experience_mode": mode.value,
            },
        )
