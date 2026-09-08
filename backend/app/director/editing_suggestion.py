"""Server-fact-driven Director suggestions for persisted EditSessions.

This is deliberately a service seam, not an HTTP or UI surface.  It reads one
server-owned EditSession, asks the configured audited text transport for a
typed plan, rechecks the session version, and persists exactly one existing
DirectorProposal plus one typed command item.  It never applies the command
or touches production/execution facts.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.director.assistant_models import DirectorThread
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.text_transport import DirectorInvocationEvidence, DirectorTextTransport
from app.director.turn_models import DirectorTurn
from app.director.turn_service import DirectorTurnService
from app.editing.adapter import EditingAdapter
from app.editing.models import EditSession
from app.editing.proposal_plan import (
    EditSessionTimelinePlan,
    ReorderClipsOperation,
    SetClipDurationOperation,
    SetClipSubtitleOperation,
)
from app.providers.model_profiles.slots import ModelSlot
from app.shared.db import set_rls_context
from app.shared.errors import AppError, ConflictError, NotFoundError, ValidationAppError


class EditingDirectorSuggestionRequest(BaseModel):
    """The only user-supplied values accepted by the suggestion service."""

    model_config = ConfigDict(extra="forbid")

    expected_session_version: int = Field(ge=1)
    user_instruction: str = Field(min_length=1, max_length=4000)
    request_key: str = Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")

    @field_validator("user_instruction")
    @classmethod
    def instruction_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("user_instruction must not be blank")
        return normalized


class EditingProactiveSuggestionRequest(BaseModel):
    """No user instruction; the server analyzes the current timeline."""

    model_config = ConfigDict(extra="forbid")

    expected_session_version: int = Field(ge=1)
    request_key: str = Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")


class EditingDirectorClipContext(BaseModel):
    """The design-only portion of one server-owned timeline clip."""

    model_config = ConfigDict(extra="forbid")

    clip_id: str = Field(min_length=1, max_length=200)
    order: int = Field(ge=1)
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)
    shot_id: str | None = Field(default=None, max_length=200)
    subtitle: str = Field(default="", max_length=4000)


class EditingDirectorSuggestionContext(BaseModel):
    """Context intentionally excludes artifact/provider/runtime details."""

    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    session_id: UUID
    session_version: int = Field(ge=1)
    session_name: str = Field(min_length=1, max_length=200)
    clips: list[EditingDirectorClipContext] = Field(default_factory=list, max_length=1000)
    metadata: dict[str, object] = Field(default_factory=dict)
    user_instruction: str = Field(min_length=1, max_length=4000)


_FORBIDDEN_PLAN_FIELDS = frozenset(
    {
        "artifact",
        "artifact_id",
        "artifact_ids",
        "artifact_url",
        "column",
        "execution",
        "execution_id",
        "execution_plan",
        "field_path",
        "from",
        "json_patch",
        "node_run",
        "node_run_id",
        "node_run_ids",
        "patch",
        "path",
        "production_lineage",
        "provider",
        "provider_model_id",
        "provider_operation",
        "raw_replacement",
        "raw_sql",
        "replacement",
        "replacement_payload",
        "runtime",
        "runtime_id",
        "sql",
        "sql_query",
        "table",
        "to",
        "worker",
        "worker_queue",
    }
)


def _normalize_key(key: object) -> str:
    text = str(key).strip().replace("-", "_").replace(" ", "_")
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return re.sub(r"_+", "_", text).lower()


def _is_forbidden_plan_field(key: object) -> bool:
    normalized = _normalize_key(key)
    return normalized in _FORBIDDEN_PLAN_FIELDS or normalized.startswith(
        (
            "artifact_",
            "execution_",
            "node_run_",
            "provider_",
            "raw_sql_",
            "runtime_",
            "sql_",
            "worker_",
        )
    )


def _reject_forbidden_plan_fields(value: object, *, path: str = "candidate") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if _is_forbidden_plan_field(key):
                raise ValueError(f"{path} contains forbidden field: {key}")
            _reject_forbidden_plan_fields(nested, path=f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            _reject_forbidden_plan_fields(nested, path=f"{path}[{index}]")


def _sanitize_design_metadata(value: object) -> object:
    """Copy timeline metadata without exposing execution/provider fields."""

    if isinstance(value, Mapping):
        return {
            key: _sanitize_design_metadata(nested)
            for key, nested in value.items()
            if not _is_forbidden_plan_field(key)
        }
    if isinstance(value, list):
        return [_sanitize_design_metadata(nested) for nested in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_design_metadata(nested) for nested in value)
    return deepcopy(value)


class EditingDirectorSuggestionCandidate(BaseModel):
    """Typed design proposal returned by the suggestion transport."""

    model_config = ConfigDict(extra="forbid")

    base_session_version: int = Field(ge=1)
    plan: EditSessionTimelinePlan
    rationale: str = Field(min_length=1, max_length=4000)
    benefit: str = Field(min_length=1, max_length=4000)
    cost: str = Field(min_length=1, max_length=4000)
    risk: str = Field(min_length=1, max_length=4000)
    impact: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="before")
    @classmethod
    def reject_untrusted_fields(cls, value: object) -> object:
        _reject_forbidden_plan_fields(value)
        return value


class EditingDirectorSuggestionResult(EditingDirectorSuggestionCandidate):
    """Validated suggestion plus the rows persisted for this exact result.

    The result intentionally subclasses the candidate so callers of the P9-04B
    service can continue to inspect ``plan`` and the explanation fields while
    the HTTP bridge can return the proposal and item identities.  The private
    candidate reference is the validated object that was produced before row
    persistence; it is never loaded through a latest-row query.
    """

    proposal_id: UUID
    item_id: UUID
    director_evidence: DirectorInvocationEvidence | None = None
    _candidate: EditingDirectorSuggestionCandidate = PrivateAttr()

    @property
    def candidate(self) -> EditingDirectorSuggestionCandidate:
        """Return the validated candidate represented by this persisted result."""

        return self._candidate

    @property
    def suggestion(self) -> EditingDirectorSuggestionCandidate:
        """Compatibility alias for callers using the HTTP response vocabulary."""

        return self._candidate


class EditingDirectorSuggestionTransport(Protocol):
    async def generate(self, context: EditingDirectorSuggestionContext) -> object:
        """Return an untrusted candidate for structured validation."""


class DeterministicEditingDirectorSuggestionTransport:
    """No-network fixture; production never selects it implicitly."""

    async def generate(self, context: EditingDirectorSuggestionContext) -> object:
        clip_ids = [clip.clip_id for clip in context.clips]
        operations: list[dict[str, object]] = []
        if len(clip_ids) > 1:
            operations.append({"operation": "reorder_clips", "clip_ids": list(reversed(clip_ids))})
        elif clip_ids:
            operations.append(
                {
                    "operation": "set_clip_duration",
                    "clip_id": clip_ids[0],
                    "duration_seconds": context.clips[0].duration_seconds,
                }
            )
        else:
            # An empty timeline has no valid operation target. The service
            # will fail closed rather than invent a clip or production fact.
            operations = []
        return {
            "base_session_version": context.session_version,
            "plan": {"operations": operations},
            "rationale": f"根据“{context.user_instruction}”审阅当前剪辑顺序与停顿。",
            "benefit": "只调整现有时间线片段，不改变正式生产产物。",
            "cost": "需要人工确认并保存时间线版本。",
            "risk": "顺序或时长变化会影响剪辑节奏。",
            "impact": "仅影响当前 EditSession 的 clips；production lineage 保持只读。",
        }


def get_editing_director_suggestion_transport() -> EditingDirectorSuggestionTransport:
    """Return the explicit deterministic fixture for focused tests."""

    return DeterministicEditingDirectorSuggestionTransport()


@dataclass(frozen=True)
class _TimelineContext:
    clips: list[EditingDirectorClipContext]
    metadata: dict[str, object]


def _timeline_context(timeline: Mapping[str, object]) -> _TimelineContext:
    raw_clips = timeline.get("clips")
    raw_metadata = timeline.get("metadata", {})
    if not isinstance(raw_clips, list) or not all(isinstance(clip, Mapping) for clip in raw_clips):
        raise ValidationAppError(
            "edit session timeline clips must be an array of objects",
            details={"code": "INVALID_EDIT_SESSION_TIMELINE"},
        )
    if not isinstance(raw_metadata, dict):
        raise ValidationAppError(
            "edit session timeline metadata must be an object",
            details={"code": "INVALID_EDIT_SESSION_TIMELINE"},
        )
    contexts: list[EditingDirectorClipContext] = []
    seen_ids: set[str] = set()
    for index, raw_clip in enumerate(raw_clips, start=1):
        clip_id = raw_clip.get("id")
        if not isinstance(clip_id, str) or not clip_id.strip() or clip_id in seen_ids:
            raise ValidationAppError(
                "edit session timeline clip ids must be unique and non-empty",
                details={"code": "INVALID_EDIT_SESSION_TIMELINE"},
            )
        raw_order = raw_clip.get("order", index)
        raw_duration = raw_clip.get("duration_seconds", 0)
        try:
            order = int(raw_order)
            duration = float(raw_duration)
        except (TypeError, ValueError):
            raise ValidationAppError(
                "edit session timeline clip order/duration is invalid",
                details={"code": "INVALID_EDIT_SESSION_TIMELINE"},
            ) from None
        if order < 1 or not math.isfinite(duration) or duration < 0:
            raise ValidationAppError(
                "edit session timeline clip order/duration is invalid",
                details={"code": "INVALID_EDIT_SESSION_TIMELINE"},
            )
        raw_shot_id = raw_clip.get("shot_id")
        shot_id = str(raw_shot_id) if raw_shot_id is not None else None
        raw_subtitle = raw_clip.get("subtitle", "")
        if not isinstance(raw_subtitle, str):
            raise ValidationAppError(
                "edit session timeline clip subtitle must be text",
                details={"code": "INVALID_EDIT_SESSION_TIMELINE"},
            )
        seen_ids.add(clip_id)
        contexts.append(
            EditingDirectorClipContext(
                clip_id=clip_id,
                order=order,
                duration_seconds=duration,
                shot_id=shot_id,
                subtitle=raw_subtitle,
            )
        )
    contexts.sort(key=lambda clip: (clip.order, clip.clip_id))
    # A transport must not receive references into the ORM-owned JSON document.
    # Even the deterministic default is kept behind a protocol so tests and a
    # future explicitly-approved transport cannot mutate EditSession facts by
    # changing nested metadata in-place.
    return _TimelineContext(
        clips=contexts,
        metadata=cast(dict[str, object], _sanitize_design_metadata(raw_metadata)),
    )


def _validate_plan_targets(
    plan: EditSessionTimelinePlan,
    *,
    clip_ids: list[str],
) -> None:
    current_ids = list(clip_ids)
    for operation in plan.operations:
        if isinstance(operation, ReorderClipsOperation):
            operation_ids = list(operation.clip_ids)
            if len(operation_ids) != len(current_ids) or set(operation_ids) != set(current_ids):
                raise ValidationAppError(
                    "reorder_clips must be an exact permutation of existing clip ids",
                    details={"code": "INVALID_EDITING_DIRECTOR_PLAN"},
                )
            current_ids = operation_ids
        elif isinstance(operation, SetClipDurationOperation):
            if operation.clip_id not in current_ids:
                raise ValidationAppError(
                    "set_clip_duration requires an existing clip id",
                    details={"code": "INVALID_EDITING_DIRECTOR_PLAN"},
                )
        elif isinstance(operation, SetClipSubtitleOperation):
            if operation.clip_id not in current_ids:
                raise ValidationAppError(
                    "set_clip_subtitle requires an existing clip id",
                    details={"code": "INVALID_EDITING_DIRECTOR_PLAN"},
                )


class EditingDirectorSuggestionService:
    """Generate and persist one typed Director proposal without applying it."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        transport: EditingDirectorSuggestionTransport | None = None,
        text_transport: DirectorTextTransport | None = None,
    ) -> None:
        self._session = session
        self._transport = transport
        self._text_transport = text_transport or DirectorTextTransport(session)

    async def suggest(
        self,
        *,
        project_id: UUID,
        session_id: UUID,
        actor: User,
        request: EditingDirectorSuggestionRequest,
        proactive: bool = False,
    ) -> EditingDirectorSuggestionResult:
        project = await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        autonomy_version = (
            await DirectorTurnService(self._session).require_proactive_authorization(
                project_id=project.id,
            )
            if proactive else None
        )
        adapter = EditingAdapter(self._session)
        edit_session = await adapter.load_timeline(
            project_id=project.id,
            session_id=session_id,
        )
        if edit_session.version != request.expected_session_version:
            raise ConflictError(
                "edit session version conflict; suggestion must use current server truth",
                details={
                    "code": "EDITING_SUGGESTION_STALE",
                    "expected_version": request.expected_session_version,
                    "actual_version": edit_session.version,
                },
            )

        context_data = _timeline_context(dict(edit_session.timeline or {}))
        context = EditingDirectorSuggestionContext(
            project_id=project.id,
            session_id=edit_session.id,
            session_version=edit_session.version,
            session_name=edit_session.name,
            clips=context_data.clips,
            metadata=context_data.metadata,
            user_instruction=request.user_instruction,
        )
        text_result = None
        try:
            if self._transport is not None:
                candidate = EditingDirectorSuggestionCandidate.model_validate(
                    await self._transport.generate(context)
                )
            else:
                text_result = await self._text_transport.generate_structured(
                    project=project,
                    actor=actor,
                    scope_type="edit_session",
                    scope_entity_id=edit_session.id,
                    request_key=request.request_key,
                    slot=ModelSlot.PLANNING_STORYBOARD,
                    task_name="editing_director_suggestion",
                    system_instruction=(
                        "Act as a film editor. Propose a bounded Timeline plan using only "
                        "reorder_clips, set_clip_duration, or set_clip_subtitle. Every target "
                        "must be an existing clip id. Preserve the user's explicit wording and "
                        "never request media regeneration."
                    ),
                    input_versions={
                        **({"creative_profile": autonomy_version} if proactive else {}),
                        "project": project.version,
                        "edit_session": edit_session.version,
                    },
                    intent_snapshot={"user_instruction": request.user_instruction},
                    context_payload={"timeline": context.model_dump(mode="json")},
                    output_type=EditingDirectorSuggestionCandidate,
                )
                candidate = text_result.value
        except ValidationError as exc:
            raise ValidationAppError(
                "editing Director suggestion failed structured validation",
                details={"code": "INVALID_EDITING_DIRECTOR_SUGGESTION", "errors": exc.errors()},
            ) from exc
        except (ValidationAppError, ConflictError):
            raise
        except Exception as exc:  # noqa: BLE001 - transport boundary is fail-closed
            raise ValidationAppError(
                f"editing Director suggestion failed: {exc}",
                details={"code": "EDITING_DIRECTOR_SUGGESTION_FAILED", "manual_ok": True},
            ) from exc

        try:
            if candidate.base_session_version != context.session_version:
                raise ValidationAppError(
                    "editing Director suggestion base version does not match the server session",
                    details={
                        "code": "INVALID_EDITING_DIRECTOR_BASE_VERSION",
                        "expected_version": context.session_version,
                        "actual_version": candidate.base_session_version,
                    },
                )
            _validate_plan_targets(
                candidate.plan,
                clip_ids=[clip.clip_id for clip in context.clips],
            )
        except ValidationAppError as exc:
            if text_result is not None:
                await self._text_transport.mark_failed(
                    text_result.turn,
                    reason=f"Editing plan validation failed: {exc}",
                    wait_reason="proposal_invalid",
                )
            raise

        # Read the persisted scalar directly instead of selecting the ORM row.
        # The latter can return the already-loaded identity-map instance and
        # therefore miss a version committed by a concurrent editor while the
        # transport was running.  Keep both identifiers in the predicate so a
        # session from another project can never satisfy this stale gate.
        latest_version = await self._session.scalar(
            select(EditSession.version).where(
                EditSession.project_id == project.id,
                EditSession.id == edit_session.id,
            )
        )
        if latest_version is None:
            if text_result is not None:
                await self._text_transport.mark_stale(
                    text_result.turn,
                    reason="EditSession was removed while the suggestion was in flight",
                )
            raise NotFoundError("edit session not found")
        if latest_version != context.session_version:
            if text_result is not None:
                await self._text_transport.mark_stale(
                    text_result.turn,
                    reason=(
                        f"EditSession changed during inference: expected "
                        f"{context.session_version}, current {latest_version}"
                    ),
                )
            raise ConflictError(
                "edit session changed while the suggestion was generated",
                details={
                    "code": "EDITING_SUGGESTION_STALE",
                    "expected_version": context.session_version,
                    "actual_version": latest_version,
                },
            )

        if text_result is not None and text_result.turn.proposal_id is not None:
            existing_proposal = await self._session.scalar(
                select(DirectorProposal).where(
                    DirectorProposal.id == text_result.turn.proposal_id,
                    DirectorProposal.project_id == project.id,
                    DirectorProposal.scope_type == "edit_session",
                    DirectorProposal.scope_entity_id == edit_session.id,
                )
            )
            existing_item = (
                await self._session.scalar(
                    select(DirectorProposalItem)
                    .where(
                        DirectorProposalItem.proposal_id == text_result.turn.proposal_id,
                        DirectorProposalItem.project_id == project.id,
                    )
                    .order_by(DirectorProposalItem.created_at, DirectorProposalItem.id)
                    .limit(1)
                )
                if existing_proposal is not None
                else None
            )
            if existing_proposal is None or existing_item is None:
                raise ConflictError(
                    "DirectorTurn proposal link is incomplete",
                    details={
                        "code": "EDITING_DIRECTOR_PROPOSAL_LINK_INVALID",
                        "turn_id": str(text_result.turn.id),
                    },
                )
            return self._result(
                candidate=candidate,
                proposal_id=existing_proposal.id,
                item_id=existing_item.id,
                evidence=text_result.evidence,
            )

        try:
            thread = await self._session.scalar(
                select(DirectorThread).where(
                    DirectorThread.project_id == project.id,
                    DirectorThread.scope_type == "project",
                    DirectorThread.scope_entity_id == project.id,
                )
            )
            if thread is None:
                thread = DirectorThread(
                    project_id=project.id,
                    scope_type="project",
                    scope_entity_id=project.id,
                    created_by=actor.id,
                )
                self._session.add(thread)
                await self._session.flush()

            proposal = DirectorProposal(
                project_id=project.id,
                thread_id=thread.id,
                scope_type="edit_session",
                scope_entity_id=edit_session.id,
                status="pending",
                created_by=actor.id,
            )
            self._session.add(proposal)
            await self._session.flush()
            item = DirectorProposalItem(
                proposal_id=proposal.id,
                project_id=project.id,
                command="edit_session.apply_timeline_plan",
                payload={
                    "edit_session_id": str(edit_session.id),
                    "plan": candidate.plan.model_dump(mode="json"),
                },
                expected_target_version=context.session_version,
                rationale=candidate.rationale,
                benefit=candidate.benefit,
                cost=candidate.cost,
                risk=candidate.risk,
                impact=candidate.impact,
                status="pending",
            )
            self._session.add(item)
            # Both ids are read from rows created in this invocation; never a
            # timestamp-based "latest" query.
            await self._session.flush()
        except Exception as exc:  # noqa: BLE001 - keep text evidence durable
            if text_result is not None:
                await self._record_persistence_failure(
                    turn_id=text_result.turn.id,
                    actor_id=actor.id,
                    workspace_id=project.workspace_id,
                    project_id=project.id,
                    exc=exc,
                )
            if isinstance(exc, AppError):
                raise
            raise ValidationAppError(
                "editing Director proposal persistence failed",
                details={
                    "code": "EDITING_DIRECTOR_PROPOSAL_PERSISTENCE_FAILED",
                    "manual_ok": True,
                    "turn_id": str(text_result.turn.id) if text_result is not None else None,
                },
            ) from exc

        if text_result is not None:
            await self._text_transport.mark_awaiting_user(
                text_result.turn,
                proposal_id=proposal.id,
            )
        else:
            await self._session.commit()
        return self._result(
            candidate=candidate,
            proposal_id=proposal.id,
            item_id=item.id,
            evidence=text_result.evidence if text_result is not None else None,
        )

    @staticmethod
    def _result(
        *,
        candidate: EditingDirectorSuggestionCandidate,
        proposal_id: UUID,
        item_id: UUID,
        evidence: DirectorInvocationEvidence | None,
    ) -> EditingDirectorSuggestionResult:
        result = EditingDirectorSuggestionResult(
            **candidate.model_dump(mode="python"),
            proposal_id=proposal_id,
            item_id=item_id,
            director_evidence=evidence,
        )
        result._candidate = candidate
        return result

    async def _record_persistence_failure(
        self,
        *,
        turn_id: UUID,
        actor_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        exc: Exception,
    ) -> None:
        await self._session.rollback()
        await set_rls_context(
            self._session,
            user_id=actor_id,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        turn = await self._session.get(DirectorTurn, turn_id)
        if turn is not None:
            await self._text_transport.mark_failed(
                turn,
                reason=f"Editing proposal persistence failed: {type(exc).__name__}: {exc}",
                wait_reason="proposal_invalid",
            )

    async def suggest_proactive(
        self,
        *,
        project_id: UUID,
        session_id: UUID,
        actor: User,
        request: EditingProactiveSuggestionRequest,
    ) -> EditingDirectorSuggestionResult:
        """Generate one server-driven editing suggestion without user input."""

        return await self.suggest(
            project_id=project_id,
            session_id=session_id,
            actor=actor,
            proactive=True,
            request=EditingDirectorSuggestionRequest(
                expected_session_version=request.expected_session_version,
                user_instruction="主动分析当前时间线节奏与转场，不要求用户输入",
                request_key=request.request_key,
            ),
        )


__all__ = [
    "EditingProactiveSuggestionRequest",
    "DeterministicEditingDirectorSuggestionTransport",
    "EditingDirectorClipContext",
    "EditingDirectorSuggestionCandidate",
    "EditingDirectorSuggestionContext",
    "EditingDirectorSuggestionResult",
    "EditingDirectorSuggestionRequest",
    "EditingDirectorSuggestionService",
    "EditingDirectorSuggestionTransport",
    "get_editing_director_suggestion_transport",
]
