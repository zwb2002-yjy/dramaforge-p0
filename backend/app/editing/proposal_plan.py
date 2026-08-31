"""Typed, proposal-only edit-session timeline operations.

The plan is intentionally smaller than the persisted timeline document.  It
can reorder existing clip ids and change an existing clip's duration, but it
cannot carry replacement JSON, paths, provider/runtime instructions, or a
production-lineage payload.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

_FORBIDDEN_FIELDS = frozenset(
    {
        "artifact",
        "artifact_id",
        "artifact_ids",
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
_FORBIDDEN_PREFIXES = (
    "artifact_",
    "execution_",
    "node_run_",
    "provider_",
    "raw_sql_",
    "runtime_",
    "sql_",
    "worker_",
)


def _normalize_key(key: object) -> str:
    value = str(key).strip().replace("-", "_").replace(" ", "_")
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"_+", "_", value).lower()


def _reject_forbidden_fields(value: object, *, path: str = "plan") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = _normalize_key(key)
            if normalized in _FORBIDDEN_FIELDS or normalized.startswith(_FORBIDDEN_PREFIXES):
                raise ValueError(f"{path} contains forbidden field: {key}")
            _reject_forbidden_fields(nested, path=f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            _reject_forbidden_fields(nested, path=f"{path}[{index}]")


def _normalize_operation_tag(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    if "operation" in value:
        return value
    aliases = ("kind", "type", "op")
    alias = next((key for key in aliases if key in value), None)
    if alias is None:
        return value
    normalized = dict(value)
    normalized.pop(alias, None)
    normalized["operation"] = value[alias]
    return normalized


class _StrictPlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReorderClipsOperation(_StrictPlanModel):
    operation: Literal["reorder_clips"]
    clip_ids: list[str] = Field(min_length=1, max_length=1000)

    @field_validator("clip_ids")
    @classmethod
    def validate_clip_ids(cls, value: list[str]) -> list[str]:
        if any(not clip_id.strip() for clip_id in value):
            raise ValueError("clip_ids must contain non-empty ids")
        if len(set(value)) != len(value):
            raise ValueError("reorder_clips clip_ids must be unique")
        return value

    @model_validator(mode="before")
    @classmethod
    def normalize_operation(cls, value: object) -> object:
        return _normalize_operation_tag(value)


class SetClipDurationOperation(_StrictPlanModel):
    operation: Literal["set_clip_duration"]
    clip_id: str = Field(min_length=1, max_length=200)
    duration_seconds: float = Field(strict=True, ge=0, allow_inf_nan=False)

    @field_validator("clip_id")
    @classmethod
    def validate_clip_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("clip_id must not be blank")
        return value

    @field_validator("duration_seconds")
    @classmethod
    def validate_finite_duration(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("duration_seconds must be finite")
        return value

    @model_validator(mode="before")
    @classmethod
    def normalize_operation(cls, value: object) -> object:
        return _normalize_operation_tag(value)


EditSessionTimelineOperation = Annotated[
    ReorderClipsOperation | SetClipDurationOperation,
    Field(discriminator="operation"),
]


class EditSessionTimelinePlan(_StrictPlanModel):
    """Allow-listed edit operations applied against one session version."""

    operations: list[EditSessionTimelineOperation] = Field(min_length=1, max_length=100)

    @model_validator(mode="before")
    @classmethod
    def reject_untrusted_fields(cls, value: object) -> object:
        _reject_forbidden_fields(value)
        if not isinstance(value, Mapping):
            return value
        operations = value.get("operations")
        if not isinstance(operations, list):
            return value
        return {
            **value,
            "operations": [_normalize_operation_tag(operation) for operation in operations],
        }


class EditSessionTimelineCommand(_StrictPlanModel):
    """Payload carried by the canonical proposal command."""

    edit_session_id: UUID
    plan: EditSessionTimelinePlan

    @model_validator(mode="before")
    @classmethod
    def normalize_session_id(cls, value: object) -> object:
        _reject_forbidden_fields(value)
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        if "edit_session_id" not in value and "session_id" in value:
            normalized.pop("session_id", None)
            normalized["edit_session_id"] = value["session_id"]
        if "plan" not in value:
            if "timeline_plan" in value:
                normalized.pop("timeline_plan", None)
                normalized["plan"] = value["timeline_plan"]
            elif "operations" in value:
                normalized.pop("operations", None)
                normalized["plan"] = {"operations": value["operations"]}
        return normalized


def validate_edit_session_timeline_command(
    payload: Mapping[str, object],
) -> EditSessionTimelineCommand:
    """Validate untrusted proposal JSON into the narrow typed command shape."""

    try:
        return EditSessionTimelineCommand.model_validate(payload)
    except ValidationError:
        raise


__all__ = [
    "EditSessionTimelineCommand",
    "EditSessionTimelineOperation",
    "EditSessionTimelinePlan",
    "ReorderClipsOperation",
    "SetClipDurationOperation",
    "validate_edit_session_timeline_command",
]
