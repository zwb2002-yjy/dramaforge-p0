"""Per-Turn immutable engine routing; configuration affects new turns only."""

from typing import Literal

from app.config import Settings
from app.director.runtime.control import DirectorRuntimeControlService
from app.director.runtime.langgraph_adapter import ENGINE_VERSION, STATE_SCHEMA_VERSION
from app.director.runtime.models import DirectorRuntimeControl
from app.director.turn_models import DirectorTurn
from app.shared.errors import ConflictError

DirectorEngine = Literal["legacy", "langgraph"]


class DirectorEngineRouter:
    def __init__(
        self, *, settings: Settings, controls: DirectorRuntimeControlService,
    ) -> None:
        self._settings = settings
        self._controls = controls

    async def bind_new(
        self, turn: DirectorTurn, *, created: bool,
    ) -> DirectorRuntimeControl | None:
        existing = self.engine_for(turn)
        if existing == "langgraph":
            assert turn.runtime_execution_id is not None
            return await self._controls.bind(
                project_id=turn.project_id,
                turn_id=turn.id,
                engine_version=str(turn.engine_version),
                state_schema_version=str(turn.state_schema_version),
            )
        if existing == "legacy" and turn.runtime_execution_id is None:
            if not created or self._settings.director_runtime_engine == "legacy":
                return None
            return await self._controls.bind(
                project_id=turn.project_id,
                turn_id=turn.id,
                engine_version=ENGINE_VERSION,
                state_schema_version=STATE_SCHEMA_VERSION,
            )
        raise ConflictError(
            "Director turn engine binding is invalid",
            details={"code": "DIRECTOR_ENGINE_BINDING_INVALID"},
        )

    @staticmethod
    def engine_for(turn: DirectorTurn) -> DirectorEngine:
        if (
            turn.engine_version is None
            and turn.state_schema_version is None
            and turn.runtime_execution_id is None
        ):
            return "legacy"
        if (
            turn.engine_version == ENGINE_VERSION
            and turn.state_schema_version == STATE_SCHEMA_VERSION
            and turn.runtime_execution_id is not None
        ):
            return "langgraph"
        raise ConflictError(
            "Director turn is bound to an unsupported engine",
            details={
                "code": "DIRECTOR_ENGINE_VERSION_UNSUPPORTED",
                "engine_version": turn.engine_version,
                "state_schema_version": turn.state_schema_version,
            },
        )


__all__ = ["DirectorEngine", "DirectorEngineRouter"]
