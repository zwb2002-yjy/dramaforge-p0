"""Owner-only maintenance API: list and replay persisted failures.

This is deliberately not part of the creative workbench. Replays are
per-item, require the exact failure identity the caller saw, and are audited.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CsrfDep, CurrentUser, SessionDep
from app.maintenance import recovery_service

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


class RecoveryItemRead(BaseModel):
    """One replayable failure as shown in Settings -> Advanced recovery."""

    kind: Literal["director_wakeup", "outbox_dead_letter"]
    id: UUID
    project_id: UUID | None
    label: str
    detail: str
    attempts: int
    failed_at: datetime


class RecoveryListRead(BaseModel):
    items: list[RecoveryItemRead]


class DirectorWakeupReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    expected_dead_letter_at: datetime


class OutboxDeadLetterReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_dead_lettered_at: datetime


class RecoveryReplayRead(BaseModel):
    """Result of one replay; ``applied`` is False when nothing was left to do."""

    kind: Literal["director_wakeup", "outbox_dead_letter"]
    id: UUID
    applied: bool
    replayed_at: datetime = Field(description="Server time of the accepted replay")


@router.get("/recovery", response_model=RecoveryListRead)
async def list_recovery(
    session: SessionDep,
    user: CurrentUser,
) -> RecoveryListRead:
    """Failures the current Owner can still replay (empty for everyone else)."""
    items = await recovery_service.list_recovery_items(session, actor=user)
    return RecoveryListRead(
        items=[
            RecoveryItemRead(
                kind=item.kind,
                id=item.id,
                project_id=item.project_id,
                label=item.label,
                detail=item.detail,
                attempts=item.attempts,
                failed_at=item.failed_at,
            )
            for item in items
        ]
    )


@router.post("/director-wakeups/{inbox_id}/replay", response_model=RecoveryReplayRead)
async def replay_director_wakeup(
    inbox_id: UUID,
    body: DirectorWakeupReplayRequest,
    session: SessionDep,
    user: CurrentUser,
    _csrf: CsrfDep,
) -> RecoveryReplayRead:
    """Replay one dead-lettered Director wakeup."""
    applied = await recovery_service.replay_director_wakeup(
        session,
        actor=user,
        project_id=body.project_id,
        inbox_id=inbox_id,
        expected_dead_letter_at=body.expected_dead_letter_at,
    )
    await session.commit()
    return RecoveryReplayRead(
        kind="director_wakeup",
        id=inbox_id,
        applied=applied,
        replayed_at=datetime.now(UTC),
    )


@router.post(
    "/outbox/dead-letters/{dead_letter_id}/replay",
    response_model=RecoveryReplayRead,
)
async def replay_outbox_dead_letter(
    dead_letter_id: UUID,
    body: OutboxDeadLetterReplayRequest,
    session: SessionDep,
    user: CurrentUser,
    _csrf: CsrfDep,
) -> RecoveryReplayRead:
    """Replay one dead-lettered Outbox event exactly once."""
    _event, applied = await recovery_service.replay_outbox_dead_letter(
        session,
        actor=user,
        dead_letter_id=dead_letter_id,
        expected_dead_lettered_at=body.expected_dead_lettered_at,
    )
    await session.commit()
    return RecoveryReplayRead(
        kind="outbox_dead_letter",
        id=dead_letter_id,
        applied=applied,
        replayed_at=datetime.now(UTC),
    )
