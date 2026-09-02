"""Proactive Director Recommendation (V1 G4A).

Recommendation reads server-owned Scene/Shot facts and returns one structured
design suggestion without writing canonical facts, creating media, or touching
Provider/Runtime/SQL/Artifact fields.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.assets.models import Scene, Shot
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


_FORBIDDEN_KEYS = frozenset(
    {
        "artifact",
        "artifact_id",
        "artifact_ids",
        "artifact_url",
        "column",
        "execution",
        "execution_id",
        "execution_plan",
        "node_run",
        "node_run_id",
        "node_run_ids",
        "patch",
        "production_lineage",
        "provider",
        "provider_model_id",
        "provider_operation",
        "provider_request",
        "raw_sql",
        "runtime",
        "runtime_id",
        "sql",
        "sql_query",
        "table",
        "worker",
        "worker_queue",
    }
)
_FORBIDDEN_PREFIXES = (
    "artifact_",
    "execution_",
    "node_run_",
    "provider_",
    "raw_sql_",
    "runtime_",
    "sql_",
    "worker_",
)


def _normalize(key: object) -> str:
    text = str(key).strip().replace("-", "_").replace(" ", "_")
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return re.sub(r"_+", "_", text).lower()


def _reject_forbidden(value: object, *, path: str = "recommendation") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if _normalize(key) in _FORBIDDEN_KEYS or _normalize(key).startswith(
                _FORBIDDEN_PREFIXES
            ):
                raise ValueError(f"{path} contains forbidden field: {key}")
            _reject_forbidden(nested, path=f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            _reject_forbidden(nested, path=f"{path}[{index}]")


class DirectorRecommendation(_StrictModel):
    base_shot_version: int = Field(ge=1)
    scope: Literal["shot"] = "shot"
    category: Literal[
        "PERFORMANCE",
        "BLOCKING",
        "SHOT_SIZE",
        "CAMERA_ANGLE",
        "CAMERA_MOTION",
        "PACING",
    ]
    current_state: str = Field(min_length=1, max_length=4000)
    suggested_change: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=4000)
    expected_effect: str = Field(min_length=1, max_length=4000)
    risk: str = Field(min_length=1, max_length=4000)
    affected_facts: list[str] = Field(default_factory=list, max_length=30)
    typed_operations: list[dict[str, object]] = Field(default_factory=list, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def reject_execution_fields(cls, value: object) -> object:
        _reject_forbidden(value)
        return value


class DirectorRecommendationRequest(_StrictModel):
    scene_id: UUID
    shot_id: UUID
    expected_shot_version: int = Field(ge=1)


@dataclass(frozen=True)
class DirectorRecommendationContext:
    project_id: UUID
    scene_id: UUID
    shot_id: UUID
    shot_version: int
    shot_type: str
    camera_move: str
    visual_description: str
    dialogue: str
    director_state: dict[str, object]


class DirectorRecommendationTransport(Protocol):
    async def generate(self, context: DirectorRecommendationContext) -> object:
        """Return an untrusted structured recommendation candidate."""


class DeterministicDirectorRecommendationTransport:
    async def generate(self, context: DirectorRecommendationContext) -> object:
        raw_action = context.director_state.get("action")
        action = dict(raw_action) if isinstance(raw_action, Mapping) else {}
        current_action = str(action.get("description") or context.visual_description)
        return {
            "base_shot_version": context.shot_version,
            "scope": "shot",
            "category": "PERFORMANCE",
            "current_state": (
                f"{context.shot_type} {context.camera_move}：{current_action}"
            )[:4000],
            "suggested_change": (
                "先完成一个可观察的呼吸/视线停顿，再进入台词或动作节拍"
            ),
            "reason": "当前镜头缺少情绪被角色消化后产生的表演节拍。",
            "expected_effect": "情绪从‘告知’变成‘发生’，观众能读到内部反应。",
            "risk": "增加停顿会轻微延长镜头时长，需在后续剪辑确认节奏。",
            "affected_facts": ["shot.director_state.action", "shot.director_state.performance"],
            "typed_operations": [
                {
                    "op": "update_director_state",
                    "field": "performance",
                    "value": {
                        "beat": "breath_hold",
                        "gaze": "down_then_up",
                        "note": "导演主动推荐：先内部反应再输出",
                    },
                }
            ],
        }


class DirectorRecommendationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        transport: DirectorRecommendationTransport | None = None,
    ) -> None:
        self._session = session
        self._transport = transport or DeterministicDirectorRecommendationTransport()

    async def recommend(
        self,
        *,
        project_id: UUID,
        actor: User,
        request: DirectorRecommendationRequest,
    ) -> DirectorRecommendation:
        await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        scene = await self._session.scalar(
            select(Scene).where(
                Scene.id == request.scene_id,
            )
        )
        shot = await self._session.scalar(
            select(Shot).where(
                Shot.id == request.shot_id,
                Shot.project_id == project_id,
                Shot.scene_id == request.scene_id,
            )
        )
        if shot is None or scene is None:
            raise NotFoundError("shot not found")
        if shot.version != request.expected_shot_version:
            raise ConflictError(
                "shot version conflict; recommendation must use current server truth",
                details={
                    "code": "SHOT_RECOMMENDATION_STALE",
                    "expected_version": request.expected_shot_version,
                    "actual_version": shot.version,
                },
            )
        context = DirectorRecommendationContext(
            project_id=project_id,
            scene_id=shot.scene_id,
            shot_id=shot.id,
            shot_version=shot.version,
            shot_type=shot.shot_type,
            camera_move=shot.camera_move,
            visual_description=shot.visual_description,
            dialogue=shot.dialogue,
            director_state=dict(shot.director_state or {}),
        )
        try:
            recommendation = DirectorRecommendation.model_validate(
                await self._transport.generate(context)
            )
        except ValidationError as exc:
            raise ValidationAppError(
                "director recommendation failed structured validation",
                details={"code": "INVALID_DIRECTOR_RECOMMENDATION", "errors": exc.errors()},
            ) from exc
        except Exception as exc:  # noqa: BLE001 - transport boundary fail closed
            raise ValidationAppError(
                f"director recommendation failed: {exc}",
                details={"code": "DIRECTOR_RECOMMENDATION_FAILED", "manual_ok": True},
            ) from exc
        if recommendation.base_shot_version != shot.version:
            raise ValidationAppError(
                "recommendation base version does not match the server Shot",
                details={"code": "INVALID_RECOMMENDATION_BASE_VERSION"},
            )
        return recommendation


__all__ = [
    "DeterministicDirectorRecommendationTransport",
    "DirectorRecommendation",
    "DirectorRecommendationContext",
    "DirectorRecommendationRequest",
    "DirectorRecommendationService",
    "DirectorRecommendationTransport",
]
