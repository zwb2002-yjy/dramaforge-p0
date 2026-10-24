"""Read-only Director runtime capability + blocker read model.

The Director runtime is only executable when the deployment selects the verified
engine and its checkpoint store is configured. Every executable entry point must
report that fact instead of offering a button that is guaranteed to fail.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.shared.errors import ConflictError

DIRECTOR_BLOCKER_CHECKPOINT_NOT_CONFIGURED = "DIRECTOR_CHECKPOINT_NOT_CONFIGURED"


class DirectorCapabilitiesRead(BaseModel):
    """Secret-free description of what this deployment can actually run."""

    model_config = ConfigDict(extra="forbid")

    effective_engine: str
    runtime_turns_available: bool
    blocker_code: str | None = None
    blocker_message: str | None = None
    # MANUAL production never depends on the Director worker or this engine.
    manual_production_available: bool = True
    # Whether a checkpoint store is configured for the selected engine.
    checkpoint_configured: bool = False


def build_director_capabilities(settings: Settings) -> DirectorCapabilitiesRead:
    """Describe the effective engine and why a new runtime turn may be blocked."""
    engine = settings.director_runtime_engine
    checkpoint_configured = bool(settings.director_checkpoint_database_url.strip())
    if not checkpoint_configured:
        # Starting a turn without the checkpoint store would fail after the
        # authorization was already persisted, so report it as a blocker now.
        return DirectorCapabilitiesRead(
            effective_engine=engine,
            runtime_turns_available=False,
            blocker_code=DIRECTOR_BLOCKER_CHECKPOINT_NOT_CONFIGURED,
            blocker_message=(
                "导演引擎为 langgraph，但未配置 checkpoint 数据库连接；"
                "自动轮次无法持久化。请先按部署文档准备 checkpoint schema 与角色。"
            ),
            manual_production_available=True,
            checkpoint_configured=False,
        )
    return DirectorCapabilitiesRead(
        effective_engine=engine,
        runtime_turns_available=True,
        blocker_code=None,
        blocker_message=None,
        manual_production_available=True,
        checkpoint_configured=True,
    )


def require_director_runtime_available(settings: Settings) -> None:
    """Reject an unavailable runtime before creating turns or calling text models."""
    capabilities = build_director_capabilities(settings)
    if not capabilities.runtime_turns_available:
        raise ConflictError(
            capabilities.blocker_message or "Director runtime is unavailable",
            details={
                "code": capabilities.blocker_code or "DIRECTOR_RUNTIME_UNAVAILABLE",
                "manual_ok": capabilities.manual_production_available,
            },
        )


__all__ = [
    "DIRECTOR_BLOCKER_CHECKPOINT_NOT_CONFIGURED",
    "DirectorCapabilitiesRead",
    "build_director_capabilities",
    "require_director_runtime_available",
]
