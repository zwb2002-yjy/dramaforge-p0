"""P7-03 Director Assistant context builder (03 §63).

Every turn re-reads current database facts (Project + visual standard, Scene,
Shot, Formal Assets, References, Current Model Capability, Current Experiments,
Open Annotations) and appends recent messages + the current user message.
Database facts always take priority over old chat.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.assets.models import Episode, Scene, Shot
from app.delivery.models import ReviewAnnotation
from app.director.models import DirectorMessage, DirectorThread
from app.execution.models import Artifact
from app.production.models import ShotExperiment, ShotReferenceBinding
from app.providers.model_profiles.service import ProductionModelProfileService


class AssistantContextRead(BaseModel):
    """Structured context handed to the Director Assistant each turn."""

    model_config = ConfigDict(extra="forbid")

    project: dict[str, object] = Field(default_factory=dict)
    scene: dict[str, object] | None = None
    shot: dict[str, object] | None = None
    model_capability: dict[str, object] = Field(default_factory=dict)
    creative_capabilities: dict[str, object] = Field(default_factory=dict)
    experiments: list[dict[str, object]] = Field(default_factory=list)
    open_annotations: list[dict[str, object]] = Field(default_factory=list)
    recent_messages: list[dict[str, object]] = Field(default_factory=list)
    current_user_message: str = ""
    context_priority: str = "database_facts"


class AssistantContextBuilder:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build(
        self,
        *,
        project: Project,
        thread: DirectorThread,
        current_user_message: str,
        recent_limit: int = 20,
    ) -> AssistantContextRead:
        ctx = AssistantContextRead(
            project={
                "id": str(project.id),
                "name": project.name,
                "aspect_ratio": project.aspect_ratio,
                "visual_standard": project.style_bible or {},
            },
            current_user_message=current_user_message,
        )

        scope_type = thread.scope_type
        scope_entity_id = thread.scope_entity_id
        if scope_type in ("scene", "shot"):
            scene = await self._session.get(Scene, scope_entity_id)
            if scene is not None:
                episode = await self._session.get(Episode, scene.episode_id)
                if episode is not None and episode.project_id == project.id:
                    ctx.scene = {
                        "id": str(scene.id),
                        "episode_id": str(scene.episode_id),
                        "scene_number": scene.scene_number,
                        "location_name": scene.location_name,
                    }
        if scope_type == "shot":
            shot = await self._session.get(Shot, scope_entity_id)
            if shot is not None and shot.project_id == project.id:
                ctx.shot = await self._shot_facts(project, shot)

        # Current model capability: effective project profile bindings.
        try:
            profile = await ProductionModelProfileService(
                self._session
            ).get_effective_for_project(project=project)
            if profile is not None:
                ctx.model_capability = {
                    "profile_id": str(profile.id),
                    "version": profile.version,
                    "bindings": dict(profile.bindings or {}),
                }
        except Exception:  # noqa: BLE001 - no profile yet is not fatal
            ctx.model_capability = {"bindings": {}}

        # Active creative capability provenance (CC10): frozen identities from
        # Scene.design_state / Shot.director_state (read-only). The assistant
        # reads these so it never invents hidden skills or silently overrides
        # the user's explicit capability selection.
        ctx.creative_capabilities = await self._creative_capability_facts(
            project=project, scope_type=thread.scope_type, scope_entity_id=thread.scope_entity_id
        )

        # Current experiments for the shot scope.
        if scope_type == "shot":
            rows = (
                await self._session.execute(
                    select(ShotExperiment).where(
                        ShotExperiment.project_id == project.id,
                        ShotExperiment.shot_id == scope_entity_id,
                    )
                )
            ).scalars().all()
            ctx.experiments = [
                {
                    "shot_experiment_id": str(row.id),
                    "status": row.status,
                    "model_overrides": row.model_overrides,
                }
                for row in rows
            ]

        # Open annotations for the shot.
        annotations = (
            await self._session.execute(
                select(ReviewAnnotation).where(
                    ReviewAnnotation.project_id == project.id,
                    ReviewAnnotation.shot_id == scope_entity_id,
                    ReviewAnnotation.status == "open",
                )
            )
        ).scalars().all()
        ctx.open_annotations = [
            {
                "id": str(row.id),
                "time_start": float(row.time_start) if row.time_start is not None else None,
                "time_end": float(row.time_end) if row.time_end is not None else None,
                "note": row.note,
                "severity": row.severity,
            }
            for row in annotations
        ]

        messages = (
            await self._session.execute(
                select(DirectorMessage)
                .where(DirectorMessage.thread_id == thread.id)
                .order_by(
                    DirectorMessage.created_at.asc(),
                    DirectorMessage.id.asc(),
                )
            )
        ).scalars().all()
        ctx.recent_messages = [
            {"role": message.role, "content": message.content}
            for message in messages[-recent_limit:]
        ]
        return ctx

    async def _creative_capability_facts(
        self,
        *,
        project: Project,
        scope_type: str,
        scope_entity_id: UUID,
    ) -> dict[str, object]:
        """Read frozen creative-capability provenance (read-only, no Provider).

        The provenance is written by the CreativeCapabilityCompiler into
        ``Scene.design_state`` / ``Shot.director_state`` under the
        ``creative_capabilities`` key.  If none is frozen yet, the assistant
        simply sees an empty selection (no hidden skill, no silent override).
        """
        state: dict[str, object] = {}
        if scope_type == "scene":
            scene = await self._session.get(Scene, scope_entity_id)
            if scene is not None:
                state = dict(scene.design_state or {})
        elif scope_type == "shot":
            shot = await self._session.get(Shot, scope_entity_id)
            if shot is not None:
                state = dict(shot.director_state or {})
                scene = await self._session.get(Scene, shot.scene_id)
                if scene is not None and isinstance(scene.design_state, dict):
                    state.setdefault("creative_capabilities", {})
                    state.setdefault("design", dict(scene.design_state or {}))
        frozen_raw = state.get("creative_capabilities")
        frozen = dict(frozen_raw) if isinstance(frozen_raw, dict) else {}
        # Lift any genre/skill/style provenance that may live under design.
        design = state.get("design")
        if isinstance(design, dict) and isinstance(design.get("creative_capabilities"), dict):
            for key, value in design["creative_capabilities"].items():
                frozen.setdefault(key, value)
        return frozen

    async def _shot_facts(self, project: Project, shot: Shot) -> dict[str, object]:
        formal_keyframe: dict[str, object] | None = None
        formal_video: dict[str, object] | None = None
        if shot.formal_keyframe_artifact_id is not None:
            artifact = await self._session.get(Artifact, shot.formal_keyframe_artifact_id)
            if artifact is not None:
                formal_keyframe = {
                    "artifact_id": str(artifact.id),
                    "content_hash": artifact.content_hash,
                    "mime_type": artifact.mime_type,
                }
        if shot.formal_video_artifact_id is not None:
            artifact = await self._session.get(Artifact, shot.formal_video_artifact_id)
            if artifact is not None:
                formal_video = {
                    "artifact_id": str(artifact.id),
                    "content_hash": artifact.content_hash,
                    "mime_type": artifact.mime_type,
                }
        references = (
            await self._session.execute(
                select(ShotReferenceBinding)
                .where(
                    ShotReferenceBinding.project_id == project.id,
                    ShotReferenceBinding.shot_id == shot.id,
                )
                .order_by(ShotReferenceBinding.sort_order)
            )
        ).scalars().all()
        return {
            "id": str(shot.id),
            "shot_number": shot.shot_number,
            "version": shot.version,
            "image_prompt": shot.image_prompt,
            "video_prompt": shot.video_prompt,
            "director_state": shot.director_state or {},
            "formal_keyframe": formal_keyframe,
            "formal_video": formal_video,
            "references": [
                {
                    "purpose": row.purpose,
                    "resolution_mode": row.resolution_mode,
                    "asset_id": str(row.asset_id) if row.asset_id else None,
                }
                for row in references
            ],
        }
