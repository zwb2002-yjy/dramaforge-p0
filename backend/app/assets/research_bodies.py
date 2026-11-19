"""Typed research bodies (schema_version 1) and their claim vocabulary.

The six kinds are distinct shapes, not free JSON: a summary is not a person, a timeline
is not an event. Claim keys name the parts a citation may support; unknown keys are
rejected so a citation cannot silently point at text that does not exist.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.assets.research_models import RESEARCH_KINDS
from app.shared.errors import ValidationAppError

SCHEMA_VERSION: Literal[1] = 1
MAX_CITATIONS = 200


class ResearchBodyBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = SCHEMA_VERSION


class SummaryBody(ResearchBodyBase):
    text: str = Field(min_length=1, max_length=20_000)
    coverage_note: str = Field(default="", max_length=2_000)


class NamedBody(ResearchBodyBase):
    """Person/place: a display name, optional aliases and a description."""

    display_name: str = Field(min_length=1, max_length=240)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    description: str = Field(default="", max_length=8_000)


class TimePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(default="", max_length=240)
    precision: Literal["exact", "year", "range", "unknown"] = "unknown"
    start: str | None = Field(default=None, max_length=40)
    end: str | None = Field(default=None, max_length=40)


class EventBody(ResearchBodyBase):
    description: str = Field(min_length=1, max_length=20_000)
    time: TimePoint | None = None
    related_person_ids: list[UUID] = Field(default_factory=list, max_length=100)
    related_place_ids: list[UUID] = Field(default_factory=list, max_length=100)


class TimelineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=240)
    time: TimePoint | None = None
    description: str = Field(default="", max_length=4_000)


class TimelineBody(ResearchBodyBase):
    items: list[TimelineItem] = Field(min_length=1, max_length=200)


class CulturalClueBody(ResearchBodyBase):
    theme: str = Field(min_length=1, max_length=240)
    interpretation: str = Field(min_length=1, max_length=20_000)
    related_material: str = Field(default="", max_length=4_000)


_BODIES: dict[str, type[ResearchBodyBase]] = {
    "summary": SummaryBody,
    "person": NamedBody,
    "place": NamedBody,
    "event": EventBody,
    "timeline": TimelineBody,
    "cultural_clue": CulturalClueBody,
}


def validate_body(kind: str, raw: object) -> dict[str, object]:
    """Validate one typed body and return its canonical JSON object."""
    if kind not in RESEARCH_KINDS:
        raise ValidationAppError("Unknown research kind")
    model = _BODIES[kind]
    try:
        parsed = model.model_validate(raw)
    except ValidationError as exc:
        raise ValidationAppError(
            "Research body does not match its kind",
            details={"code": "RESEARCH_BODY_INVALID", "errors": exc.errors(include_url=False)},
        ) from exc
    return parsed.model_dump(mode="json")


def content_hash(body: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def claim_keys(kind: str, body: dict[str, object]) -> set[str]:
    """Which claim keys a citation may name for this body."""
    keys = {"root"}
    if kind == "timeline":
        items = body.get("items")
        if isinstance(items, list):
            keys.update(f"item:{index}" for index in range(len(items)))
    elif kind == "event":
        keys.add("time")
    return keys


def summary_text(kind: str, body: dict[str, object]) -> str:
    """One-line human summary for read models; never a second editable body."""
    if kind == "summary":
        return str(body.get("text", ""))[:240]
    if kind in {"person", "place"}:
        return str(body.get("display_name", ""))
    if kind == "event":
        time = body.get("time") or {}
        label = time.get("label") if isinstance(time, dict) else ""
        description = str(body.get("description", ""))
        return f"{label} {description}".strip()[:240]
    if kind == "timeline":
        raw_items = body.get("items")
        labels = [
            str(item.get("label", ""))
            for item in (raw_items if isinstance(raw_items, list) else [])
            if isinstance(item, dict)
        ]
        return " → ".join(labels)[:240]
    if kind == "cultural_clue":
        return str(body.get("theme", ""))[:240]
    return ""


__all__ = [
    "MAX_CITATIONS",
    "SCHEMA_VERSION",
    "claim_keys",
    "content_hash",
    "summary_text",
    "validate_body",
]
