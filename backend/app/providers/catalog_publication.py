"""Reviewed negative lifecycle events around the single immutable Catalog.

Events change publication permission, never manifest capability bytes or hashes.
Git retains the append history; events cannot make a contract executable.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_PUBLICATION_LOCK = 0x4472616D61436174


async def lock_catalog_publication(session: AsyncSession, *, shared: bool) -> None:
    """Coordinate Create with the maintenance writer without granting Catalog UPDATE."""
    if session.get_bind().dialect.name == "postgresql":
        function = "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
        await session.execute(text(f"SELECT {function}(:key)"), {"key": _PUBLICATION_LOCK})


class CatalogPublicationEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    provider_type: str
    protocol_profile: str
    model_id: str
    lifecycle: Literal["deprecated", "retired"]
    reviewed_at: datetime
    reviewed_by: str
    reason: str
    source_url: str
    source_locator: str
    captured_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_statement: str


@lru_cache(maxsize=1)
def publication_events() -> tuple[CatalogPublicationEvent, ...]:
    path = Path(__file__).with_name("catalog_publication_events.json")
    events = tuple(
        CatalogPublicationEvent.model_validate(item)
        for item in json.loads(path.read_text(encoding="utf-8"))
    )
    if len({event.event_id for event in events}) != len(events):
        raise ValueError("duplicate catalog publication event identity")
    return events


def effective_publication_lifecycle(
    provider_type: str, protocol_profile: str, model_id: str, stored_lifecycle: str
) -> str:
    matching = [
        event
        for event in publication_events()
        if (event.provider_type, event.protocol_profile, event.model_id)
        == (provider_type, protocol_profile, model_id)
    ]
    # Retirements are permanent and cannot be undone by a later static import.
    if stored_lifecycle == "retired" or any(event.lifecycle == "retired" for event in matching):
        return "retired"
    if matching and stored_lifecycle == "active":
        return "deprecated"
    return stored_lifecycle
