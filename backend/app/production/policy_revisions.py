"""Explicit maintenance operations for immutable product policy revisions.

This module is not called by the current runtime. Dispatch will select and
freeze a revision only after the model-system cutover gates are implemented.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.production.policy_models import (
    ProductPolicyEvent,
    ProductPolicyRevision,
    ProductPolicyState,
)


class ProductPolicyContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    product_path: str = Field(min_length=1, max_length=120)
    allowed_operations: frozenset[str] = Field(min_length=1)
    allowed_contracts: dict[str, frozenset[str]]
    allowed_options: dict[str, frozenset[str]]
    constraint_overrides: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_operations(self) -> ProductPolicyContent:
        if not self.allowed_operations or any(
            not operation.strip() for operation in self.allowed_operations
        ):
            raise ValueError("policy operations must be non-empty")
        if not set(self.allowed_contracts) <= self.allowed_operations:
            raise ValueError("contracts reference an operation the policy does not allow")
        if not set(self.allowed_options) <= self.allowed_operations:
            raise ValueError("options reference an operation the policy does not allow")
        if any(not contracts for contracts in self.allowed_contracts.values()):
            raise ValueError("allowed contract sets cannot be empty")
        return self

    def canonical_body(self) -> dict[str, Any]:
        return {
            "product_path": self.product_path,
            "allowed_operations": sorted(self.allowed_operations),
            "allowed_contracts": {
                operation: sorted(contracts)
                for operation, contracts in sorted(self.allowed_contracts.items())
            },
            "allowed_options": {
                operation: sorted(options)
                for operation, options in sorted(self.allowed_options.items())
            },
            "constraint_overrides": self.constraint_overrides,
        }

    def policy_hash(self) -> str:
        return _hash_policy_body(self.canonical_body())


def _hash_policy_body(body: dict[str, Any]) -> str:
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def publish_product_policy_revision(
    session: AsyncSession,
    *,
    policy_id: UUID,
    policy_revision: int,
    content: ProductPolicyContent,
    reason: str,
) -> ProductPolicyRevision:
    """Publish a new exact revision; previous revisions remain independently active."""
    if policy_revision <= 0 or not reason.strip():
        raise ValueError("positive policy revision and reason are required")
    body = content.canonical_body()
    row = ProductPolicyRevision(
        policy_id=policy_id,
        policy_revision=policy_revision,
        policy_hash=_hash_policy_body(body),
        product_path=body["product_path"],
        allowed_operations_json=body["allowed_operations"],
        allowed_contracts_json=body["allowed_contracts"],
        allowed_options_json=body["allowed_options"],
        constraint_overrides_json=body["constraint_overrides"],
    )
    session.add(row)
    await session.flush()
    session.add(ProductPolicyState(policy_revision_id=row.id, status="active"))
    session.add(
        ProductPolicyEvent(
            policy_revision_id=row.id,
            from_status=None,
            to_status="active",
            reason=reason.strip(),
        )
    )
    await session.flush()
    return row


async def revoke_product_policy_revision(
    session: AsyncSession, *, policy_revision_id: UUID, reason: str
) -> None:
    """Revoke one revision for future Create without mutating its policy body."""
    if not reason.strip():
        raise ValueError("revoke reason is required")
    state = await session.scalar(
        select(ProductPolicyState)
        .where(ProductPolicyState.policy_revision_id == policy_revision_id)
        .with_for_update()
    )
    if state is None or state.status != "active":
        raise ValueError("policy revision is missing or already revoked")
    state.status = "revoked"
    state.updated_at = datetime.now(UTC)
    session.add(
        ProductPolicyEvent(
            policy_revision_id=policy_revision_id,
            from_status="active",
            to_status="revoked",
            reason=reason.strip(),
        )
    )
    await session.flush()
