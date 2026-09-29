"""Immutable product policy revisions and independent revocation state.

This is additive cutover storage. Runtime dispatch still uses its existing
policy path until a frozen plan can select one exact revision.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base


class ProductPolicyRevision(Base):
    __tablename__ = "product_policy_revisions"
    __table_args__ = (
        UniqueConstraint("policy_id", "policy_revision", name="uq_product_policy_revision"),
        CheckConstraint("policy_revision > 0", name="ck_product_policy_revision_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    policy_id: Mapped[UUID] = mapped_column(nullable=False)
    policy_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    product_path: Mapped[str] = mapped_column(String(120), nullable=False)
    allowed_operations_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    allowed_contracts_json: Mapped[dict[str, list[str]]] = mapped_column(JSON, nullable=False)
    allowed_options_json: Mapped[dict[str, list[str]]] = mapped_column(JSON, nullable=False)
    constraint_overrides_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProductPolicyState(Base):
    __tablename__ = "product_policy_states"
    __table_args__ = (
        CheckConstraint("status IN ('active','revoked')", name="ck_product_policy_state_status"),
    )

    policy_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_policy_revisions.id", ondelete="RESTRICT"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProductPolicyEvent(Base):
    __tablename__ = "product_policy_events"
    __table_args__ = (
        CheckConstraint(
            "from_status IS NULL OR from_status IN ('active','revoked')",
            name="ck_product_policy_event_from_status",
        ),
        CheckConstraint(
            "to_status IN ('active','revoked')", name="ck_product_policy_event_to_status"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    policy_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_policy_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(240), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
