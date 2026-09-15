"""Explicit one-shot production delegation into the Director runtime."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.config import Settings
from app.contracts.production_commands import ExecutionBody
from app.director.assistant_models import DirectorThread
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.runtime.models import DirectorRuntimeWakeup
from app.director.runtime.start import DirectorRuntimeStartService
from app.director.turn_models import DirectorTurn
from app.production.application.authorization import ProductionAuthorizations
from app.production.application.commands import execution_input
from app.production.workbench_execution import WorkbenchExecutionService
from app.shared.errors import ConflictError, ValidationAppError


class DirectorRuntimeDelegationService:
    """Persist one exact user grant and schedule its bounded coordinator Turn."""

    def __init__(self, session: AsyncSession, *, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def accept(
        self,
        *,
        project: Project,
        actor: User,
        shot_id: UUID,
        decision_id: UUID,
        execution: ExecutionBody,
        authorization_expires_at: datetime,
        max_steps: int,
    ) -> tuple[DirectorTurn, DirectorRuntimeWakeup]:
        if self._settings.director_runtime_engine != "langgraph":
            raise ConflictError(
                "The durable Director runtime is not enabled for new turns",
                details={"code": "DIRECTOR_RUNTIME_NOT_ENABLED", "manual_ok": True},
            )
        if authorization_expires_at.tzinfo is None:
            raise ValidationAppError("Director authorization expiry must include a timezone")
        normalized_expiry = authorization_expires_at.astimezone(UTC)
        now = datetime.now(UTC)
        if normalized_expiry <= now or normalized_expiry > now + timedelta(hours=1):
            raise ValidationAppError(
                "Director authorization must expire within one hour",
                details={"code": "DIRECTOR_AUTHORIZATION_EXPIRY_INVALID"},
            )

        authorization_id = await ProductionAuthorizations(
            self._session,
        ).approve_user_action(
            actor=actor,
            project_id=project.id,
            shot_id=shot_id,
            decision_id=decision_id,
            body=execution,
            expires_at=normalized_expiry,
        )
        # approve_user_action now holds the same production acceptance scope
        # lock used by submit; re-resolve the plan under that lock so the grant
        # cannot be persisted for a version that changed after browser preview.
        workbench = WorkbenchExecutionService(self._session, user_id=actor.id)
        plan = await workbench.build_plan(
            project=project,
            execution_input=execution_input(project.id, shot_id, execution),
        )
        if plan.plan_fingerprint != execution.plan_fingerprint:
            raise ConflictError(
                "Execution plan changed before Director delegation",
                details={"code": "PLAN_FINGERPRINT_MISMATCH"},
            )
        if sorted(plan.accepted_approximations) != sorted(execution.accepted_approximations):
            raise ConflictError(
                "Execution approximation decision changed before Director delegation",
                details={"code": "ACCEPTED_APPROXIMATIONS_MISMATCH"},
            )
        request_key = f"director-delegation:{decision_id}"
        existing = await self._session.scalar(select(DirectorTurn).where(
            DirectorTurn.project_id == project.id,
            DirectorTurn.request_key == request_key,
        ))
        if existing is not None:
            if existing.proposal_id is None:
                raise ConflictError(
                    "Director delegation has an invalid persisted proposal",
                    details={"code": "DIRECTOR_RUNTIME_REQUEST_CONFLICT"},
                )
            return await DirectorRuntimeStartService(
                self._session, settings=self._settings,
            ).accept(
                project=project,
                actor=actor,
                proposal_id=existing.proposal_id,
                authorization_ref=authorization_id,
                request_key=request_key,
                max_steps=max_steps,
            )

        thread = await self._session.scalar(select(DirectorThread).where(
            DirectorThread.project_id == project.id,
            DirectorThread.scope_type == "shot",
            DirectorThread.scope_entity_id == shot_id,
        ))
        if thread is None:
            thread = DirectorThread(
                project_id=project.id,
                scope_type="shot",
                scope_entity_id=shot_id,
                title="Shot Director",
                created_by=actor.id,
            )
            self._session.add(thread)
            await self._session.flush()
        proposal = DirectorProposal(
            project_id=project.id,
            thread_id=thread.id,
            scope_type="shot",
            scope_entity_id=shot_id,
            status="applied",
            created_by=actor.id,
            decided_at=now,
        )
        self._session.add(proposal)
        await self._session.flush()
        self._session.add(DirectorProposalItem(
            proposal_id=proposal.id,
            project_id=project.id,
            command="production.request_stage_execution",
            payload={
                "shot_id": str(shot_id),
                "stage": execution.stage,
                "authorization_ref": str(authorization_id),
                "plan_fingerprint": execution.plan_fingerprint,
            },
            expected_target_version=execution.expected_shot_version,
            rationale="User explicitly delegated this frozen production plan.",
            benefit="Director runtime can coordinate one accepted execution.",
            cost="One authorized provider execution.",
            risk="The grant expires and cannot be reused for another plan.",
            impact=f"shot:{shot_id}:{execution.stage}",
            status="accepted",
            decided_at=now,
        ))
        await self._session.flush()
        return await DirectorRuntimeStartService(
            self._session, settings=self._settings,
        ).accept(
            project=project,
            actor=actor,
            proposal_id=proposal.id,
            authorization_ref=authorization_id,
            request_key=request_key,
            max_steps=max_steps,
        )


__all__ = ["DirectorRuntimeDelegationService"]
