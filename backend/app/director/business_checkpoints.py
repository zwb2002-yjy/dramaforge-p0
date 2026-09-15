"""Business-owned Director checkpoints; no Provider or production dispatch."""

from __future__ import annotations

from contextlib import suppress
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, ProjectCreativeProfile, User
from app.contracts.production_facts import ExecutionTrackingFact
from app.director.next_action import DirectorNextActionService
from app.director.turn_models import DirectorTurn
from app.director.turn_service import ACTIVE_TURN_STATUSES, DirectorTurnService
from app.production.application.facts import ProductionFacts
from app.shared.errors import ConflictError, ValidationAppError


class ExecutionIdentity(Protocol):
    @property
    def id(self) -> UUID: ...


class DirectorBusinessCheckpoints:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._turns = DirectorTurnService(session)

    async def track_execution(
        self, *, project: Project, actor: User, run: ExecutionIdentity,
    ) -> DirectorTurn | None:
        """Legacy adapter; callers migrate to the independent event worker."""
        fact = await ProductionFacts(self._session).tracking(project_id=project.id, run_id=run.id)
        return await self.track_fact(project=project, actor=actor, run=fact)

    async def track_fact(
        self, *, project: Project, actor: User, run: ExecutionTrackingFact,
    ) -> DirectorTurn | None:
        profile = await self._session.scalar(
            select(ProjectCreativeProfile)
            .where(ProjectCreativeProfile.project_id == project.id)
            .with_for_update().execution_options(populate_existing=True)
        )
        if profile is None or profile.director_autonomy not in {"AUTO", "ASSIST"}:
            return None
        if run.project_id != project.id:
            raise ValidationAppError("Execution checkpoint is outside the project")
        shot_id = run.shot_id
        turn, created = await self._turns.create_or_get(
            project=project, actor=actor, scope_type="shot", scope_entity_id=shot_id,
            request_key=f"workbench:{run.id}",
            context_snapshot={"node_run_id": str(run.id), "input_hash": run.input_hash},
            input_versions={"shot": run.shot_version,
                            "creative_profile": profile.version},
            intent_snapshot={"goal": "review_production", "stage": run.stage},
            max_steps=4,
        )
        if not created:
            return turn
        await self._turns.claim(
            project_id=project.id, turn_id=turn.id, expected_revision=turn.revision,
        )
        resolution = run.model_resolution
        return await self._turns.compare_and_set(
            turn=turn, expected_statuses=("thinking",), target_status="awaiting_execution",
            updates={
                "wait_reason": "execution_in_progress",
                "request_summary": {"task": "workbench_followup", "max_steps": 4,
                                    "stage": run.stage},
                "model_resolution": dict(resolution) if isinstance(resolution, dict) else {},
                "dispatched_command_key": run.command_key,
                "node_run_ids": [str(run.id)],
            },
        )

    async def reconcile_business_fact(
        self, *, project: Project, shot_id: UUID | None = None, proposal_id: UUID | None = None,
    ) -> None:
        """A valid user mutation must not roll back merely because a turn expired."""
        await self._session.flush()
        statement = select(DirectorTurn.id).where(
            DirectorTurn.project_id == project.id,
            DirectorTurn.status.in_(("awaiting_execution", "awaiting_user")),
            DirectorTurn.runtime_execution_id.is_(None),
        )
        if shot_id is not None:
            statement = statement.where(
                DirectorTurn.scope_type == "shot", DirectorTurn.scope_entity_id == shot_id,
                DirectorTurn.node_run_ids != [],
            )
        elif proposal_id is not None:
            statement = statement.where(DirectorTurn.proposal_id == proposal_id)
        else:
            raise ValueError("A business checkpoint must name its canonical scope")
        result = await self._session.execute(statement.order_by(DirectorTurn.id))
        turn_ids = list(result.scalars())
        for turn_id in turn_ids:
            try:
                await DirectorNextActionService(self._session).reconcile(
                    project=project, turn_id=turn_id,
                )
            except ConflictError as exc:
                if exc.details.get("code") not in {
                    "DIRECTOR_TURN_LIMIT_REACHED", "DIRECTOR_TURN_REVISION_CONFLICT",
                }:
                    raise
            except ValidationAppError as exc:
                turn = await self._turns.get(project_id=project.id, turn_id=turn_id)
                if turn.status in ACTIVE_TURN_STATUSES:
                    # A concurrent user stop/mode change already owns the turn.
                    with suppress(ConflictError):
                        await self._turns.compare_and_set(
                            turn=turn, expected_statuses=tuple(ACTIVE_TURN_STATUSES),
                            target_status="failed", updates={
                                "wait_reason": "checkpoint_invalid",
                                "last_error": str(exc.details.get("code", "INVALID_CHECKPOINT")),
                            },
                        )
