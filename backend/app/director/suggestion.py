"""Single-shot Director suggestions for the professional shot workbench.

This module deliberately models a proposal-only boundary. A suggestion is
computed from the current, server-owned Shot design and is returned without
changing that design or creating media execution facts. Production defaults to
the configured structured text bridge; the deterministic transport is an
explicit test fixture only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.assets.models import Scene, Shot
from app.config import get_settings
from app.director.runtime.start import DirectorRuntimeStartService
from app.director.text_transport import DirectorInvocationEvidence, DirectorTextTransport
from app.providers.model_profiles.slots import ModelSlot
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError


class _StrictModel(BaseModel):
    """Base for structured suggestion output; unknown fields fail closed."""

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
        "provider",
        "provider_model_id",
        "provider_model_ids",
        "provider_operation",
        "provider_operation_id",
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


def _normalized_field_name(key: object) -> str:
    """Normalize snake/camel/kebab field spellings before policy matching."""

    text = str(key).strip().replace("-", "_").replace(" ", "_")
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return re.sub(r"_+", "_", text).lower()


def _is_forbidden_field(key: object) -> bool:
    normalized = _normalized_field_name(key)
    return normalized in _FORBIDDEN_KEYS or normalized.startswith(_FORBIDDEN_PREFIXES)


def _reject_execution_fields(value: object, *, path: str = "suggestion") -> None:
    """Reject execution/provider fields even inside free-form design maps."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            if _is_forbidden_field(key):
                raise ValueError(f"{path} contains forbidden design field: {key}")
            _reject_execution_fields(nested, path=f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            _reject_execution_fields(nested, path=f"{path}[{index}]")


class SuggestionDirectorState(RootModel[dict[str, object]]):
    """A design-only state map preserving existing Shot state extensions.

    Shot.director_state already carries versioned design extensions such as
    workflow participation and creative-capability provenance.  Keep those
    keys intact while rejecting execution/provider payloads recursively.
    """

    @model_validator(mode="after")
    def reject_execution_fields(self) -> SuggestionDirectorState:
        _reject_execution_fields(self.root, path="suggested_director_state")
        return self


class ShotDirectorSuggestionCandidate(_StrictModel):
    """Untrusted model output before invocation evidence is attached."""

    base_shot_version: int = Field(ge=1)
    suggested_image_prompt: str = Field(max_length=20000)
    suggested_video_prompt: str = Field(max_length=20000)
    suggested_director_state: SuggestionDirectorState
    change_summary: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="before")
    @classmethod
    def reject_forbidden_fields(cls, value: object) -> object:
        _reject_execution_fields(value)
        return value


class ShotDirectorSuggestionRequest(_StrictModel):
    """Client request; canonical Shot prompts/state are never accepted here."""

    scene_id: UUID
    shot_id: UUID
    expected_shot_version: int = Field(ge=1)
    user_instruction: str = Field(min_length=1, max_length=4000)
    request_key: str = Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")

    @field_validator("user_instruction")
    @classmethod
    def instruction_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("user_instruction must not be blank")
        return normalized


@dataclass(frozen=True)
class ShotDirectorSuggestionContext:
    """Read-only server context handed to the suggestion transport."""

    project_id: UUID
    scene_id: UUID
    shot_id: UUID
    expected_shot_version: int
    user_instruction: str
    image_prompt: str
    video_prompt: str
    director_state: dict[str, object]


class ShotDirectorSuggestionTransport(Protocol):
    async def generate(self, context: ShotDirectorSuggestionContext) -> object:
        """Return an untrusted structured candidate for Pydantic validation."""


def _append_prompt(current: str, instruction: str) -> str:
    suffix = f"\n\n导演要求：{instruction}"
    if not current:
        return suffix.lstrip()
    return f"{current}{suffix}"[:20000]


class DeterministicShotDirectorSuggestionTransport:
    """No-network fixture; production never selects this transport implicitly."""

    async def generate(self, context: ShotDirectorSuggestionContext) -> object:
        state = dict(SuggestionDirectorState.model_validate(context.director_state).root)
        action_value = state.get("action")
        current_action = dict(action_value) if isinstance(action_value, dict) else {}
        action_description = (
            f"{current_action.get('description', '')}\n导演要求：{context.user_instruction}"
            if current_action.get("description")
            else f"导演要求：{context.user_instruction}"
        )
        # Keep the deterministic adapter within the same design schema limits
        # as the eventual structured model output.
        state["action"] = {**current_action, "description": action_description[:2000]}
        return {
            "base_shot_version": context.expected_shot_version,
            "suggested_image_prompt": _append_prompt(
                context.image_prompt, context.user_instruction
            ),
            "suggested_video_prompt": _append_prompt(
                context.video_prompt, context.user_instruction
            ),
            "suggested_director_state": state,
            "change_summary": (
                f"根据导演要求更新图片提示词、视频提示词和动作语义：{context.user_instruction}"
            )[:4000],
        }


def get_shot_director_suggestion_transport() -> ShotDirectorSuggestionTransport:
    """Return the explicit deterministic fixture for legacy focused tests."""

    return DeterministicShotDirectorSuggestionTransport()


class ShotDirectorSuggestionService:
    """Read current Shot truth and return one validated, non-persistent proposal."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        transport: ShotDirectorSuggestionTransport | None = None,
        text_transport: DirectorTextTransport | None = None,
    ) -> None:
        self._session = session
        self._transport = transport
        self._text_transport = text_transport or DirectorTextTransport(session)

    async def suggest(
        self,
        *,
        project_id: UUID,
        actor: User,
        request: ShotDirectorSuggestionRequest,
    ) -> ShotDirectorSuggestion:
        project = await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        shot = (
            await self._session.execute(
                select(Shot).where(
                    Shot.id == request.shot_id,
                    Shot.project_id == project_id,
                    Shot.scene_id == request.scene_id,
                )
            )
        ).scalar_one_or_none()
        if shot is None:
            # Do not reveal whether a foreign shot id exists.
            raise NotFoundError("shot not found")
        if shot.version != request.expected_shot_version:
            raise ConflictError(
                "shot version conflict; suggestion must use current server truth",
                details={
                    "code": "SHOT_SUGGESTION_STALE",
                    "expected_version": request.expected_shot_version,
                    "actual_version": shot.version,
                },
            )

        try:
            current_state = SuggestionDirectorState.model_validate(dict(shot.director_state or {}))
        except ValidationError as exc:
            raise ValidationAppError(
                "current shot director state is invalid",
                details={"code": "INVALID_CURRENT_SHOT_DIRECTOR_STATE"},
            ) from exc

        context = ShotDirectorSuggestionContext(
            project_id=project.id,
            scene_id=shot.scene_id,
            shot_id=shot.id,
            expected_shot_version=shot.version,
            user_instruction=request.user_instruction,
            image_prompt=shot.image_prompt,
            video_prompt=shot.video_prompt,
            director_state=dict(current_state.root),
        )
        text_result = None
        try:
            if self._transport is not None:
                raw = await self._transport.generate(context)
                candidate = ShotDirectorSuggestionCandidate.model_validate(raw)
            else:
                scene = await self._session.get(Scene, shot.scene_id)
                if scene is None:
                    raise NotFoundError("scene not found")
                text_result = await self._text_transport.generate_structured(
                    project=project,
                    actor=actor,
                    scope_type="shot",
                    scope_entity_id=shot.id,
                    request_key=request.request_key,
                    slot=ModelSlot.PLANNING_STORYBOARD,
                    task_name="shot_director_suggestion",
                    system_instruction=(
                        "Act as a film Director. Preserve explicit user constraints and existing "
                        "design extensions. Propose a bounded Shot design diff only."
                    ),
                    input_versions={
                        "project": project.version,
                        "scene": scene.version,
                        "shot": shot.version,
                    },
                    intent_snapshot={"user_instruction": request.user_instruction},
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
                            "director_state": dict(current_state.root),
                            "formal_keyframe_artifact_id": (
                                str(shot.formal_keyframe_artifact_id)
                                if shot.formal_keyframe_artifact_id
                                else None
                            ),
                            "formal_video_artifact_id": (
                                str(shot.formal_video_artifact_id)
                                if shot.formal_video_artifact_id
                                else None
                            ),
                        },
                    },
                    output_type=ShotDirectorSuggestionCandidate,
                )
                candidate = text_result.value
        except ValidationError as exc:
            raise ValidationAppError(
                "director suggestion output failed structured validation",
                details={"code": "INVALID_DIRECTOR_SUGGESTION", "errors": exc.errors()},
            ) from exc
        except ValidationAppError:
            raise
        except ConflictError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport boundary is fail-closed
            raise ValidationAppError(
                f"director suggestion failed: {exc}",
                details={"code": "DIRECTOR_SUGGESTION_FAILED", "manual_ok": True},
            ) from exc

        if candidate.base_shot_version != shot.version:
            if text_result is not None:
                await self._text_transport.mark_failed(
                    text_result.turn,
                    reason=("model base_shot_version did not match the frozen server Shot version"),
                )
            raise ValidationAppError(
                "director suggestion base version does not match the server Shot",
                details={
                    "code": "INVALID_DIRECTOR_SUGGESTION_BASE_VERSION",
                    "expected_version": shot.version,
                    "actual_version": candidate.base_shot_version,
                },
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
                    "shot changed while the Director suggestion was generated",
                    details={
                        "code": "SHOT_SUGGESTION_RESULT_STALE",
                        "expected_version": request.expected_shot_version,
                        "actual_version": shot.version,
                        "turn_id": str(text_result.turn.id),
                    },
                )
            await self._text_transport.mark_awaiting_user(text_result.turn)
            await DirectorRuntimeStartService(
                self._session, settings=get_settings(),
            ).accept_existing_detached_turn(
                project=project,
                actor=actor,
                turn=text_result.turn,
                created=text_result.turn_created,
            )
            await self._session.commit()
        return ShotDirectorSuggestion(
            **candidate.model_dump(),
            director_evidence=text_result.evidence if text_result is not None else None,
        )


class ShotDirectorSuggestion(ShotDirectorSuggestionCandidate):
    """Validated proposal plus the exact text invocation identity, when real."""

    director_evidence: DirectorInvocationEvidence | None = None


__all__ = [
    "DeterministicShotDirectorSuggestionTransport",
    "ShotDirectorSuggestion",
    "ShotDirectorSuggestionCandidate",
    "ShotDirectorSuggestionContext",
    "ShotDirectorSuggestionRequest",
    "ShotDirectorSuggestionService",
    "ShotDirectorSuggestionTransport",
    "SuggestionDirectorState",
    "get_shot_director_suggestion_transport",
]
