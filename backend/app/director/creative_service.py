"""Creative-stage Director use cases: concepts, preference card and story package."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.access.projects import ProjectService
from app.director.agent_runtime import DirectorAgentRuntime
from app.director.creative import (
    ConceptSetPayload,
    PreferenceUnderstandingPayload,
    StoryDraftPayload,
    canonicalize_dialogue_speakers,
    canonicalize_self_variant_characters,
    parse_concept_set,
    parse_preference_understanding,
    parse_story_draft,
    review_story_deterministically,
)
from app.director.enums import ArtifactKind, WorkflowStatus
from app.director.models import CreativeArtifactVersion, DirectorWorkflowRun
from app.director.service import DirectorService
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError


class DirectorCreativeService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._director = DirectorService(session)
        self._runtime = DirectorAgentRuntime(session)
        self._projects = ProjectService(session)

    async def generate_concepts(
        self,
        *,
        project_id: UUID,
        actor: User,
        entry_mode: str,
        creation_goal: str | None,
        idea: str,
        script_text: str,
        adaptation_mode: str | None,
        source_rights_confirmed: bool,
        confirmed_preference_version_id: UUID | None,
        authorize_text_call: bool,
        idempotency_key: str,
    ) -> CreativeArtifactVersion:
        project, workflow = await self._creative_context(project_id=project_id, actor=actor)
        existing = await self._existing_single_output(
            project_id=project_id,
            actor=actor,
            idempotency_key=idempotency_key,
            artifact_kind=ArtifactKind.CONCEPT_SET,
        )
        if existing is not None:
            return existing
        if not authorize_text_call:
            raise ValidationAppError(
                "text model authorization is required to generate concepts",
                details={"code": "TEXT_CALL_AUTHORIZATION_REQUIRED", "manual_ok": True},
            )
        preference_summary = ""
        preference_refs: list[str] = []
        if confirmed_preference_version_id is not None:
            preference = await self._artifact(
                project_id=project_id,
                version_id=confirmed_preference_version_id,
                expected_kind=ArtifactKind.PREFERENCE_UNDERSTANDING,
            )
            validated_preference = PreferenceUnderstandingPayload.model_validate(preference.payload)
            preference_summary = validated_preference.interpretation_summary
            preference_refs.append(str(preference.id))
        context: dict[str, object] = {
            "entry_mode": entry_mode,
            "creation_goal": creation_goal,
            "idea": idea,
            "script_text": script_text,
            "adaptation_mode": adaptation_mode,
            "source_rights_confirmed": source_rights_confirmed,
            "preference_summary": preference_summary,
        }
        prompt = self._concept_prompt(context)
        parsed, _agent, step_run = await self._runtime.run_text_skill(
            workspace_id=project.workspace_id,
            project_id=project_id,
            workflow_run_id=workflow.id,
            actor_id=actor.id,
            step_key="develop_story",
            skill_id="story_development",
            prompt=prompt,
            max_tokens=2800,
            parse=parse_concept_set,
            idempotency_key=idempotency_key,
            input_version_refs=preference_refs,
            provider_kind="concept_set",
            provider_context=context,
        )
        assert isinstance(parsed, ConceptSetPayload)
        version = await self._director.publish_artifact_version(
            project_id=project_id,
            actor=actor,
            artifact_kind=ArtifactKind.CONCEPT_SET,
            payload=parsed.model_dump(mode="json"),
            source_kind="agent",
            source_run_id=step_run.agent_run_id,
            commit=False,
        )
        step_run.output_version_refs = [str(version.id)]
        await self._session.commit()
        return version

    async def interpret_preferences(
        self,
        *,
        project_id: UUID,
        actor: User,
        source_concept_version_id: UUID,
        feedback: str,
        authorize_text_call: bool,
        idempotency_key: str,
    ) -> CreativeArtifactVersion:
        project, workflow = await self._creative_context(project_id=project_id, actor=actor)
        existing = await self._existing_single_output(
            project_id=project_id,
            actor=actor,
            idempotency_key=idempotency_key,
            artifact_kind=ArtifactKind.PREFERENCE_UNDERSTANDING,
        )
        if existing is not None:
            return existing
        concept_version = await self._artifact(
            project_id=project_id,
            version_id=source_concept_version_id,
            expected_kind=ArtifactKind.CONCEPT_SET,
        )
        if not authorize_text_call:
            raise ValidationAppError(
                "text model authorization is required to interpret preferences",
                details={"code": "TEXT_CALL_AUTHORIZATION_REQUIRED"},
            )
        prompt = (
            "You are an AI director interpreting creator feedback. Return ONLY JSON with "
            "liked, disliked, inferred_preferences, avoid, interpretation_summary. "
            "Do not rewrite the concepts and do not assume approval. Concepts:\n"
            f"{json.dumps(concept_version.payload, ensure_ascii=False)}\n"
            f"Creator feedback:\n{feedback}"
        )
        parsed, _agent, step_run = await self._runtime.run_text_skill(
            workspace_id=project.workspace_id,
            project_id=project_id,
            workflow_run_id=workflow.id,
            actor_id=actor.id,
            step_key="develop_story",
            skill_id="story_development",
            prompt=prompt,
            max_tokens=1200,
            parse=parse_preference_understanding,
            idempotency_key=idempotency_key,
            input_version_refs=[str(concept_version.id)],
            provider_kind="preference_understanding",
            provider_context={"feedback": feedback},
        )
        assert isinstance(parsed, PreferenceUnderstandingPayload)
        version = await self._director.publish_artifact_version(
            project_id=project_id,
            actor=actor,
            artifact_kind=ArtifactKind.PREFERENCE_UNDERSTANDING,
            payload=parsed.model_dump(mode="json"),
            source_kind="agent",
            source_run_id=step_run.agent_run_id,
            commit=False,
        )
        step_run.output_version_refs = [str(version.id)]
        await self._session.commit()
        return version

    async def generate_creative_package(
        self,
        *,
        project_id: UUID,
        actor: User,
        concept_version_id: UUID,
        selected_concept_id: str,
        theme: str,
        core_conflict: str,
        emotional_direction: str,
        ending: str,
        authorize_text_call: bool,
        idempotency_key: str,
    ) -> tuple[CreativeArtifactVersion, CreativeArtifactVersion, CreativeArtifactVersion]:
        project, workflow = await self._creative_context(project_id=project_id, actor=actor)
        existing_run = await self._director.find_step_run(
            project_id=project_id, actor=actor, idempotency_key=idempotency_key
        )
        if existing_run is not None:
            if existing_run.status != "succeeded" or len(existing_run.output_version_refs) != 3:
                raise ConflictError(
                    "creative package request already exists without three completed outputs"
                )
            outputs = await self._director.artifact_versions_by_ids(
                project_id=project_id,
                ids=[UUID(value) for value in existing_run.output_version_refs],
                actor=actor,
            )
            if len(outputs) != 3:
                raise ConflictError("creative package outputs are incomplete")
            return outputs[0], outputs[1], outputs[2]
        concept_version = await self._artifact(
            project_id=project_id,
            version_id=concept_version_id,
            expected_kind=ArtifactKind.CONCEPT_SET,
        )
        concept_set = ConceptSetPayload.model_validate(concept_version.payload)
        if selected_concept_id not in {item.concept_id for item in concept_set.concepts}:
            raise ValidationAppError("selected_concept_id is not in the concept version")
        if not authorize_text_call:
            raise ValidationAppError(
                "text model authorization is required to develop the creative package",
                details={"code": "TEXT_CALL_AUTHORIZATION_REQUIRED", "manual_ok": True},
            )
        locked_choices: dict[str, object] = {
            "selected_concept_id": selected_concept_id,
            "theme": theme,
            "core_conflict": core_conflict,
            "emotional_direction": emotional_direction,
            "ending": ending,
        }
        prompt = (
            "You are a short-drama head writer. Develop the selected concept while preserving "
            "the creator's locked theme, conflict, emotion and ending. Return ONLY JSON with "
            "story_core and episode_script. story_core requires selected_concept_id, theme, "
            "core_conflict, emotional_direction, ending, characters(name, identity, desire, "
            "fear_or_cost). episode_script requires title, target_duration_seconds 15-30, "
            "setup, turn, ending and dialogue(speaker,text,emotion). Use 1-2 main characters "
            "where possible and concise Mandarin dialogue. A future/past self, inner voice, "
            "or self-recording is the same character: keep one character entry and the same "
            "speaker name unless a genuinely different person appears.\nConcept set:\n"
            f"{json.dumps(concept_version.payload, ensure_ascii=False)}\nLocked choices:\n"
            f"{json.dumps(locked_choices, ensure_ascii=False)}"
        )
        draft, _agent, step_run = await self._runtime.run_text_skill(
            workspace_id=project.workspace_id,
            project_id=project_id,
            workflow_run_id=workflow.id,
            actor_id=actor.id,
            step_key="develop_story",
            skill_id="story_development",
            prompt=prompt,
            max_tokens=3200,
            parse=parse_story_draft,
            idempotency_key=idempotency_key,
            input_version_refs=[str(concept_version.id)],
            provider_kind="creative_story",
            provider_context=locked_choices,
        )
        assert isinstance(draft, StoryDraftPayload)
        # LLM output cannot overrule the creator's explicitly locked story choices.
        story_core = draft.story_core.model_copy(update=locked_choices)
        draft = draft.model_copy(update={"story_core": story_core})
        draft = canonicalize_self_variant_characters(draft)
        draft = canonicalize_dialogue_speakers(draft)
        review = review_story_deterministically(draft)
        story_version = await self._director.publish_artifact_version(
            project_id=project_id,
            actor=actor,
            artifact_kind=ArtifactKind.STORY_CORE,
            payload=draft.story_core.model_dump(mode="json"),
            source_kind="agent",
            source_run_id=step_run.agent_run_id,
            commit=False,
        )
        script_version = await self._director.publish_artifact_version(
            project_id=project_id,
            actor=actor,
            artifact_kind=ArtifactKind.EPISODE_SCRIPT,
            payload=draft.episode_script.model_dump(mode="json"),
            source_kind="agent",
            source_run_id=step_run.agent_run_id,
            commit=False,
        )
        review_version = await self._director.publish_artifact_version(
            project_id=project_id,
            actor=actor,
            artifact_kind=ArtifactKind.STORY_REVIEW,
            payload=review.model_dump(mode="json"),
            source_kind="service",
            source_run_id=None,
            commit=False,
        )
        step_run.output_version_refs = [
            str(story_version.id),
            str(script_version.id),
            str(review_version.id),
        ]
        await self._session.commit()
        return story_version, script_version, review_version

    async def _creative_context(
        self, *, project_id: UUID, actor: User
    ) -> tuple[Project, DirectorWorkflowRun]:
        project = await self._projects.get_project_for_owner(project_id=project_id, actor=actor)
        workflow = await self._director.get_workflow(project_id=project_id, actor=actor)
        if workflow.status not in {
            WorkflowStatus.DRAFTING_CREATIVE.value,
            WorkflowStatus.AWAITING_CREATIVE_CONFIRMATION.value,
        }:
            raise ValidationAppError("creative stage is not writable")
        return project, workflow

    async def _artifact(
        self,
        *,
        project_id: UUID,
        version_id: UUID,
        expected_kind: ArtifactKind,
    ) -> CreativeArtifactVersion:
        version = await self._session.get(CreativeArtifactVersion, version_id)
        if (
            version is None
            or version.project_id != project_id
            or version.artifact_kind != expected_kind.value
        ):
            raise NotFoundError(f"{expected_kind.value} version not found")
        return version

    async def _existing_single_output(
        self,
        *,
        project_id: UUID,
        actor: User,
        idempotency_key: str,
        artifact_kind: ArtifactKind,
    ) -> CreativeArtifactVersion | None:
        run = await self._director.find_step_run(
            project_id=project_id, actor=actor, idempotency_key=idempotency_key
        )
        if run is None:
            return None
        if run.status != "succeeded" or len(run.output_version_refs) != 1:
            raise ConflictError("Director Skill request already exists but is not reusable")
        version = await self._artifact(
            project_id=project_id,
            version_id=UUID(run.output_version_refs[0]),
            expected_kind=artifact_kind,
        )
        return version

    @staticmethod
    def _concept_prompt(context: dict[str, object]) -> str:
        trend_rule = (
            "For high_traffic or balanced goals, use only the supplied abstract trend themes. "
            "Never copy a known video, author, dialogue or character. "
        )
        return (
            "You are an AI director helping a novice creator find a story they feel ownership "
            "of. Return ONLY JSON matching: entry_mode, creation_goal, adaptation_mode, "
            "source_rights_confirmed, preference_summary, concepts. concepts must contain "
            "exactly three distinct originals with concept_id, title, logline, theme, "
            "character_relationship, core_conflict, ending_direction, why_it_fits. Each must "
            "fit a 15-30 second photorealistic dialogue-driven short with 1-2 main characters. "
            f"{trend_rule}Input:\n{json.dumps(context, ensure_ascii=False)}"
        )
