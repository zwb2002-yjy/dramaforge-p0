"""Finite, fact-derived next actions for durable Director turns.

The reconciler reads canonical Proposal/NodeRun/Profile rows and records only a
typed coordination projection on DirectorTurn. It never executes an arbitrary
tool, invokes a Provider, creates a NodeRun, or selects Formal media.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, ProjectCreativeProfile
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.turn_models import DirectorTurn
from app.director.turn_service import TERMINAL_TURN_STATUSES, DirectorTurnService
from app.execution.models import NodeRun
from app.shared.errors import ConflictError, ValidationAppError

_RUN_ACTIVE = frozenset({"queued", "running", "cancel_requested"})
_RUN_SUCCESS = frozenset({"cached", "completed", "completed_after_cancel"})
_RUN_FAILURE = frozenset({"failed", "cancelled"})


class DirectorNextAction(StrEnum):
    WAIT_FOR_EXECUTION = "wait_for_execution"
    REVIEW_EXECUTION_FAILURE = "review_execution_failure"
    CONFIRM_FORMAL_CANDIDATE = "confirm_formal_candidate"
    REVIEW_PRODUCTION_RESULT = "review_production_result"
    REVIEW_PROPOSAL = "review_proposal"
    REVIEW_ACCEPTED_CHANGES = "review_accepted_changes"
    PROPOSAL_REJECTED = "proposal_rejected"
    REVIEW_STALE_PROPOSAL = "review_stale_proposal"
    REVIEW_SUGGESTION = "review_suggestion"
    MANUAL_NO_ADVANCE = "manual_no_advance"
    COMPLETED = "completed"


class DirectorNextActionRead(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID
    action: DirectorNextAction
    requires_confirmation: bool
    reason: str
    autonomy: str
    fact_hash: str = Field(min_length=64, max_length=64)
    event_key: str
    turn_status: str
    turn_revision: int
    step_count: int
    node_run_ids: list[UUID] = Field(default_factory=list)
    accepted_item_ids: list[UUID] = Field(default_factory=list)
    rejected_item_ids: list[UUID] = Field(default_factory=list)


@dataclass(frozen=True)
class _Decision:
    action: DirectorNextAction
    requires_confirmation: bool
    reason: str
    node_run_ids: list[UUID]
    accepted_item_ids: list[UUID]
    rejected_item_ids: list[UUID]


def _canonical_hash(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _coordination(turn: DirectorTurn) -> dict[str, object]:
    return _mapping((turn.response_summary or {}).get("coordination"))


class DirectorNextActionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._turns = DirectorTurnService(session)

    async def reconcile(
        self,
        *,
        project: Project,
        turn_id: UUID,
        event_key: str | None = None,
        expected_revision: int | None = None,
    ) -> DirectorNextActionRead:
        turn = await self._turns.get(project_id=project.id, turn_id=turn_id)
        if turn.status in TERMINAL_TURN_STATUSES:
            stored = self._stored_current(turn)
            if (
                stored is not None
                and stored.turn_status == turn.status
                and stored.turn_revision == turn.revision
            ):
                return stored
            return DirectorNextActionRead(
                turn_id=turn.id,
                action=DirectorNextAction.COMPLETED,
                requires_confirmation=False,
                reason=f"Director turn is already {turn.status}.",
                autonomy=await self._autonomy(project.id),
                fact_hash=_canonical_hash({"status": turn.status, "revision": turn.revision}),
                event_key=event_key or f"terminal:{turn.status}:{turn.revision}",
                turn_status=turn.status,
                turn_revision=turn.revision,
                step_count=turn.step_count,
            )
        if turn.status not in {"awaiting_user", "awaiting_execution"}:
            raise ValidationAppError(
                "Director turn is not at a reconcilable checkpoint",
                details={
                    "code": "DIRECTOR_TURN_NOT_RECONCILABLE",
                    "status": turn.status,
                },
            )

        # Expiry always stops the turn. A duplicate does not spend a step and
        # may still read the final allowed checkpoint; CAS guards new decisions.
        await self._turns.enforce_limits(turn, advancing=False)
        autonomy = await self._autonomy(project.id)
        decision, target_status, wait_reason, facts = await self._derive(
            project=project,
            turn=turn,
            autonomy=autonomy,
        )
        fact_hash = _canonical_hash(facts)
        stable_event_key = (event_key or f"facts:{fact_hash}").strip()
        if not stable_event_key or len(stable_event_key) > 200:
            raise ValidationAppError(
                "Director event_key must contain 1 to 200 characters",
                details={"code": "DIRECTOR_EVENT_KEY_INVALID"},
            )
        previous = self._processed_event(turn, stable_event_key)
        if previous is not None:
            if previous != fact_hash:
                raise ConflictError(
                    "Director event key was reused for changed business facts",
                    details={"code": "DIRECTOR_EVENT_KEY_REUSED"},
                )
            stored = self._stored_current(turn)
            if stored is None:
                raise ConflictError(
                    "Director event exists without its result projection",
                    details={"code": "DIRECTOR_EVENT_RESULT_MISSING"},
                )
            return stored
        processed = _mapping(_coordination(turn).get("processed_events"))
        if fact_hash in {str(value) for value in processed.values()}:
            stored = self._stored_current(turn)
            if stored is None:
                raise ConflictError(
                    "Director fact-set exists without its result projection",
                    details={"code": "DIRECTOR_EVENT_RESULT_MISSING"},
                )
            return stored
        if expected_revision is not None and turn.revision != expected_revision:
            raise ConflictError(
                "Director turn revision conflict",
                details={
                    "code": "DIRECTOR_TURN_REVISION_CONFLICT",
                    "status": turn.status,
                    "revision": turn.revision,
                },
            )

        result = DirectorNextActionRead(
            turn_id=turn.id,
            action=decision.action,
            requires_confirmation=decision.requires_confirmation,
            reason=decision.reason,
            autonomy=autonomy,
            fact_hash=fact_hash,
            event_key=stable_event_key,
            turn_status=target_status,
            turn_revision=turn.revision + 1,
            step_count=turn.step_count + 1,
            node_run_ids=decision.node_run_ids,
            accepted_item_ids=decision.accepted_item_ids,
            rejected_item_ids=decision.rejected_item_ids,
        )
        summary = dict(turn.response_summary or {})
        coordination = _coordination(turn)
        processed = _mapping(coordination.get("processed_events"))
        processed[stable_event_key] = fact_hash
        coordination.update(
            {
                "processed_events": processed,
                "current_action": result.model_dump(mode="json"),
            }
        )
        summary["coordination"] = coordination
        try:
            changed = await self._turns.compare_and_set(
                turn=turn,
                expected_statuses=(turn.status,),
                target_status=target_status,
                updates={
                    "response_summary": summary,
                    "wait_reason": wait_reason,
                    "last_error": (
                        decision.reason
                        if decision.action is DirectorNextAction.REVIEW_EXECUTION_FAILURE
                        else None
                    ),
                },
                increment_step=True,
            )
        except ConflictError:
            await self._session.refresh(turn)
            stored = self._stored_current(turn)
            if stored is not None and stored.fact_hash == fact_hash:
                return stored
            raise
        stored = self._stored_current(changed)
        assert stored is not None
        return stored

    async def _derive(
        self,
        *,
        project: Project,
        turn: DirectorTurn,
        autonomy: str,
    ) -> tuple[_Decision, str, str, dict[str, object]]:
        stored = self._stored_current(turn)
        execution_checkpoint = stored is not None and bool(stored.node_run_ids)
        if turn.status == "awaiting_execution" or (turn.node_run_ids and execution_checkpoint):
            runs = await self._load_runs(project_id=project.id, turn=turn)
            facts: dict[str, object] = {
                "kind": "execution",
                "autonomy": autonomy,
                "runs": [
                    {
                        "id": str(run.id),
                        "status": run.status,
                        "result_artifact_id": (
                            str(run.result_artifact_id) if run.result_artifact_id else None
                        ),
                    }
                    for run in runs
                ],
            }
            ids = [run.id for run in runs]
            statuses = {run.status for run in runs}
            if not statuses or not statuses <= _RUN_ACTIVE | _RUN_SUCCESS | _RUN_FAILURE:
                raise ValidationAppError(
                    "Director execution links have an unsupported state",
                    details={"code": "DIRECTOR_EXECUTION_STATE_INVALID"},
                )
            if statuses & _RUN_ACTIVE:
                return (
                    self._decision(
                        DirectorNextAction.WAIT_FOR_EXECUTION,
                        confirmation=False,
                        reason="Production is still running; no new command was issued.",
                        node_run_ids=ids,
                    ),
                    "awaiting_execution",
                    "execution_in_progress",
                    facts,
                )
            if statuses & _RUN_FAILURE:
                return (
                    self._decision(
                        DirectorNextAction.REVIEW_EXECUTION_FAILURE,
                        confirmation=True,
                        reason="Production reached a failed or cancelled terminal state.",
                        node_run_ids=ids,
                    ),
                    "awaiting_user",
                    "execution_failed",
                    facts,
                )
            if not statuses or not statuses <= _RUN_SUCCESS:
                raise ValidationAppError(
                    "Director execution links have an unsupported state",
                    details={"code": "DIRECTOR_EXECUTION_STATE_INVALID"},
                )
            if any(run.result_artifact_id is None for run in runs):
                raise ValidationAppError(
                    "Completed Director execution link has no result Artifact",
                    details={"code": "DIRECTOR_EXECUTION_RESULT_MISSING"},
                )
            action = (
                DirectorNextAction.CONFIRM_FORMAL_CANDIDATE
                if autonomy == "AUTO"
                else DirectorNextAction.REVIEW_PRODUCTION_RESULT
                if autonomy == "ASSIST"
                else DirectorNextAction.MANUAL_NO_ADVANCE
            )
            return (
                self._decision(
                    action,
                    confirmation=True,
                    reason=(
                        "Production completed. Formal selection remains an explicit user gate."
                    ),
                    node_run_ids=ids,
                ),
                "awaiting_user",
                "formal_confirmation" if autonomy == "AUTO" else "production_review",
                facts,
            )

        if turn.proposal_id is None:
            facts = {
                "kind": "suggestion",
                "autonomy": autonomy,
                "output_hash": turn.output_hash,
                "status": turn.status,
            }
            action = (
                DirectorNextAction.MANUAL_NO_ADVANCE
                if autonomy == "MANUAL"
                else DirectorNextAction.REVIEW_SUGGESTION
            )
            return (
                self._decision(
                    action,
                    confirmation=True,
                    reason="The persisted suggestion is waiting for a user decision.",
                ),
                "awaiting_user",
                "proposal_decision",
                facts,
            )

        proposal = await self._session.scalar(
            select(DirectorProposal).where(
                DirectorProposal.id == turn.proposal_id,
                DirectorProposal.project_id == project.id,
            )
        )
        if proposal is None:
            raise ValidationAppError(
                "Director turn proposal link is missing",
                details={"code": "DIRECTOR_PROPOSAL_LINK_MISSING"},
            )
        items = list(
            (
                await self._session.execute(
                    select(DirectorProposalItem)
                    .where(
                        DirectorProposalItem.proposal_id == proposal.id,
                        DirectorProposalItem.project_id == project.id,
                    )
                    .order_by(DirectorProposalItem.created_at, DirectorProposalItem.id)
                )
            )
            .scalars()
            .all()
        )
        if not items:
            raise ValidationAppError(
                "Director proposal has no decision items",
                details={"code": "DIRECTOR_PROPOSAL_ITEMS_MISSING"},
            )
        if any(item.status not in {"pending", "accepted", "rejected", "stale"} for item in items):
            raise ValidationAppError(
                "Director proposal contains unsupported decision states",
                details={"code": "DIRECTOR_PROPOSAL_ITEM_STATE_INVALID"},
            )
        accepted = [item.id for item in items if item.status == "accepted"]
        rejected = [item.id for item in items if item.status == "rejected"]
        pending = [item.id for item in items if item.status == "pending"]
        facts = {
            "kind": "proposal",
            "autonomy": autonomy,
            "proposal_id": str(proposal.id),
            "proposal_status": proposal.status,
            "items": [{"id": str(item.id), "status": item.status} for item in items],
        }
        if any(item.status == "stale" for item in items):
            return (
                self._decision(
                    DirectorNextAction.REVIEW_STALE_PROPOSAL,
                    confirmation=True,
                    reason="Proposal targets changed; stale items cannot be applied or retried.",
                    accepted_item_ids=accepted,
                    rejected_item_ids=rejected,
                ),
                "stale",
                "proposal_stale",
                facts,
            )
        if pending:
            return (
                self._decision(
                    DirectorNextAction.REVIEW_PROPOSAL,
                    confirmation=True,
                    reason="A typed proposal is waiting for explicit item decisions.",
                    accepted_item_ids=accepted,
                    rejected_item_ids=rejected,
                ),
                "awaiting_user",
                "proposal_decision",
                facts,
            )
        if accepted:
            return (
                self._decision(
                    DirectorNextAction.REVIEW_ACCEPTED_CHANGES,
                    confirmation=True,
                    reason="Only accepted proposal items changed canonical facts.",
                    accepted_item_ids=accepted,
                    rejected_item_ids=rejected,
                ),
                "awaiting_user",
                "accepted_changes_review",
                facts,
            )
        return (
            self._decision(
                DirectorNextAction.PROPOSAL_REJECTED,
                confirmation=False,
                reason="All proposal items were rejected; this suggestion branch is closed.",
                rejected_item_ids=rejected,
            ),
            "completed",
            "proposal_rejected",
            facts,
        )

    async def _load_runs(self, *, project_id: UUID, turn: DirectorTurn) -> list[NodeRun]:
        try:
            ids = [UUID(str(value)) for value in (turn.node_run_ids or [])]
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValidationAppError(
                "Director turn contains an invalid NodeRun link",
                details={"code": "DIRECTOR_NODE_RUN_LINK_INVALID"},
            ) from exc
        if not ids:
            raise ValidationAppError(
                "Director turn is awaiting execution without a NodeRun link",
                details={"code": "DIRECTOR_NODE_RUN_LINK_MISSING"},
            )
        rows = list(
            (
                await self._session.execute(
                    select(NodeRun).where(
                        NodeRun.id.in_(ids),
                        NodeRun.project_id == project_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = {row.id: row for row in rows}
        if set(by_id) != set(ids):
            raise ValidationAppError(
                "Director turn NodeRun link is missing or belongs to another project",
                details={"code": "DIRECTOR_NODE_RUN_LINK_MISSING"},
            )
        return [by_id[node_id] for node_id in ids]

    async def _autonomy(self, project_id: UUID) -> str:
        profile = await self._session.scalar(
            select(ProjectCreativeProfile).where(ProjectCreativeProfile.project_id == project_id)
        )
        return str(profile.director_autonomy if profile is not None else "ASSIST")

    @staticmethod
    def _decision(
        action: DirectorNextAction,
        *,
        confirmation: bool,
        reason: str,
        node_run_ids: list[UUID] | None = None,
        accepted_item_ids: list[UUID] | None = None,
        rejected_item_ids: list[UUID] | None = None,
    ) -> _Decision:
        return _Decision(
            action=action,
            requires_confirmation=confirmation,
            reason=reason,
            node_run_ids=node_run_ids or [],
            accepted_item_ids=accepted_item_ids or [],
            rejected_item_ids=rejected_item_ids or [],
        )

    @staticmethod
    def _processed_event(turn: DirectorTurn, event_key: str) -> str | None:
        raw = _mapping(_coordination(turn).get("processed_events")).get(event_key)
        return str(raw) if raw is not None else None

    @staticmethod
    def _stored_current(turn: DirectorTurn) -> DirectorNextActionRead | None:
        raw = _coordination(turn).get("current_action")
        if not isinstance(raw, Mapping):
            return None
        return DirectorNextActionRead.model_validate(raw)


__all__ = [
    "DirectorNextAction",
    "DirectorNextActionRead",
    "DirectorNextActionService",
]
