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
from app.assets.models import Episode, Scene, Shot
from app.director.text_transport import DirectorInvocationEvidence, DirectorTextTransport
from app.director.turn_service import DirectorTurnService
from app.providers.model_profiles.slots import ModelSlot
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


class DirectorRecommendationOperation(_StrictModel):
    """The only operation a Shot recommendation may place in a draft."""

    op: Literal["update_director_state"]
    field: Literal[
        "framing",
        "camera",
        "action",
        "expression",
        "gaze",
        "composition",
        "continuity_constraints",
        "video_reference_risk",
        "performance",
    ]
    value: dict[str, object] | list[dict[str, object]]


class DirectorRecommendationCandidate(_StrictModel):
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
    typed_operations: list[DirectorRecommendationOperation] = Field(
        default_factory=list, max_length=20
    )

    @model_validator(mode="before")
    @classmethod
    def reject_execution_fields(cls, value: object) -> object:
        _reject_forbidden(value)
        return value


class DirectorRecommendationRequest(_StrictModel):
    scene_id: UUID
    shot_id: UUID
    expected_shot_version: int = Field(ge=1)
    request_key: str = Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")


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
    """No-network fixture; production never selects it implicitly."""

    async def generate(self, context: DirectorRecommendationContext) -> object:
        raw_action = context.director_state.get("action")
        action = dict(raw_action) if isinstance(raw_action, Mapping) else {}
        current_action = str(action.get("description") or context.visual_description)
        return {
            "base_shot_version": context.shot_version,
            "scope": "shot",
            "category": "PERFORMANCE",
            "current_state": (f"{context.shot_type} {context.camera_move}：{current_action}")[
                :4000
            ],
            "suggested_change": ("先完成一个可观察的呼吸/视线停顿，再进入台词或动作节拍"),
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
        text_transport: DirectorTextTransport | None = None,
    ) -> None:
        self._session = session
        self._transport = transport
        self._text_transport = text_transport or DirectorTextTransport(session)

    async def recommend(
        self,
        *,
        project_id: UUID,
        actor: User,
        request: DirectorRecommendationRequest,
    ) -> DirectorRecommendation:
        project = await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        autonomy_version = await DirectorTurnService(self._session).require_proactive_authorization(
            project_id=project.id,
        )
        scene = await self._session.scalar(
            select(Scene)
            .join(Episode, Episode.id == Scene.episode_id)
            .where(
                Scene.id == request.scene_id,
                Episode.project_id == project_id,
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
        text_result = None
        try:
            if self._transport is not None:
                recommendation = DirectorRecommendationCandidate.model_validate(
                    await self._transport.generate(context)
                )
            else:
                text_result = await self._text_transport.generate_structured(
                    project=project,
                    actor=actor,
                    scope_type="shot",
                    scope_entity_id=shot.id,
                    request_key=request.request_key,
                    slot=ModelSlot.PLANNING_STORYBOARD,
                    task_name="shot_director_recommendation",
                    system_instruction=(
                        "Act as a proactive film Director. Return one focused, bounded and "
                        "actionable recommendation. typed_operations may only use "
                        "update_director_state with a design field and JSON value."
                    ),
                    input_versions={
                        "creative_profile": autonomy_version,
                        "project": project.version,
                        "scene": scene.version,
                        "shot": shot.version,
                    },
                    intent_snapshot={"kind": "proactive_shot_analysis"},
                    context_payload={
                        "project": {
                            "name": project.name,
                            "aspect_ratio": project.aspect_ratio,
                            "style_bible": project.style_bible or {},
                        },
                        "scene": {
                            "id": str(scene.id),
                            "scene_number": scene.scene_number,
                            "location_name": scene.location_name,
                            "time_of_day": scene.time_of_day,
                            "synopsis": scene.synopsis,
                            "design_state": scene.design_state or {},
                        },
                        "shot": {
                            "id": str(shot.id),
                            "shot_number": shot.shot_number,
                            "shot_type": shot.shot_type,
                            "camera_move": shot.camera_move,
                            "visual_description": shot.visual_description,
                            "dialogue": shot.dialogue,
                            "duration_seconds": str(float(shot.duration_seconds)),
                            "image_prompt": shot.image_prompt,
                            "video_prompt": shot.video_prompt,
                            "director_state": shot.director_state or {},
                        },
                    },
                    output_type=DirectorRecommendationCandidate,
                )
                recommendation = text_result.value
        except ValidationError as exc:
            raise ValidationAppError(
                "director recommendation failed structured validation",
                details={"code": "INVALID_DIRECTOR_RECOMMENDATION", "errors": exc.errors()},
            ) from exc
        except ValidationAppError:
            raise
        except ConflictError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport boundary fail closed
            raise ValidationAppError(
                f"director recommendation failed: {exc}",
                details={"code": "DIRECTOR_RECOMMENDATION_FAILED", "manual_ok": True},
            ) from exc
        if recommendation.base_shot_version != shot.version:
            if text_result is not None:
                await self._text_transport.mark_failed(
                    text_result.turn,
                    reason="model base_shot_version did not match the frozen server Shot version",
                )
            raise ValidationAppError(
                "recommendation base version does not match the server Shot",
                details={"code": "INVALID_RECOMMENDATION_BASE_VERSION"},
            )
        if text_result is not None:
            await self._session.refresh(shot)
            if shot.version != request.expected_shot_version:
                await self._text_transport.mark_stale(
                    text_result.turn,
                    reason=(
                        f"Shot changed during inference: expected "
                        f"{request.expected_shot_version}, current {shot.version}"
                    ),
                )
                raise ConflictError(
                    "shot changed while the Director recommendation was generated",
                    details={
                        "code": "SHOT_RECOMMENDATION_RESULT_STALE",
                        "expected_version": request.expected_shot_version,
                        "actual_version": shot.version,
                        "turn_id": str(text_result.turn.id),
                    },
                )
            await self._text_transport.mark_awaiting_user(text_result.turn)
        return DirectorRecommendation(
            **recommendation.model_dump(),
            director_evidence=text_result.evidence if text_result is not None else None,
        )


class DirectorRecommendation(DirectorRecommendationCandidate):
    director_evidence: DirectorInvocationEvidence | None = None


__all__ = [
    "DeterministicDirectorRecommendationTransport",
    "DirectorRecommendation",
    "DirectorRecommendationCandidate",
    "DirectorRecommendationContext",
    "DirectorRecommendationRequest",
    "DirectorRecommendationService",
    "DirectorRecommendationTransport",
]
