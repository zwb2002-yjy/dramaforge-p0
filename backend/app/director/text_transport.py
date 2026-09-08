"""Structured, auditable text-model bridge for bounded Director turns."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.director.turn_models import DirectorTurn
from app.director.turn_service import ACTIVE_TURN_STATUSES, DirectorTurnService
from app.providers.capabilities import Capability
from app.providers.contracts.common import ExecutionContext, GenerationStatus, ProviderCreateResult
from app.providers.contracts.text import TextGenerateRequest, TextMessage
from app.providers.model_profiles.resolver import ModelBindingResolver
from app.providers.model_profiles.slots import ModelSlot
from app.providers.registry import ModelRegistry
from app.providers.router import CapabilityRouter
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError, ValidationAppError


class DirectorInvocationEvidence(BaseModel):
    """Safe identity returned with a proposal; no credential or raw wire data."""

    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    request_key: str
    context_hash: str = Field(min_length=64, max_length=64)
    output_hash: str = Field(min_length=64, max_length=64)
    slot: ModelSlot
    model_id: str
    model_binding_ref: str
    actual_model: str | None = None
    transport_status: Literal["succeeded"] = "succeeded"
    token_usage: dict[str, object] = Field(default_factory=dict)
    reported_cost: str | None = None
    cost_status: Literal["unknown", "reported"]
    currency: str = "USD"
    schema_repair_count: int = Field(ge=0, le=1)


@dataclass(frozen=True)
class StructuredDirectorTextResult[OutputT: BaseModel]:
    value: OutputT
    turn: DirectorTurn
    evidence: DirectorInvocationEvidence


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _safe_json(value: object) -> object:
    """Coerce allowlisted provider metadata into JSON values without secrets."""

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe_json(nested) for key, nested in value.items()}
    if isinstance(value, list | tuple):
        return [_safe_json(nested) for nested in value]
    return str(value)


def _error_code(exc: Exception) -> str:
    details = getattr(exc, "details", None)
    if isinstance(details, dict) and details.get("code"):
        return str(details["code"])
    return type(exc).__name__


def _bounded_error(exc: Exception) -> str:
    return f"{_error_code(exc)}: {str(exc)}"[:2000]


def _model_binding_ref(*, slot: ModelSlot, resolved: object) -> str:
    profile_id = getattr(resolved, "profile_id", None)
    profile_version = getattr(resolved, "profile_version", None)
    model_id = str(getattr(resolved, "model_id", ""))
    if profile_id is not None:
        return f"production-model-profile:{profile_id}@{profile_version}:{slot}"
    return f"{getattr(resolved, 'source', 'unknown')}:{model_id}:{slot}"


def _response_format(output_type: type[BaseModel], task_name: str) -> dict[str, object]:
    schema_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", task_name).strip("_")[:64]
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name or "director_result",
            "strict": True,
            "schema": output_type.model_json_schema(mode="validation"),
        },
    }


def _parse_output[OutputT: BaseModel](text: str, output_type: type[OutputT]) -> OutputT:
    value = json.loads(text)
    return output_type.model_validate(value)


def _aggregate_usage(attempts: list[dict[str, object]]) -> dict[str, object]:
    totals: dict[str, object] = {}
    for attempt in attempts:
        usage = attempt.get("usage")
        if not isinstance(usage, dict):
            continue
        for key, value in usage.items():
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            current = totals.get(str(key), 0)
            totals[str(key)] = (current if isinstance(current, int | float) else 0) + value
    return totals


def _reported_cost(attempts: list[dict[str, object]]) -> tuple[Decimal | None, str]:
    if not attempts:
        return None, "unknown"
    costs: list[Decimal] = []
    for attempt in attempts:
        raw = attempt.get("provider_cost")
        if raw is None:
            return None, "unknown"
        try:
            costs.append(Decimal(str(raw)))
        except InvalidOperation:
            return None, "unknown"
    return sum(costs, start=Decimal("0")), "reported"


def _evidence_reported_cost(turn: DirectorTurn) -> str | None:
    raw_attempts = (turn.response_summary or {}).get("attempts")
    attempts = [dict(item) for item in raw_attempts if isinstance(item, dict)] if isinstance(
        raw_attempts, list
    ) else []
    amount, status = _reported_cost(attempts)
    if status == "reported" and amount is not None:
        return str(amount)
    return str(turn.provider_cost) if turn.provider_cost is not None else None


class DirectorTextTransport:
    """Resolve one profile model, dispatch at most twice, and persist the turn."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: ModelRegistry | None = None,
    ) -> None:
        self._session = session
        self._turns = DirectorTurnService(session)
        if registry is None:
            from app.providers.model_profiles.service import default_model_registry

            registry = default_model_registry()
        self._registry = registry

    async def generate_structured[OutputT: BaseModel](
        self,
        *,
        project: Project,
        actor: User,
        scope_type: str,
        scope_entity_id: UUID,
        request_key: str,
        slot: ModelSlot,
        task_name: str,
        system_instruction: str,
        input_versions: dict[str, object],
        intent_snapshot: dict[str, object],
        context_payload: dict[str, object],
        output_type: type[OutputT],
    ) -> StructuredDirectorTextResult[OutputT]:
        context_snapshot = {
            "workspace_id": str(project.workspace_id),
            "project_id": str(project.id),
            "scope_type": scope_type,
            "scope_entity_id": str(scope_entity_id),
            "slot": str(slot),
            "input_versions": input_versions,
            "intent": intent_snapshot,
            "context": context_payload,
        }
        turn, created = await self._turns.create_or_get(
            project=project,
            actor=actor,
            scope_type=scope_type,
            scope_entity_id=scope_entity_id,
            request_key=request_key,
            context_snapshot=context_snapshot,
            input_versions=input_versions,
            intent_snapshot=intent_snapshot,
            max_steps=4,
        )
        context_fingerprint = turn.context_hash
        if not created:
            return self._restore_existing(
                turn=turn,
                context_hash=context_fingerprint,
                output_type=output_type,
            )
        await self._turns.claim(
            project_id=project.id,
            turn_id=turn.id,
            expected_revision=turn.revision,
        )

        try:
            resolved = await ModelBindingResolver(self._session, self._registry).resolve(
                workspace_id=project.workspace_id,
                project_id=project.id,
                slot=slot,
                capability=Capability.TEXT_GENERATE,
            )
            registered = self._registry.get(resolved.model_id)
            binding_ref = _model_binding_ref(slot=slot, resolved=resolved)
            backend = registered.manifest.metadata.get("backend")
            model_resolution: dict[str, object] = {
                "slot": str(slot),
                "source": resolved.source,
                "model_id": resolved.model_id,
                "profile_id": str(resolved.profile_id) if resolved.profile_id else None,
                "profile_version": resolved.profile_version,
                "model_binding_ref": binding_ref,
                "provider_id": registered.adapter.provider_id,
                "manifest_version": registered.manifest.manifest_version,
                "backend": _safe_json(backend) if isinstance(backend, dict) else {},
            }
        except Exception as exc:  # noqa: BLE001 - persist explicit resolution failure
            await self._turns.compare_and_set(
                turn=turn,
                expected_statuses=("thinking",),
                target_status="failed",
                updates={
                    "model_resolution": {"slot": str(slot), "error_code": _error_code(exc)},
                    "transport_status": "failed",
                    "request_summary": {
                        "task": task_name,
                        "context_hash": context_fingerprint,
                        "max_steps": 4,
                    },
                    "response_summary": {"error_code": _error_code(exc)},
                    "wait_reason": "model_unavailable",
                    "last_error": _bounded_error(exc),
                },
            )
            await self._commit_and_restore_scope(turn)
            raise ValidationAppError(
                "Director text model is not configured or unavailable",
                details={
                    "code": "DIRECTOR_TEXT_MODEL_UNAVAILABLE",
                    "model_error_code": _error_code(exc),
                    "manual_ok": True,
                    "turn_id": str(turn.id),
                },
            ) from exc

        await self._turns.compare_and_set(
            turn=turn,
            expected_statuses=("thinking",),
            target_status="thinking",
            updates={
                "model_resolution": model_resolution,
                "transport_status": "submission_started",
                "request_summary": {
                    "task": task_name,
                    "slot": str(slot),
                    "context_hash": context_fingerprint,
                    "schema": output_type.__name__,
                    "max_steps": 4,
                },
                "wait_reason": "text_model",
            },
        )
        await self._commit_and_restore_scope(turn)

        schema = output_type.model_json_schema(mode="validation")
        primary_request = TextGenerateRequest(
            messages=[
                TextMessage(
                    role="user",
                    content=canonical_json(
                        {
                            "task": task_name,
                            "context": context_snapshot,
                            "required_output_schema": schema,
                        }
                    ),
                )
            ],
            system=(
                f"{system_instruction}\n"
                "Return exactly one JSON object matching the supplied schema. "
                "Never include SQL, code, credentials, URLs, provider/runtime fields, "
                "media execution commands, or prose outside the JSON object."
            ),
            temperature=0.2,
            max_tokens=4096,
            response_format=_response_format(output_type, task_name),
            native_options=dict(resolved.native_options),
        )
        attempts: list[dict[str, object]] = []
        schema_repair_count = 0
        try:
            first = await self._dispatch(
                request=primary_request,
                project=project,
                actor=actor,
                turn=turn,
                model_id=resolved.model_id,
            )
            first_text = self._record_attempt(attempts, result=first, purpose="primary")
            self._require_success(first, turn=turn, attempts=attempts)
            try:
                value = _parse_output(first_text, output_type)
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as first_error:
                schema_repair_count = 1
                repair_request = TextGenerateRequest(
                    messages=[
                        TextMessage(
                            role="user",
                            content=canonical_json(
                                {
                                    "task": task_name,
                                    "original_context": context_snapshot,
                                    "invalid_output": first_text[:20000],
                                    "validation_error": str(first_error)[:4000],
                                    "required_output_schema": schema,
                                }
                            ),
                        )
                    ],
                    system=(
                        "Repair the invalid model output once. Return exactly one JSON object "
                        "matching the supplied schema, with no prose and no execution fields."
                    ),
                    temperature=0,
                    max_tokens=4096,
                    response_format=_response_format(output_type, f"{task_name}_repair"),
                    native_options=dict(resolved.native_options),
                )
                repaired = await self._dispatch(
                    request=repair_request,
                    project=project,
                    actor=actor,
                    turn=turn,
                    model_id=resolved.model_id,
                )
                repaired_text = self._record_attempt(
                    attempts, result=repaired, purpose="schema_repair"
                )
                self._require_success(repaired, turn=turn, attempts=attempts)
                try:
                    value = _parse_output(repaired_text, output_type)
                except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
                    raise ValidationAppError(
                        "Director text output failed structured validation after one repair",
                        details={"code": "INVALID_DIRECTOR_TEXT_OUTPUT", "manual_ok": True},
                    ) from exc
        except Exception as exc:  # noqa: BLE001 - turn evidence must survive every failure
            await self._fail_turn(
                turn=turn,
                attempts=attempts,
                exc=exc,
                schema_repair_count=schema_repair_count,
            )
            code = _error_code(exc)
            if isinstance(exc, ValidationAppError) and code in {
                "DIRECTOR_TEXT_CALL_FAILED",
                "DIRECTOR_TEXT_CALL_UNKNOWN",
                "INVALID_DIRECTOR_TEXT_OUTPUT",
            }:
                exc.details.setdefault("turn_id", str(turn.id))
                raise
            if code.startswith("MODEL_PROFILE_"):
                raise ValidationAppError(
                    "Director text model is not configured or unavailable",
                    details={
                        "code": "DIRECTOR_TEXT_MODEL_UNAVAILABLE",
                        "model_error_code": code,
                        "manual_ok": True,
                        "turn_id": str(turn.id),
                    },
                ) from exc
            raise ValidationAppError(
                "Director text generation failed",
                details={
                    "code": "DIRECTOR_TEXT_CALL_FAILED",
                    "transport_error_code": code,
                    "manual_ok": True,
                    "turn_id": str(turn.id),
                },
            ) from exc

        output_snapshot = value.model_dump(mode="json")
        output_fingerprint = content_hash(output_snapshot)
        provider_cost, cost_status = _reported_cost(attempts)
        actual_model = next(
            (
                str(attempt["actual_model"])
                for attempt in reversed(attempts)
                if attempt.get("actual_model")
            ),
            None,
        )
        request_id = next(
            (
                str(attempt["provider_request_id"])
                for attempt in attempts
                if attempt.get("provider_request_id")
            ),
            None,
        )
        evidence_patch: dict[str, object] = {
            "transport_record_id": request_id,
            "transport_status": "succeeded",
            "response_summary": {
                "output_hash": output_fingerprint,
                "actual_model": actual_model,
                "attempts": attempts,
            },
            "token_usage": _aggregate_usage(attempts),
            "provider_cost": provider_cost,
            "cost_status": cost_status,
            "output_hash": output_fingerprint,
            "output_snapshot": output_snapshot,
            "schema_repair_count": schema_repair_count,
            "wait_reason": "version_recheck",
        }
        try:
            await self._turns.compare_and_set(
                turn=turn,
                expected_statuses=("thinking",),
                target_status="thinking",
                updates=evidence_patch,
            )
        except ConflictError:
            # A concurrent user stop/manual edit wins the decision state, but
            # the already-returned model evidence is still recorded without
            # reviving the turn or applying its output.
            if turn.status not in {"cancelled", "stale"}:
                raise
            terminal_status = turn.status
            evidence_patch.pop("wait_reason", None)
            await self._turns.compare_and_set(
                turn=turn,
                expected_statuses=(terminal_status,),
                target_status=terminal_status,
                updates=evidence_patch,
            )
            await self._commit_and_restore_scope(turn)
            raise ConflictError(
                "Director turn stopped while the text model was running",
                details={
                    "code": "DIRECTOR_TURN_STOPPED",
                    "turn_id": str(turn.id),
                    "status": terminal_status,
                },
            ) from None
        await self._commit_and_restore_scope(turn)
        evidence = self._evidence(turn)
        return StructuredDirectorTextResult(value=value, turn=turn, evidence=evidence)

    async def mark_awaiting_user(
        self,
        turn: DirectorTurn,
        *,
        proposal_id: UUID | None = None,
    ) -> None:
        if turn.status == "awaiting_user" and (
            proposal_id is None or proposal_id == turn.proposal_id
        ):
            return
        updates: dict[str, object] = {"wait_reason": "proposal_decision"}
        if proposal_id is not None:
            updates["proposal_id"] = proposal_id
        await self._turns.compare_and_set(
            turn=turn,
            expected_statuses=("thinking",),
            target_status="awaiting_user",
            updates=updates,
        )
        await self._commit_and_restore_scope(turn)

    async def mark_stale(self, turn: DirectorTurn, *, reason: str) -> None:
        if turn.status == "stale":
            return
        if turn.status not in ACTIVE_TURN_STATUSES:
            return
        await self._turns.compare_and_set(
            turn=turn,
            expected_statuses=tuple(ACTIVE_TURN_STATUSES),
            target_status="stale",
            updates={"wait_reason": "context_changed", "last_error": reason},
        )
        await self._commit_and_restore_scope(turn)

    async def mark_failed(
        self,
        turn: DirectorTurn,
        *,
        reason: str,
        wait_reason: str = "output_invalid",
    ) -> None:
        if turn.status not in ACTIVE_TURN_STATUSES:
            return
        await self._turns.compare_and_set(
            turn=turn,
            expected_statuses=tuple(ACTIVE_TURN_STATUSES),
            target_status="failed",
            updates={"wait_reason": wait_reason, "last_error": reason},
        )
        await self._commit_and_restore_scope(turn)

    async def _dispatch(
        self,
        *,
        request: TextGenerateRequest,
        project: Project,
        actor: User,
        turn: DirectorTurn,
        model_id: str,
    ) -> ProviderCreateResult:
        return await CapabilityRouter(registry=self._registry).create(
            capability=Capability.TEXT_GENERATE,
            request=request,
            model_id=model_id,
            context=ExecutionContext(
                trace_id=str(turn.id),
                operation_id=f"director-turn:{turn.id}",
                project_id=str(project.id),
                workspace_id=str(project.workspace_id),
                user_id=str(actor.id),
                idempotency_key=turn.request_key,
            ),
        )

    async def _commit_and_restore_scope(self, turn: DirectorTurn) -> None:
        """Commit durable evidence, then restore transaction-local PostgreSQL RLS."""

        await self._session.commit()
        await set_rls_context(
            self._session,
            user_id=turn.actor_id,
            workspace_id=turn.workspace_id,
            project_id=turn.project_id,
        )

    @staticmethod
    def _record_attempt(
        attempts: list[dict[str, object]],
        *,
        result: ProviderCreateResult,
        purpose: str,
    ) -> str:
        metadata = result.provider_metadata
        text = str(metadata.get("text") or "")
        provider_cost = metadata.get("litellm_response_cost")
        if provider_cost is None:
            provider_cost = metadata.get("litellm_response_cost_original")
        attempt: dict[str, object] = {
            "attempt_no": len(attempts) + 1,
            "purpose": purpose,
            "status": str(result.status),
            "provider_request_id": metadata.get("request_id"),
            "actual_model": metadata.get("litellm_model_name") or metadata.get("model"),
            "usage": _safe_json(metadata.get("usage") or {}),
            "provider_cost": _safe_json(provider_cost),
            "output_text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "error_code": metadata.get("error_code"),
        }
        attempts.append(attempt)
        return text

    @staticmethod
    def _require_success(
        result: ProviderCreateResult,
        *,
        turn: DirectorTurn,
        attempts: list[dict[str, object]],
    ) -> None:
        if result.status == GenerationStatus.SUCCEEDED:
            return
        metadata = result.provider_metadata
        if result.status == GenerationStatus.SUBMIT_UNKNOWN:
            raise ValidationAppError(
                "Director text submission result is unknown; no automatic retry was made",
                details={
                    "code": "DIRECTOR_TEXT_CALL_UNKNOWN",
                    "manual_ok": True,
                    "turn_id": str(turn.id),
                    "attempts": len(attempts),
                },
            )
        raise ValidationAppError(
            "Director text model call failed",
            details={
                "code": "DIRECTOR_TEXT_CALL_FAILED",
                "provider_error_code": str(metadata.get("error_code") or "unknown"),
                "manual_ok": True,
                "turn_id": str(turn.id),
                "attempts": len(attempts),
            },
        )

    async def _fail_turn(
        self,
        *,
        turn: DirectorTurn,
        attempts: list[dict[str, object]],
        exc: Exception,
        schema_repair_count: int,
    ) -> None:
        provider_cost, cost_status = _reported_cost(attempts)
        transport_status = (
            "unknown_submission" if _error_code(exc) == "DIRECTOR_TEXT_CALL_UNKNOWN" else "failed"
        )
        evidence_patch: dict[str, object] = {
            "transport_status": transport_status,
            "response_summary": {
                "error_code": _error_code(exc),
                "attempts": attempts,
            },
            "token_usage": _aggregate_usage(attempts),
            "provider_cost": provider_cost,
            "cost_status": cost_status,
            "schema_repair_count": schema_repair_count,
        }
        if turn.status in {"cancelled", "stale"}:
            await self._turns.compare_and_set(
                turn=turn,
                expected_statuses=(turn.status,),
                target_status=turn.status,
                updates=evidence_patch,
            )
        else:
            await self._turns.compare_and_set(
                turn=turn,
                expected_statuses=("thinking",),
                target_status="failed",
                updates={
                    **evidence_patch,
                    "wait_reason": (
                        "model_result_unknown"
                        if transport_status == "unknown_submission"
                        else "model_failed"
                    ),
                    "last_error": _bounded_error(exc),
                },
            )
        await self._commit_and_restore_scope(turn)

    def _restore_existing[OutputT: BaseModel](
        self,
        *,
        turn: DirectorTurn,
        context_hash: str,
        output_type: type[OutputT],
    ) -> StructuredDirectorTextResult[OutputT]:
        if turn.context_hash != context_hash:
            raise ConflictError(
                "Director request key was already used for different context",
                details={"code": "DIRECTOR_REQUEST_KEY_REUSED", "turn_id": str(turn.id)},
            )
        if turn.status == "stale":
            raise ConflictError(
                "Director turn is stale because its source context changed",
                details={"code": "DIRECTOR_TURN_STALE", "turn_id": str(turn.id)},
            )
        if turn.transport_status != "succeeded" or not turn.output_hash:
            raise ConflictError(
                "Director request already exists without a reusable completed result",
                details={
                    "code": "DIRECTOR_TURN_NOT_REUSABLE",
                    "turn_id": str(turn.id),
                    "status": turn.status,
                    "transport_status": turn.transport_status,
                },
            )
        try:
            value = output_type.model_validate(turn.output_snapshot)
        except ValidationError as exc:
            raise ConflictError(
                "Stored Director result no longer matches its schema",
                details={"code": "DIRECTOR_TURN_RESULT_INVALID", "turn_id": str(turn.id)},
            ) from exc
        return StructuredDirectorTextResult(
            value=value,
            turn=turn,
            evidence=self._evidence(turn),
        )

    @staticmethod
    def _evidence(turn: DirectorTurn) -> DirectorInvocationEvidence:
        resolution = turn.model_resolution
        actual_model = turn.response_summary.get("actual_model")
        return DirectorInvocationEvidence(
            turn_id=turn.id,
            request_key=turn.request_key,
            context_hash=turn.context_hash,
            output_hash=str(turn.output_hash),
            slot=ModelSlot(str(resolution["slot"])),
            model_id=str(resolution["model_id"]),
            model_binding_ref=str(resolution["model_binding_ref"]),
            actual_model=str(actual_model) if actual_model else None,
            token_usage=dict(turn.token_usage or {}),
            reported_cost=_evidence_reported_cost(turn),
            cost_status=turn.cost_status,  # type: ignore[arg-type]
            currency=turn.currency,
            schema_repair_count=turn.schema_repair_count,
        )


__all__ = [
    "DirectorInvocationEvidence",
    "DirectorTextTransport",
    "StructuredDirectorTextResult",
    "canonical_json",
    "content_hash",
]
