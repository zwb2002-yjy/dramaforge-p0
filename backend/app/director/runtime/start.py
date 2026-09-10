"""Authenticated acceptance of a persisted Proposal into the Director runtime."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.config import Settings
from app.contracts.director_runtime import RuntimeInput, RuntimeScope
from app.director.assistant_models import DirectorThread
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.runtime.control import DirectorRuntimeControlService
from app.director.runtime.models import DirectorRuntimeWakeup
from app.director.runtime.routing import DirectorEngineRouter
from app.director.runtime.wakeups import DirectorRuntimeWakeupService
from app.director.turn_models import DirectorTurn
from app.director.turn_service import DirectorTurnService
from app.production.command_models import ProductionCommandAuthorization
from app.shared.errors import ConflictError, NotFoundError


class DirectorRuntimeStartService:
    def __init__(self, session: AsyncSession, *, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def accept(
        self,
        *,
        project: Project,
        actor: User,
        proposal_id: UUID,
        authorization_ref: UUID | None,
        request_key: str,
        max_steps: int,
    ) -> tuple[DirectorTurn, DirectorRuntimeWakeup]:
        if self._settings.director_runtime_engine != "langgraph":
            raise ConflictError(
                "The durable Director runtime is not enabled for new turns",
                details={"code": "DIRECTOR_RUNTIME_NOT_ENABLED", "manual_ok": True},
            )
        result = await self._session.execute(
            select(DirectorProposal, DirectorThread)
            .join(DirectorThread, DirectorThread.id == DirectorProposal.thread_id)
            .where(
                DirectorProposal.id == proposal_id,
                DirectorProposal.project_id == project.id,
                DirectorThread.project_id == project.id,
            )
        )
        row = result.one_or_none()
        if row is None:
            raise NotFoundError("Director proposal not found")
        proposal, thread = row
        items = list((await self._session.scalars(
            select(DirectorProposalItem).where(
                DirectorProposalItem.proposal_id == proposal.id,
                DirectorProposalItem.project_id == project.id,
            ).order_by(DirectorProposalItem.id)
        )).all())
        grant: ProductionCommandAuthorization | None = None
        if authorization_ref is not None:
            grant = await self._session.scalar(select(ProductionCommandAuthorization).where(
                ProductionCommandAuthorization.id == authorization_ref,
                ProductionCommandAuthorization.project_id == project.id,
                ProductionCommandAuthorization.actor_id == actor.id,
            ))
            if grant is None:
                raise NotFoundError("Production authorization not found")
            if thread.scope_type == "shot" and grant.shot_id != thread.scope_entity_id:
                raise ConflictError(
                    "Production authorization is outside the Proposal scope",
                    details={"code": "DIRECTOR_AUTHORIZATION_SCOPE_MISMATCH"},
                )
        context_snapshot: dict[str, object] = {
            "proposal_id": str(proposal.id),
            "proposal_status": proposal.status,
            "proposal_items": [
                {
                    "id": str(item.id),
                    "command": item.command,
                    "status": item.status,
                    "expected_target_version": item.expected_target_version,
                }
                for item in items
            ],
            "authorization_ref": str(grant.id) if grant is not None else None,
            "authorization_request_hash": grant.request_hash if grant is not None else None,
        }
        intent_snapshot: dict[str, object] = {
            "task": "proposal_runtime",
            "proposal_id": str(proposal.id),
            "proposal_version": 1,
            "authorization_ref": str(grant.id) if grant is not None else None,
        }
        turn, created = await DirectorTurnService(self._session).create_or_get(
            project=project,
            actor=actor,
            scope_type=thread.scope_type,
            scope_entity_id=thread.scope_entity_id,
            request_key=request_key,
            context_snapshot=context_snapshot,
            intent_snapshot=intent_snapshot,
            max_steps=max_steps,
        )
        if created:
            turn.proposal_id = proposal.id
            await self._session.flush()
        elif turn.proposal_id != proposal.id:
            raise ConflictError(
                "Director request key belongs to another Proposal",
                details={"code": "DIRECTOR_RUNTIME_REQUEST_CONFLICT"},
            )
        control = await DirectorEngineRouter(
            settings=self._settings,
            controls=DirectorRuntimeControlService(self._session),
        ).bind_new(turn, created=created)
        if control is None:
            raise ConflictError(
                "An existing legacy turn cannot be migrated to LangGraph",
                details={"code": "DIRECTOR_ENGINE_BINDING_CONFLICT"},
            )
        request = RuntimeInput(
            scope=RuntimeScope(
                workspace_id=project.workspace_id,
                project_id=project.id,
                actor_id=actor.id,
            ),
            turn_id=turn.id,
            runtime_execution_id=control.runtime_execution_id,
            engine_version=control.engine_version,
            input_reference=proposal.id,
            authorization_ref=authorization_ref,
            max_steps=max_steps,
        )
        wakeup = await DirectorRuntimeWakeupService(self._session).enqueue_start(request)
        return turn, wakeup

    async def accept_existing_new_turn(
        self,
        *,
        project: Project,
        actor: User,
        turn: DirectorTurn,
        proposal_id: UUID,
        created: bool,
        authorization_ref: UUID | None = None,
    ) -> DirectorRuntimeWakeup | None:
        """Bind a Turn created in this request; legacy/replayed Turns stay untouched."""

        if self._settings.director_runtime_engine != "langgraph":
            return None
        if turn.project_id != project.id or turn.actor_id != actor.id:
            raise NotFoundError("Director turn not found")
        if not created and turn.runtime_execution_id is None:
            return None
        proposal = await self._session.scalar(select(DirectorProposal).where(
            DirectorProposal.id == proposal_id,
            DirectorProposal.project_id == project.id,
        ))
        if proposal is None:
            raise NotFoundError("Director proposal not found")
        if turn.proposal_id is None:
            turn.proposal_id = proposal.id
        elif turn.proposal_id != proposal.id:
            raise ConflictError(
                "Director turn belongs to another Proposal",
                details={"code": "DIRECTOR_RUNTIME_REQUEST_CONFLICT"},
            )
        intent = dict(turn.intent_snapshot or {})
        intent.update({
            "proposal_id": str(proposal.id),
            "proposal_version": 1,
            "authorization_ref": (
                str(authorization_ref) if authorization_ref is not None else None
            ),
        })
        turn.intent_snapshot = intent
        await self._session.flush()
        control = await DirectorEngineRouter(
            settings=self._settings,
            controls=DirectorRuntimeControlService(self._session),
        ).bind_new(turn, created=created)
        if control is None:
            return None
        max_steps_raw = (turn.request_summary or {}).get("max_steps", 6)
        max_steps = (
            max_steps_raw
            if isinstance(max_steps_raw, int) and 1 <= max_steps_raw <= 8
            else 6
        )
        request = RuntimeInput(
            scope=RuntimeScope(
                workspace_id=project.workspace_id,
                project_id=project.id,
                actor_id=actor.id,
            ),
            turn_id=turn.id,
            runtime_execution_id=control.runtime_execution_id,
            engine_version=control.engine_version,
            input_reference=proposal.id,
            authorization_ref=authorization_ref,
            max_steps=max_steps,
        )
        return await DirectorRuntimeWakeupService(self._session).enqueue_start(request)

    async def accept_existing_detached_turn(
        self,
        *,
        project: Project,
        actor: User,
        turn: DirectorTurn,
        created: bool,
    ) -> DirectorRuntimeWakeup | None:
        """Bind a newly generated draft-only suggestion without inventing a Proposal row."""

        if self._settings.director_runtime_engine != "langgraph":
            return None
        if turn.project_id != project.id or turn.actor_id != actor.id:
            raise NotFoundError("Director turn not found")
        if not created and turn.runtime_execution_id is None:
            return None
        task = (turn.request_summary or {}).get("task")
        if (
            turn.proposal_id is not None
            or task not in {"shot_director_suggestion", "shot_director_recommendation"}
            or not turn.output_hash
            or not turn.output_snapshot
        ):
            raise ConflictError(
                "Director turn is not a persisted draft-only suggestion",
                details={"code": "DIRECTOR_RUNTIME_INPUT_INVALID"},
            )
        control = await DirectorEngineRouter(
            settings=self._settings,
            controls=DirectorRuntimeControlService(self._session),
        ).bind_new(turn, created=created)
        if control is None:
            return None
        max_steps_raw = (turn.request_summary or {}).get("max_steps", 4)
        max_steps = (
            max_steps_raw
            if isinstance(max_steps_raw, int) and 1 <= max_steps_raw <= 8
            else 4
        )
        request = RuntimeInput(
            scope=RuntimeScope(
                workspace_id=project.workspace_id,
                project_id=project.id,
                actor_id=actor.id,
            ),
            turn_id=turn.id,
            runtime_execution_id=control.runtime_execution_id,
            engine_version=control.engine_version,
            input_reference=turn.id,
            max_steps=max_steps,
        )
        return await DirectorRuntimeWakeupService(self._session).enqueue_start(request)


__all__ = ["DirectorRuntimeStartService"]
