"""Adapters from the Director graph to persisted DramaForge domain facts."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.access.models import User
from app.contracts.director_runtime import ResumeSignal, RuntimeInput, RuntimeScope
from app.contracts.production_commands import ExecutionReceipt
from app.contracts.production_facts import ExecutionFact
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.runtime.ports import RuntimeDecisionFact, RuntimeProposalFact
from app.director.turn_models import DirectorTurn
from app.events.models import EventLog
from app.production.application.authorization import ProductionAuthorizations
from app.production.application.facts import ProductionFacts
from app.production.command_models import ProductionCommandAuthorization
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError


class DirectorDomainRuntimeTools:
    """Read decisions and submit only an already persisted one-shot grant."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        *,
        scope: RuntimeScope,
        turn_id: UUID,
    ) -> None:
        self._factory = factory
        self._scope = scope
        self._turn_id = turn_id

    async def propose(self, request: RuntimeInput) -> RuntimeProposalFact:
        self._assert_request(request)
        async with self._factory() as session:
            await self._set_scope(session)
            turn = await self._turn(session)
            if turn.proposal_id is None:
                task = (turn.request_summary or {}).get("task")
                if (
                    request.input_reference != turn.id
                    or task not in {
                        "shot_director_suggestion", "shot_director_recommendation",
                    }
                    or not turn.output_hash
                    or not turn.output_snapshot
                ):
                    raise NotFoundError("Director proposal not found")
                return RuntimeProposalFact(
                    proposal_id=None,
                    proposal_version=turn.revision,
                    command_key=None,
                )
            proposal_id = turn.proposal_id
            proposal = await session.scalar(select(DirectorProposal).where(
                DirectorProposal.id == proposal_id,
                DirectorProposal.project_id == self._scope.project_id,
            ))
            if proposal is None:
                raise NotFoundError("Director proposal not found")
            items = list((await session.scalars(select(DirectorProposalItem).where(
                DirectorProposalItem.proposal_id == proposal.id,
                DirectorProposalItem.project_id == self._scope.project_id,
            ))).all())
            if not items:
                raise NotFoundError("Director proposal items not found")
            command_key: str | None = None
            if request.authorization_ref is not None:
                grant = await session.scalar(select(ProductionCommandAuthorization).where(
                    ProductionCommandAuthorization.id == request.authorization_ref,
                    ProductionCommandAuthorization.project_id == self._scope.project_id,
                    ProductionCommandAuthorization.actor_id == self._scope.actor_id,
                ))
                if grant is None:
                    raise NotFoundError("Production authorization not found")
                command_key = grant.command_key
            raw_version = (turn.intent_snapshot or {}).get("proposal_version", 1)
            proposal_version = (
                raw_version if isinstance(raw_version, int) and raw_version > 0 else 1
            )
            pending = any(item.status == "pending" for item in items)
            accepted = any(item.status == "accepted" for item in items)
            if any(item.status not in {"pending", "accepted", "rejected"} for item in items):
                raise ConflictError(
                    "Director proposal has an invalid decision state",
                    details={"code": "DIRECTOR_PROPOSAL_DECISION_INVALID"},
                )
            return RuntimeProposalFact(
                proposal_id=proposal.id,
                proposal_version=proposal_version,
                command_key=command_key,
                persisted_decision=(
                    None if pending else "accept" if accepted else "reject"
                ),
                next_action=(
                    "execute"
                    if not pending and accepted and request.authorization_ref is not None
                    else "complete"
                ),
            )

    async def decision(self, signal: ResumeSignal) -> RuntimeDecisionFact:
        self._assert_signal(signal)
        async with self._factory() as session:
            await self._set_scope(session)
            turn = await self._turn(session)
            if signal.reference_id == turn.id and turn.proposal_id is None:
                decision = (turn.response_summary or {}).get("user_decision")
                if (
                    not isinstance(decision, dict)
                    or decision.get("output_hash") != turn.output_hash
                ):
                    raise NotFoundError("Director decision fact not found")
                value = decision.get("decision")
                if value not in {"accept", "reject"}:
                    raise NotFoundError("Director decision fact not found")
                return RuntimeDecisionFact(
                    decision=value,
                    decision_version=signal.expected_revision,
                    next_action="complete",
                )
            event = await session.scalar(select(EventLog).where(
                EventLog.event_id == signal.reference_id,
                EventLog.project_id == self._scope.project_id,
                EventLog.actor_id == self._scope.actor_id,
            ))
            notice = (event.payload or {}).get("notice") if event is not None else None
            proposal_reference = signal.reference_id
            if isinstance(notice, dict) and notice.get("kind") == "proposal_decided":
                proposal_reference = UUID(str(notice.get("proposal_id")))
            proposal = await session.scalar(select(DirectorProposal).where(
                DirectorProposal.id == proposal_reference,
                DirectorProposal.project_id == self._scope.project_id,
            ))
            if proposal is not None:
                items = list((await session.scalars(select(DirectorProposalItem).where(
                    DirectorProposalItem.proposal_id == proposal.id,
                    DirectorProposalItem.project_id == self._scope.project_id,
                ))).all())
                if not items or any(item.status == "pending" for item in items):
                    raise ConflictError(
                        "Director proposal decision is not complete",
                        details={"code": "DIRECTOR_PROPOSAL_DECISION_PENDING"},
                    )
                accepted = any(item.status == "accepted" for item in items)
                has_authorization = bool(
                    (turn.intent_snapshot or {}).get("authorization_ref")
                )
                return RuntimeDecisionFact(
                    decision="accept" if accepted else "reject",
                    decision_version=signal.expected_revision,
                    next_action="execute" if accepted and has_authorization else "complete",
                )
            if not isinstance(notice, dict) or notice.get("kind") != "formal_selected":
                raise NotFoundError("Director decision fact not found")
            return RuntimeDecisionFact(
                decision="accept",
                decision_version=signal.expected_revision,
                next_action="complete",
            )

    async def submit_execution(
        self,
        *,
        request: RuntimeInput,
        proposal: RuntimeProposalFact,
        command_key: str,
    ) -> ExecutionReceipt:
        self._assert_request(request)
        if request.authorization_ref is None or proposal.command_key != command_key:
            raise ValidationAppError(
                "Director execution has no matching persisted authorization",
                details={"code": "PRODUCTION_COMMAND_NOT_AUTHORIZED"},
            )
        async with self._factory() as session:
            await self._set_scope(session)
            actor = await session.get(User, self._scope.actor_id)
            grant = await session.scalar(select(ProductionCommandAuthorization).where(
                ProductionCommandAuthorization.id == request.authorization_ref,
                ProductionCommandAuthorization.project_id == self._scope.project_id,
                ProductionCommandAuthorization.actor_id == self._scope.actor_id,
            ))
            if actor is None or grant is None or grant.command_key != command_key:
                raise NotFoundError("Production authorization not found")
            receipt = await ProductionAuthorizations(session).submit(
                actor=actor,
                project_id=self._scope.project_id,
                authorization_id=request.authorization_ref,
            )
            await session.commit()
            return receipt

    async def execution_fact(self, signal: ResumeSignal) -> ExecutionFact:
        self._assert_signal(signal)
        async with self._factory() as session:
            await self._set_scope(session)
            event = await session.scalar(select(EventLog).where(
                EventLog.event_id == signal.reference_id,
                EventLog.project_id == self._scope.project_id,
            ))
            notice = (event.payload or {}).get("notice") if event is not None else None
            if not isinstance(notice, dict) or notice.get("kind") != "execution_changed":
                raise NotFoundError("Production completion fact not found")
            run_id = UUID(str(notice.get("node_run_id")))
            tracking = await ProductionFacts(session).tracking(
                project_id=self._scope.project_id,
                run_id=run_id,
            )
            return ExecutionFact.model_validate(tracking.model_dump())

    async def _turn(self, session: AsyncSession) -> DirectorTurn:
        turn = await session.scalar(select(DirectorTurn).where(
            DirectorTurn.id == self._turn_id,
            DirectorTurn.project_id == self._scope.project_id,
            DirectorTurn.runtime_execution_id.is_not(None),
        ))
        if turn is None:
            raise NotFoundError("Director runtime turn not found")
        return turn

    async def _set_scope(self, session: AsyncSession) -> None:
        await set_rls_context(
            session,
            user_id=self._scope.actor_id,
            workspace_id=self._scope.workspace_id,
            project_id=self._scope.project_id,
        )

    def _assert_request(self, request: RuntimeInput) -> None:
        if request.scope != self._scope or request.turn_id != self._turn_id:
            raise NotFoundError("Director runtime scope not found")

    def _assert_signal(self, signal: ResumeSignal) -> None:
        if signal.scope != self._scope or signal.turn_id != self._turn_id:
            raise NotFoundError("Director runtime scope not found")


__all__ = ["DirectorDomainRuntimeTools"]
