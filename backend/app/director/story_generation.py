"""Brief-to-script generation through the audited Director text bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.assets.models import Episode, Scene, ScriptDocument, Shot
from app.assets.script_import import parse_script_markdown
from app.config import get_settings
from app.director.runtime.start import DirectorRuntimeStartService
from app.director.story_proposal import StoryProposalResult, create_story_proposal
from app.director.text_transport import (
    DirectorInvocationEvidence,
    DirectorTextTransport,
    StructuredDirectorTextResult,
)
from app.director.turn_models import DirectorTurn
from app.providers.model_profiles.slots import ModelSlot
from app.shared.db import set_rls_context
from app.shared.errors import AppError, ConflictError, ValidationAppError


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _one_line(value: str) -> str:
    return " ".join(value.replace("\r", "\n").split()).strip()


class StoryShotDraft(_StrictModel):
    shot_number: int = Field(ge=1, le=999)
    shot_type: str = Field(min_length=1, max_length=40)
    visual: str = Field(min_length=1, max_length=4000)
    dialogue: str = Field(default="", max_length=4000)
    camera_move: str = Field(default="static", min_length=1, max_length=80)

    @field_validator("shot_type", "visual", "camera_move")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = _one_line(value)
        if not normalized:
            raise ValueError("required Story Shot text must not be blank")
        return normalized

    @field_validator("dialogue")
    @classmethod
    def normalize_dialogue(cls, value: str) -> str:
        return _one_line(value)


class StorySceneDraft(_StrictModel):
    scene_number: int = Field(ge=1, le=999)
    location_name: str = Field(min_length=1, max_length=160)
    time_of_day: str = Field(min_length=1, max_length=40)
    synopsis: str = Field(default="", max_length=4000)
    shots: list[StoryShotDraft] = Field(min_length=1, max_length=40)

    @field_validator("location_name", "time_of_day")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = _one_line(value)
        if not normalized:
            raise ValueError("Scene location and time must not be blank")
        return normalized

    @field_validator("synopsis")
    @classmethod
    def normalize_synopsis(cls, value: str) -> str:
        return _one_line(value)

    @model_validator(mode="after")
    def unique_shot_numbers(self) -> Self:
        numbers = [shot.shot_number for shot in self.shots]
        if len(numbers) != len(set(numbers)):
            raise ValueError("shot_number must be unique inside each Scene")
        return self


class StoryDraftCandidate(_StrictModel):
    episode_number: int = Field(default=1, ge=1, le=999)
    title: str = Field(min_length=1, max_length=160)
    synopsis: str = Field(default="", max_length=8000)
    scenes: list[StorySceneDraft] = Field(min_length=1, max_length=20)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = _one_line(value)
        if not normalized:
            raise ValueError("Story title must not be blank")
        return normalized

    @field_validator("synopsis")
    @classmethod
    def normalize_synopsis(cls, value: str) -> str:
        return _one_line(value)

    @model_validator(mode="after")
    def validate_structure(self) -> Self:
        numbers = [scene.scene_number for scene in self.scenes]
        if len(numbers) != len(set(numbers)):
            raise ValueError("scene_number must be unique")
        if sum(len(scene.shots) for scene in self.scenes) > 200:
            raise ValueError("story draft exceeds the 200 Shot limit")
        return self


class StoryGenerationRequest(_StrictModel):
    request_key: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    brief: str = Field(min_length=1, max_length=8000)
    filename: str = Field(default="generated-story.md", min_length=1, max_length=260)

    @field_validator("brief")
    @classmethod
    def brief_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("brief must not be blank")
        return normalized


@dataclass(frozen=True)
class GeneratedStoryProposal:
    draft: StoryDraftCandidate
    draft_text: str
    proposal: StoryProposalResult
    turn: DirectorTurn
    evidence: DirectorInvocationEvidence


def render_story_markdown(draft: StoryDraftCandidate) -> str:
    """Render only the parser grammar; model strings cannot inject headings."""

    lines = [f"# Episode {draft.episode_number} — {_one_line(draft.title)}"]
    if draft.synopsis:
        lines.append(_one_line(draft.synopsis))
    for scene in draft.scenes:
        location = _one_line(scene.location_name).replace("/", "／")
        time_of_day = _one_line(scene.time_of_day).replace("/", "／")
        lines.append(f"## Scene {scene.scene_number} — {location} / {time_of_day}")
        if scene.synopsis:
            lines.append(_one_line(scene.synopsis))
        for shot in scene.shots:
            lines.extend(
                [
                    f"### Shot {shot.shot_number} — {_one_line(shot.shot_type)}",
                    f"Visual: {_one_line(shot.visual)}",
                    f"Dialogue: {_one_line(shot.dialogue)}",
                    f"Camera: {_one_line(shot.camera_move)}",
                ]
            )
    return "\n".join(lines).strip() + "\n"


class StoryGenerationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        text_transport: DirectorTextTransport | None = None,
    ) -> None:
        self._session = session
        self._text_transport = text_transport or DirectorTextTransport(session)

    async def generate_proposal(
        self,
        *,
        project: Project,
        actor: User,
        request: StoryGenerationRequest,
    ) -> GeneratedStoryProposal:
        context, versions = await self._story_context(project)
        text_result = await self._text_transport.generate_structured(
            project=project,
            actor=actor,
            scope_type="story",
            scope_entity_id=project.id,
            request_key=request.request_key,
            slot=ModelSlot.PLANNING_SCRIPT,
            task_name="story_draft_generation",
            system_instruction=(
                "Act as a screenwriter for a short-form film. Convert the user's brief into one "
                "bounded Episode with ordered Scenes and Shots. Preserve explicit user intent. "
                "Return creative facts only; never return commands or database/media identifiers."
            ),
            input_versions=versions,
            intent_snapshot={"brief": request.brief, "filename": request.filename},
            context_payload={
                "project": {
                    "name": project.name,
                    "aspect_ratio": project.aspect_ratio,
                    "target_platform": project.target_platform,
                    "style_bible": project.style_bible or {},
                },
                "current_story": context,
            },
            output_type=StoryDraftCandidate,
        )
        _current_context, current_versions = await self._story_context(project)
        if current_versions != versions:
            await self._text_transport.mark_stale(
                text_result.turn,
                reason="Canonical Story changed while the generated draft was in flight",
            )
            raise ConflictError(
                "Canonical Story changed while the generated draft was created",
                details={
                    "code": "STORY_GENERATION_RESULT_STALE",
                    "turn_id": str(text_result.turn.id),
                },
            )
        try:
            draft_text = render_story_markdown(text_result.value)
            # Defense in depth: the exact rendered draft handed to the existing
            # proposal service must satisfy its parser before proposal rows exist.
            parse_script_markdown(draft_text)
            proposal = await create_story_proposal(
                self._session,
                project_id=project.id,
                actor=actor,
                brief=request.brief,
                filename=request.filename,
                draft_text=draft_text,
                idempotency_key=request.request_key,
            )
        except Exception as exc:  # noqa: BLE001 - persist the post-model failure
            await self._record_proposal_failure(
                project=project,
                actor=actor,
                text_result=text_result,
                exc=exc,
            )
            if isinstance(exc, AppError):
                raise
            raise ValidationAppError(
                "generated Story draft could not form a typed proposal",
                details={
                    "code": "GENERATED_STORY_PROPOSAL_INVALID",
                    "manual_ok": True,
                    "turn_id": str(text_result.turn.id),
                },
            ) from exc
        await self._text_transport.mark_awaiting_user(
            text_result.turn,
            proposal_id=proposal.proposal.id,
        )
        await DirectorRuntimeStartService(
            self._session, settings=get_settings(),
        ).accept_existing_new_turn(
            project=project,
            actor=actor,
            turn=text_result.turn,
            proposal_id=proposal.proposal.id,
            created=text_result.turn_created,
        )
        await self._session.commit()
        return GeneratedStoryProposal(
            draft=text_result.value,
            draft_text=draft_text,
            proposal=proposal,
            turn=text_result.turn,
            evidence=text_result.evidence,
        )

    async def _story_context(self, project: Project) -> tuple[dict[str, object], dict[str, object]]:
        document = await self._session.scalar(
            select(ScriptDocument)
            .where(ScriptDocument.project_id == project.id)
            .order_by(ScriptDocument.created_at.desc(), ScriptDocument.id.desc())
            .limit(1)
        )
        episodes = list(
            (
                await self._session.execute(
                    select(Episode)
                    .where(Episode.project_id == project.id)
                    .order_by(Episode.episode_number, Episode.id)
                )
            )
            .scalars()
            .all()
        )
        scenes = (
            list(
                (
                    await self._session.execute(
                        select(Scene)
                        .where(Scene.episode_id.in_([episode.id for episode in episodes]))
                        .order_by(Scene.scene_number, Scene.id)
                    )
                )
                .scalars()
                .all()
            )
            if episodes
            else []
        )
        shots = (
            list(
                (
                    await self._session.execute(
                        select(Shot)
                        .where(
                            Shot.project_id == project.id,
                            Shot.scene_id.in_([scene.id for scene in scenes]),
                        )
                        .order_by(Shot.sort_order, Shot.shot_number, Shot.id)
                    )
                )
                .scalars()
                .all()
            )
            if scenes
            else []
        )
        context: dict[str, object] = {
            "document": (
                {
                    "filename": document.filename,
                    "content_hash": document.content_hash,
                    "version": document.version,
                }
                if document is not None
                else None
            ),
            "episodes": [
                {
                    "episode_number": episode.episode_number,
                    "title": episode.title,
                    "synopsis": episode.synopsis,
                    "version": episode.version,
                }
                for episode in episodes
            ],
            "scenes": [
                {
                    "scene_number": scene.scene_number,
                    "location_name": scene.location_name,
                    "time_of_day": scene.time_of_day,
                    "synopsis": scene.synopsis,
                    "version": scene.version,
                }
                for scene in scenes
            ],
            "shots": [
                {
                    "shot_number": shot.shot_number,
                    "scene_id": str(shot.scene_id),
                    "shot_type": shot.shot_type,
                    "camera_move": shot.camera_move,
                    "visual_description": shot.visual_description,
                    "dialogue": shot.dialogue,
                    "version": shot.version,
                }
                for shot in shots
            ],
        }
        versions: dict[str, object] = {
            "project": project.version,
            "script_document": document.version if document is not None else None,
            "episodes": {str(episode.id): episode.version for episode in episodes},
            "scenes": {str(scene.id): scene.version for scene in scenes},
            "shots": {str(shot.id): shot.version for shot in shots},
        }
        return context, versions

    async def _record_proposal_failure(
        self,
        *,
        project: Project,
        actor: User,
        text_result: StructuredDirectorTextResult[StoryDraftCandidate],
        exc: Exception,
    ) -> None:
        turn_id = text_result.turn.id
        workspace_id = project.workspace_id
        project_id = project.id
        actor_id = actor.id
        await self._session.rollback()
        await set_rls_context(
            self._session,
            user_id=actor_id,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        turn = await self._session.get(DirectorTurn, turn_id)
        if turn is not None:
            await self._text_transport.mark_failed(
                turn,
                reason=f"Story proposal creation failed: {type(exc).__name__}: {exc}",
                wait_reason="proposal_invalid",
            )


__all__ = [
    "GeneratedStoryProposal",
    "StoryDraftCandidate",
    "StoryGenerationRequest",
    "StoryGenerationService",
    "StorySceneDraft",
    "StoryShotDraft",
    "render_story_markdown",
]
