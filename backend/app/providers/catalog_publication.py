"""Reviewed negative publication permissions around the single immutable Catalog.

Events change publication permission, never manifest capability bytes or hashes.
Git retains the append history; events cannot make a contract executable.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
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
    lifecycle: Literal["deprecated", "retired"] | None = None
    new_create_blocker: Literal["MODEL_OFFICIAL_EVIDENCE_GAP"] | None = None
    model_revision: str | None = None
    contract_manifest_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    audit_inventory_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reviewed_at: datetime
    reviewed_by: str
    reason: str
    source_url: str | None = None
    source_locator: str | None = None
    captured_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reviewed_statement: str | None = None

    @model_validator(mode="after")
    def validate_event(self) -> CatalogPublicationEvent:
        if self.lifecycle is not None:
            if self.new_create_blocker is not None or not all(
                (
                    self.source_url,
                    self.source_locator,
                    self.captured_content_sha256,
                    self.reviewed_statement,
                )
            ):
                raise ValueError(
                    "lifecycle event needs its official retirement/deprecation evidence"
                )
        elif not all(
            (
                self.new_create_blocker,
                self.model_revision,
                self.contract_manifest_hash,
                self.audit_inventory_sha256,
            )
        ):
            raise ValueError("Create restriction needs an exact frozen revision/hash and audit")
        return self


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
        and event.lifecycle is not None
    ]
    # Retirements are permanent and cannot be undone by a later static import.
    if stored_lifecycle == "retired" or any(event.lifecycle == "retired" for event in matching):
        return "retired"
    if matching and stored_lifecycle == "active":
        return "deprecated"
    return stored_lifecycle


def catalog_new_create_blocker(
    provider_type: str,
    protocol_profile: str,
    model_id: str,
    model_revision: str,
    contract_manifest_hash: str,
    *,
    schema_version: str = "1",
    lifecycle: str = "active",
    catalog_source: str = "official_static",
) -> str | None:
    """Publication and schema readiness only; never consulted for historical resume."""
    if schema_version == "2":
        return "MODEL_CONTRACT_NOT_TESTED"
    if schema_version != "1":
        return "MODEL_CONTRACT_SCHEMA_UNSUPPORTED"
    if (
        effective_publication_lifecycle(provider_type, protocol_profile, model_id, lifecycle)
        != "active"
    ):
        return "MODEL_LIFECYCLE_INACTIVE"
    if catalog_source == "protocol_contract":
        return "DYNAMIC_MODEL_CAPABILITY_UNVERIFIED"
    matching = [
        event
        for event in publication_events()
        if (
            event.provider_type,
            event.protocol_profile,
            event.model_id,
            event.model_revision,
        )
        == (provider_type, protocol_profile, model_id, model_revision)
        and event.new_create_blocker is not None
    ]
    if matching and not any(
        event.contract_manifest_hash == contract_manifest_hash for event in matching
    ):
        return "CATALOG_MANIFEST_HASH_MISMATCH"
    return next((event.new_create_blocker for event in matching), None)
