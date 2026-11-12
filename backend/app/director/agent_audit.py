"""Tool receipts on the existing DirectorToolCall journal.

Every method only flushes. The authenticated harness owns the transaction and
Turn lease. In particular PROPOSE preparation, domain proposal and completion
must commit together; interrupted receipts never authorize another execution.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.agent import AgentToolCall
from app.director.agent_tools import ToolSpec
from app.director.assistant_models import DirectorToolCall
from app.director.turn_models import DirectorTurn
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

MAX_RESULT_BYTES = 24576
MAX_ARGUMENT_BYTES = 65536
_TERMINAL = frozenset({"completed", "failed", "cancelled", "unknown_submission"})
_FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,79}\Z")
_TOOL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.:-]{0,159}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ERRORS: dict[str, tuple[str, bool, str]] = {
    "ToolNotFound": ("Tool is not available in this scope.", True, "correct_input"),
    "ToolInputInvalid": ("Arguments do not match the tool schema.", True, "correct_input"),
    "ToolPermissionDenied": ("Resource is unavailable in this scope.", True, "correct_input"),
    "ToolExecutionFailed": ("The tool could not be completed.", True, "transient"),
    "ToolTimeout": ("The read timed out.", True, "transient"),
    "ContextStale": ("A referenced object changed; refresh context.", False, "refresh_context"),
    "DeadlineExceeded": ("The turn deadline elapsed.", False, "none"),
    "ToolResultTooLarge": ("Narrow the requested result.", True, "correct_input"),
    "ToolResultInvalid": ("The tool returned an invalid result.", False, "none"),
    "PROPOSAL_INPUT_INVALID": ("Read the target and correct the proposal.", True, "correct_input"),
    "ToolTransactionRequired": ("A durable proposal transaction is required.", False, "none"),
    "TOOL_COMPLETION_UNCONFIRMED": (
        "The turn stopped before a tool receipt was saved; do not replay this call.",
        False,
        "none",
    ),
}


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def fingerprint(value: object) -> str:
    """Hash exact finite JSON; coercing UUIDs or arbitrary Python objects is forbidden."""
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def result_fingerprint(result: dict[str, object]) -> str:
    """Business receipt identity excludes nondeterministic timing and late observation."""
    return fingerprint(
        {
            key: value
            for key, value in result.items()
            if key not in {"result_hash", "latency_ms", "late_outcome"}
        }
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _safe_arguments(arguments: dict[str, object]) -> dict[str, object]:
    """Keep routing values; text and unexpected fields retain only a digest and size."""
    result: dict[str, object] = {}
    for index, (key, value) in enumerate(sorted(arguments.items())[:32]):
        safe_key = key if _FIELD_NAME.fullmatch(key) else f"redacted_field_{index}"
        if key in {"project_id", "scene_id", "shot_id", "asset_id"} and isinstance(value, str):
            try:
                result[safe_key] = str(UUID(value))
                continue
            except ValueError:
                pass
        if key in {"limit", "offset", "expected_version"} and type(value) is int:
            result[safe_key] = value
        else:
            result[safe_key] = {
                "redacted": True,
                "sha256": fingerprint(value),
                "byte_size": len(_json(value).encode("utf-8")),
            }
    if len(arguments) > 32:
        result["omitted_field_count"] = len(arguments) - 32
    return result


def _observed(value: object) -> dict[str, int]:
    if not isinstance(value, dict) or len(value) > 128:
        raise ValueError("Invalid observed versions")
    result: dict[str, int] = {}
    for key, version in value.items():
        if not isinstance(key, str) or type(version) is not int or version < 1:
            raise ValueError("Invalid observed version")
        kind, _, identity = key.partition(":")
        if kind not in {"project", "scene", "shot", "asset"}:
            raise ValueError("Invalid observed entity")
        result[f"{kind}:{UUID(identity)}"] = version
    return result


def _error(code: object) -> dict[str, object]:
    safe_code = code if isinstance(code, str) and code in _ERRORS else "ToolExecutionFailed"
    message, recoverable, retry_class = _ERRORS[safe_code]
    return {
        "code": safe_code,
        "message": message,
        "recoverable": recoverable,
        "retry_class": retry_class,
        "details": {},
    }


def _provenance(row: DirectorToolCall) -> dict[str, str]:
    previous = row.result.get("provenance")
    risk = previous.get("risk") if isinstance(previous, dict) else None
    return {
        "source": "dramaforge",
        "tool": row.tool_name if _TOOL_NAME.fullmatch(row.tool_name) else "unavailable_tool",
        "version": row.tool_version,
        "schema_hash": row.schema_hash,
        "risk": risk if isinstance(risk, str) and risk in {"READ", "PROPOSE"} else "UNKNOWN",
    }


def _normalize(
    row: DirectorToolCall,
    raw: dict[str, object],
    *,
    latency_ms: int,
    max_bytes: int = MAX_RESULT_BYTES,
) -> dict[str, object]:
    """One normalization/hash rule for success, safe errors and interruption."""
    if raw.get("call_id") != row.call_id:
        raise ConflictError("Tool result call identity changed")
    invalid = False
    try:
        encoded = _json(raw)
        if type(raw.get("ok")) is not bool:
            raise ValueError("Missing result status")
        observed = _observed(raw.get("observed_versions", {}))
    except (TypeError, ValueError, RecursionError):
        invalid = True
        encoded, observed = "", {}
    ok = raw.get("ok") is True and not invalid
    data = raw.get("data")
    if ok and not isinstance(data, dict):
        invalid, ok = True, False
    raw_error = raw.get("error")
    error_code = raw_error.get("code") if isinstance(raw_error, dict) else "ToolExecutionFailed"
    if invalid:
        error_code = "ToolResultInvalid"
    result: dict[str, object] = {
        "call_id": row.call_id,
        "ok": ok,
        "data": data if ok else None,
        "error": None if ok else _error(error_code),
        "observed_versions": observed,
        "provenance": _provenance(row),
        "truncated": raw.get("truncated") is True,
        "latency_ms": max(0, min(latency_ms, 86_400_000)),
    }
    # Include framing and hash in the limit; do not silently drop successful data.
    if len(encoded.encode("utf-8")) > max_bytes or len(_json(result).encode()) + 81 > max_bytes:
        result.update(
            {
                "ok": False,
                "data": None,
                "observed_versions": {},
                "truncated": True,
                "error": _error("ToolResultTooLarge"),
            }
        )
    result["result_hash"] = result_fingerprint(result)
    return cast("dict[str, object]", json.loads(_json(result)))


def public_summary(row: DirectorToolCall) -> dict[str, object]:
    """Public activity metadata, never raw arguments, tool data or untrusted errors."""
    result = row.result or {}
    raw_error = result.get("error")
    error = _error(raw_error.get("code")) if isinstance(raw_error, dict) else None
    try:
        observed = _observed(result.get("observed_versions", {}))
    except (TypeError, ValueError):
        observed = {}
    result_hash = result.get("result_hash")
    latency = result.get("latency_ms")
    summary: dict[str, object] = {
        "call_id": row.call_id,
        "step": row.step,
        "name": _provenance(row)["tool"],
        "version": row.tool_version,
        "status": row.status,
        "schema_hash": row.schema_hash,
        "args_hash": row.args_hash,
        "result_hash": result_hash
        if isinstance(result_hash, str) and _HASH.fullmatch(result_hash)
        else None,
        "ok": result.get("ok") is True,
        "error": error,
        "observed_versions": observed,
        "provenance": _provenance(row),
        "latency_ms": latency if type(latency) is int and 0 <= latency <= 86_400_000 else None,
        "created_at": row.created_at,
    }
    late = result.get("late_outcome")
    if isinstance(late, dict):
        late_hash = late.get("result_hash")
        summary["late_outcome"] = {
            "ok": late.get("ok") is True,
            "result_hash": late_hash
            if isinstance(late_hash, str) and _HASH.fullmatch(late_hash)
            else None,
        }
    return summary


@dataclass(frozen=True)
class ToolAdmission:
    row: DirectorToolCall
    should_execute: bool
    result: dict[str, object] | None


class AgentToolAudit:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _lock_turn(self, *, project_id: UUID, turn_id: UUID) -> DirectorTurn:
        turn = await self._session.scalar(
            select(DirectorTurn)
            .where(
                DirectorTurn.project_id == project_id,
                DirectorTurn.id == turn_id,
                DirectorTurn.turn_kind == "agent",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if turn is None:
            raise NotFoundError("Director Agent turn not found")
        return turn

    async def _row(
        self,
        *,
        project_id: UUID,
        turn_id: UUID,
        call_id: str,
    ) -> DirectorToolCall | None:
        row: DirectorToolCall | None = await self._session.scalar(
            select(DirectorToolCall)
            .where(
                DirectorToolCall.project_id == project_id,
                DirectorToolCall.turn_id == turn_id,
                DirectorToolCall.call_id == call_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return row

    async def prepare(
        self,
        *,
        project_id: UUID,
        turn_id: UUID,
        call: AgentToolCall,
        step: int,
        spec: ToolSpec | None,
    ) -> ToolAdmission:
        turn = await self._lock_turn(project_id=project_id, turn_id=turn_id)
        if type(step) is not int or step < 1:
            raise ValidationAppError("Invalid tool step")
        # Revalidate even model_construct values; no non-finite or oversized arguments.
        call = AgentToolCall.model_validate(call.model_dump())
        arguments: dict[str, object] = dict(call.arguments)
        if len(_json(arguments).encode()) > MAX_ARGUMENT_BYTES:
            raise ValidationAppError("Tool arguments exceed the size limit")
        if spec is not None and (
            spec.name != call.name
            or not _HASH.fullmatch(spec.schema_hash)
            or not spec.version
            or len(spec.version) > 80
        ):
            raise ValidationAppError("Tool specification does not match the call")
        version = spec.version if spec is not None else "unknown"
        schema_hash = spec.schema_hash if spec is not None else fingerprint({})
        args_hash = fingerprint(arguments)
        existing = await self._row(project_id=project_id, turn_id=turn_id, call_id=call.call_id)
        if existing is not None:
            identity = (
                existing.tool_name,
                existing.tool_version,
                existing.schema_hash,
                existing.args_hash,
            )
            if identity != (
                call.name,
                version,
                schema_hash,
                args_hash,
            ):
                raise ConflictError(
                    "Tool call identity was reused with different input",
                    details={"code": "TOOL_CALL_IDENTITY_CONFLICT"},
                )
            if existing.status not in _TERMINAL:
                await self._interrupt(existing, "failed")
            elif not existing.result.get("result_hash"):
                # Legacy incomplete receipts are fail-closed, never reconstructed as success.
                await self._interrupt(existing, existing.status)
            return ToolAdmission(existing, False, dict(existing.result))
        if turn.status != "thinking" or turn.stop_requested_at is not None:
            raise ConflictError("Director Agent turn no longer accepts tool calls")
        row = DirectorToolCall(
            project_id=project_id,
            turn_id=turn_id,
            step=step,
            call_id=call.call_id,
            tool_name=call.name,
            tool_version=version,
            schema_hash=schema_hash,
            args_hash=args_hash,
            arguments=_safe_arguments(arguments),
            status="running",
            result={
                "provenance": {"risk": spec.risk if spec is not None else "UNKNOWN"},
                "max_result_bytes": max(1024, min(spec.max_result_bytes, MAX_RESULT_BYTES))
                if spec is not None
                else MAX_RESULT_BYTES,
            },
        )
        self._session.add(row)
        await self._session.flush()
        return ToolAdmission(row, True, None)

    async def complete(
        self,
        *,
        project_id: UUID,
        turn_id: UUID,
        call_id: str,
        result: dict[str, object],
        latency_ms: int,
    ) -> dict[str, object]:
        await self._lock_turn(project_id=project_id, turn_id=turn_id)
        row = await self._row(project_id=project_id, turn_id=turn_id, call_id=call_id)
        if row is None:
            raise NotFoundError("Tool call receipt not found")
        if type(latency_ms) is not int or latency_ms < 0:
            raise ValidationAppError("Invalid tool latency")
        if result.get("call_id") != call_id:
            raise ConflictError("Tool result call identity changed")
        if row.status in _TERMINAL:
            # A late response cannot erase an acknowledged interruption or successful receipt.
            if not row.result.get("result_hash"):
                await self._interrupt(row, row.status)
            if row.status != "completed" and "late_outcome" not in row.result:
                late = _normalize(row, result, latency_ms=latency_ms)
                row.result = {
                    **row.result,
                    "late_outcome": {
                        "ok": late["ok"],
                        "result_hash": late["result_hash"],
                        "latency_ms": late["latency_ms"],
                    },
                }
                await self._session.flush()
            return dict(row.result)
        limit = row.result.get("max_result_bytes", MAX_RESULT_BYTES)
        row.result = _normalize(
            row,
            result,
            latency_ms=latency_ms,
            max_bytes=limit if type(limit) is int else MAX_RESULT_BYTES,
        )
        row.status = "completed"
        await self._session.flush()
        return dict(row.result)

    async def _interrupt(self, row: DirectorToolCall, status: str) -> None:
        elapsed = int((datetime.now(UTC) - _utc(row.created_at)).total_seconds() * 1000)
        row.result = _normalize(
            row,
            {
                "call_id": row.call_id,
                "ok": False,
                "error": {"code": "TOOL_COMPLETION_UNCONFIRMED"},
            },
            latency_ms=max(0, elapsed),
        )
        row.status = status
        await self._session.flush()

    async def settle(
        self,
        *,
        project_id: UUID,
        turn_id: UUID,
        status: Literal["failed", "cancelled"] = "failed",
    ) -> int:
        await self._lock_turn(project_id=project_id, turn_id=turn_id)
        if status not in {"failed", "cancelled"}:
            raise ValidationAppError("Invalid tool interruption status")
        rows = list(
            await self._session.scalars(
                select(DirectorToolCall)
                .where(
                    DirectorToolCall.project_id == project_id,
                    DirectorToolCall.turn_id == turn_id,
                    DirectorToolCall.status.in_(("pending", "running")),
                )
                .order_by(DirectorToolCall.step)
                .with_for_update()
            )
        )
        for row in rows:
            await self._interrupt(row, status)
        return len(rows)
