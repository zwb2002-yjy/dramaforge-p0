"""One explicitly approved action, persisted before autonomous submission."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base
from app.shared.db_types import JSON_DOCUMENT


class ProductionCommandAuthorization(Base):
    __tablename__ = "production_command_authorizations"
    __table_args__ = (
        UniqueConstraint("project_id", "command_key", name="uq_production_authorized_command"),
        CheckConstraint(
            "status IN ('approved','accepted','revoked')", name="ck_command_auth_status"
        ),
        CheckConstraint("profile_version > 0", name="ck_command_auth_profile_version"),
        CheckConstraint(
            "(status = 'accepted' AND node_run_id IS NOT NULL) OR "
            "(status <> 'accepted' AND node_run_id IS NULL)",
            name="ck_command_auth_receipt",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    shot_id: Mapped[UUID] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"))
    command_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    body: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT)
    profile_version: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="approved")
    node_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("node_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
