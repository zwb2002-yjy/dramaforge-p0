"""Single-shot Director suggestions for the professional shot workbench.

This module deliberately models a proposal-only boundary.  A suggestion is
computed from the current, server-owned Shot design and is returned to the
caller without creating an AgentRun, ProviderOperation, proposal row, media
artifact, or execution.  The default transport is deterministic so local and
test use never makes a paid model call; a future text transport can be
injected behind the same typed seam once that policy is explicitly approved.
"""

from __future__ import annotations

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
from app.assets.models import Shot
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError


class _StrictModel(BaseModel):
    """Base for structured suggestion output; unknown fields fail closed."""

    model_config = ConfigDict(extra="forbid")


_FORBIDDEN_KEYS = frozenset(
    {
        "artifact",
        "artifact_id",
        "artifact_ids",
        "column",
        "execution",
        "execution_id",
        "node_run",
        "node_run_id",
        "provider",
        "provider_operation",
        "provider_operation_id",
        "provider_request",
        "raw_sql",
        "runtime",
        "sql",
        "table",
        "worker",
    }
)


def _reject_execution_fields(value: object, *, path: str = "suggestion") -> None:
    """Reject execution/provider fields even inside free-form design maps."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_KEYS:
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


class ShotDirectorSuggestion(_StrictModel):
    """The complete, non-persistent proposal returned to the Shot UI."""

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
    """No-network local adapter used until an explicitly approved LLM seam exists."""

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
                "根据导演要求更新图片提示词、视频提示词和动作语义："
                f"{context.user_instruction}"
            )[:4000],
        }


def get_shot_director_suggestion_transport() -> ShotDirectorSuggestionTransport:
    """Resolve the safe default transport; tests may monkeypatch this seam."""

    return DeterministicShotDirectorSuggestionTransport()


class ShotDirectorSuggestionService:
    """Read current Shot truth and return one validated, non-persistent proposal."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        transport: ShotDirectorSuggestionTransport | None = None,
    ) -> None:
        self._session = session
        self._transport = transport or get_shot_director_suggestion_transport()

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
        try:
            raw = await self._transport.generate(context)
            suggestion = ShotDirectorSuggestion.model_validate(raw)
        except ValidationError as exc:
            raise ValidationAppError(
                "director suggestion output failed structured validation",
                details={"code": "INVALID_DIRECTOR_SUGGESTION", "errors": exc.errors()},
            ) from exc
        except Exception as exc:  # noqa: BLE001 - transport boundary is fail-closed
            raise ValidationAppError(
                f"director suggestion failed: {exc}",
                details={"code": "DIRECTOR_SUGGESTION_FAILED", "manual_ok": True},
            ) from exc

        if suggestion.base_shot_version != shot.version:
            raise ValidationAppError(
                "director suggestion base version does not match the server Shot",
                details={
                    "code": "INVALID_DIRECTOR_SUGGESTION_BASE_VERSION",
                    "expected_version": shot.version,
                    "actual_version": suggestion.base_shot_version,
                },
            )
        return suggestion


__all__ = [
    "DeterministicShotDirectorSuggestionTransport",
    "ShotDirectorSuggestion",
    "ShotDirectorSuggestionContext",
    "ShotDirectorSuggestionRequest",
    "ShotDirectorSuggestionService",
    "ShotDirectorSuggestionTransport",
    "SuggestionDirectorState",
    "get_shot_director_suggestion_transport",
]
