"""Read-only Director runtime capability + blocker read model.

The Director runtime is only executable when the deployment selects the verified
engine and its checkpoint store is configured. Every executable entry point must
report that fact instead of offering a button that is guaranteed to fail.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.config import Settings

DIRECTOR_BLOCKER_ENGINE_NOT_ENABLED = "DIRECTOR_RUNTIME_NOT_ENABLED"
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
    if engine != "langgraph":
        return DirectorCapabilitiesRead(
            effective_engine=engine,
            runtime_turns_available=False,
            blocker_code=DIRECTOR_BLOCKER_ENGINE_NOT_ENABLED,
            blocker_message=(
                f"当前部署的导演引擎为 {engine}；自动（AUTO）导演轮次需要经过验证的 "
                "langgraph 引擎。手动与人工路径不受影响。"
            ),
            manual_production_available=True,
            checkpoint_configured=False,
        )
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


__all__ = [
    "DIRECTOR_BLOCKER_CHECKPOINT_NOT_CONFIGURED",
    "DIRECTOR_BLOCKER_ENGINE_NOT_ENABLED",
    "DirectorCapabilitiesRead",
    "build_director_capabilities",
]
