"""Maintenance publishing of immutable protocol and handler revision facts.

Runtime resolution does not use these rows until exact handler mappings and
recovery preflight are complete. A caller must use a privileged maintenance
session; the application role has read-only access to the history tables.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.model_system_models import ProtocolContractRevision, RuntimeHandlerRevision
from app.providers.transport import TransportProfile


class ProtocolContractContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_profile: str = Field(min_length=1, max_length=80)
    operation_kind: Literal["image.generate", "video.generate"]
    request_schema_version: str = Field(min_length=1, max_length=80)
    transport: TransportProfile

    def canonical_body(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def protocol_hash(self) -> str:
        encoded = json.dumps(self.canonical_body(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def publish_protocol_contract_revision(
    session: AsyncSession,
    *,
    protocol_contract_id: UUID,
    protocol_revision: int,
    content: ProtocolContractContent,
) -> ProtocolContractRevision:
    if protocol_revision <= 0:
        raise ValueError("protocol revision must be positive")
    # Pydantic model_copy(update=...) skips validation; recheck before persistence.
    content = ProtocolContractContent.model_validate(content.model_dump(mode="json"))
    row = ProtocolContractRevision(
        protocol_contract_id=protocol_contract_id,
        protocol_revision=protocol_revision,
        protocol_hash=content.protocol_hash(),
        protocol_profile=content.protocol_profile,
        contract_json=content.canonical_body(),
    )
    session.add(row)
    await session.flush()
    return row


async def publish_runtime_handler_revision(
    session: AsyncSession,
    *,
    runtime_handler_id: UUID,
    handler_revision: int,
    handler_key: str,
    implementation_digest: str,
) -> RuntimeHandlerRevision:
    if handler_revision <= 0 or not handler_key.strip() or len(handler_key) > 120:
        raise ValueError("positive handler revision and non-empty key are required")
    if len(implementation_digest) != 64 or any(
        character not in "0123456789abcdef" for character in implementation_digest
    ):
        raise ValueError("implementation digest must be a lowercase SHA-256 hex string")
    row = RuntimeHandlerRevision(
        runtime_handler_id=runtime_handler_id,
        handler_revision=handler_revision,
        handler_key=handler_key.strip(),
        implementation_digest=implementation_digest,
    )
    session.add(row)
    await session.flush()
    return row
