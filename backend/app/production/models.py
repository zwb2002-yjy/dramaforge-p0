"""Production Graph models (S1.4 subset). Published GraphVersion is immutable."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.shared.base import Base
from app.shared.enums import GraphStatus
from app.shared.errors import ValidationAppError


class Graph(Base):
    __tablename__ = "graphs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GraphVersion(Base):
    __tablename__ = "graph_versions"
    __table_args__ = (
        UniqueConstraint("graph_id", "version", name="uq_graph_versions_graph_version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    graph_id: Mapped[UUID] = mapped_column(
        ForeignKey("graphs.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=GraphStatus.DRAFT.value
    )
    definition: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def assert_graph_version_mutable(version: GraphVersion) -> None:
    """Raise if a published (or later) graph version is modified."""
    if version.status in {
        GraphStatus.PUBLISHED.value,
        GraphStatus.SUPERSEDED.value,
        GraphStatus.ARCHIVED.value,
    }:
        raise ValidationAppError("published graph version is immutable")
