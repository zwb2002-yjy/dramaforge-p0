"""Shooting-plan Director use cases and deterministic production preflight."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.access.projects import ProjectService
from app.config import get_settings
from app.director.agent_runtime import DirectorAgentRuntime
from app.director.creative import EpisodeScriptPayload, StoryCorePayload
from app.director.enums import ArtifactKind, WorkflowStatus
from app.director.models import CreativeArtifactVersion, DirectorWorkflowRun, WorkflowStepRun
from app.director.service import DirectorService
from app.director.shooting import (
    CharacterBiblePayload,
    CostEstimatePayload,
    CostLine,
    SelectedModelPlan,
    SelectionPlanPayload,
    StoryboardPlanPayload,
    TrialPlanPayload,
    VisualBiblePayload,
    VoiceBiblePayload,
    build_risk_report,
    parse_character_bible,
    parse_storyboard_plan,
    parse_visual_bible,
    parse_voice_bible,
    validate_storyboard_against_story,
)
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.eligibility import evaluate_candidate
from app.providers.models import ProjectProviderBinding, ProviderConnection, ProviderModelBinding
from app.shared.errors import ConflictError, ValidationAppError


def _discrete_duration_values(raw: object) -> set[Decimal] | None:
    values: object = raw
    if isinstance(raw, dict):
        if set(raw) != {"allowed"}:
            return None
        values = raw.get("allowed")
    if not isinstance(values, list):
        values = [values]
    result: set[Decimal] = set()
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
            return None
        try:
            duration = Decimal(str(value))
        except (ArithmeticError, ValueError):
            return None
        if not duration.is_finite() or duration <= 0:
            return None
        result.add(duration)
    return result or None


def _video_preflight_blockers(
    *,
    operation_manifest: dict[str, object],
    project_aspect_ratio: str,
    requested_durations: frozenset[Decimal],
) -> list[str]:
    """Validate semantic video outputs against one selected model contract."""
    raw_constraints = operation_manifest.get("output_constraints")
    constraints = raw_constraints if isinstance(raw_constraints, dict) else {}
    blockers: list[str] = []

    declared_ratio = constraints.get("aspect_ratio")
    if declared_ratio == "adaptive":
        capabilities = operation_manifest.get("capabilities")
        raw_references = operation_manifest.get("reference_constraints")
        references = raw_references if isinstance(raw_references, dict) else {}
        first_frame = references.get("first_frame")
        inherits_from_exactly_one_first_frame = (
            isinstance(capabilities, list)
            and "video.i2v.first_frame" in capabilities
            and isinstance(first_frame, dict)
            and first_frame.get("min") == 1
            and first_frame.get("max") == 1
        )
        if (
            project_aspect_ratio not in {"9:16", "16:9"}
            or not inherits_from_exactly_one_first_frame
        ):
            blockers.append("MODEL_ASPECT_RATIO_INHERITANCE_UNVERIFIED")
    elif declared_ratio is None:
        blockers.append("MODEL_ASPECT_RATIO_UNVERIFIED")
    elif str(declared_ratio) != project_aspect_ratio:
        blockers.append("MODEL_ASPECT_RATIO_UNSUPPORTED")

    if "duration_seconds" in constraints:
        supported_durations = _discrete_duration_values(constraints["duration_seconds"])
        if supported_durations is None:
            blockers.append("MODEL_DURATION_UNVERIFIED")
        elif (
            not requested_durations
            or any(value != value.to_integral_value() for value in requested_durations)
            or not requested_durations <= supported_durations
        ):
            blockers.append("MODEL_DURATION_UNSUPPORTED")
    elif not ("num_frames" in constraints and "frame_rate" in constraints):
        blockers.append("MODEL_DURATION_UNVERIFIED")
    return blockers


class DirectorShootingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._director = DirectorService(session)
        self._runtime = DirectorAgentRuntime(session)
        self._projects = ProjectService(session)

    async def generate_shooting_package(
        self,
        *,
        project_id: UUID,
        actor: User,
        authorize_text_calls: bool,
        idempotency_key: str,
    ) -> tuple[
        CreativeArtifactVersion,
        CreativeArtifactVersion,
        CreativeArtifactVersion,
        CreativeArtifactVersion,
        CreativeArtifactVersion,
        CreativeArtifactVersion,
        CreativeArtifactVersion,
        CreativeArtifactVersion,
    ]:
        project, workflow = await self._shooting_context(project_id=project_id, actor=actor)
        existing = await self._director.find_step_run(
            project_id=project_id,
            actor=actor,
            idempotency_key=f"{idempotency_key}:package",
        )
        if existing is not None:
            if existing.status != "succeeded" or len(existing.output_version_refs) != 8:
                raise ConflictError("shooting package request exists without eight outputs")
            rows = await self._director.artifact_versions_by_ids(
                project_id=project_id,
                actor=actor,
                ids=[UUID(value) for value in existing.output_version_refs],
            )
            if len(rows) != 8:
                raise ConflictError("shooting package outputs are incomplete")
            return tuple(rows)  # type: ignore[return-value]
        if not authorize_text_calls:
            raise ValidationAppError(
                "text model authorization is required to develop the shooting package",
                details={"code": "TEXT_CALL_AUTHORIZATION_REQUIRED", "manual_ok": True},
            )
        story_row = await self._current_artifact(workflow, ArtifactKind.STORY_CORE)
        script_row = await self._current_artifact(workflow, ArtifactKind.EPISODE_SCRIPT)
        story = StoryCorePayload.model_validate(story_row.payload)
        script = EpisodeScriptPayload.model_validate(script_row.payload)

        character_bible, _agent, character_run = await self._runtime.run_text_skill(
            workspace_id=project.workspace_id,
            project_id=project.id,
            workflow_run_id=workflow.id,
            actor_id=actor.id,
            step_key="design_characters",
            skill_id="character_design",
            prompt=self._character_prompt(story),
            max_tokens=2600,
            parse=parse_character_bible,
            idempotency_key=f"{idempotency_key}:characters",
            input_version_refs=[str(story_row.id)],
            provider_kind="shooting_character_visual",
            provider_context={
                "story_core": story.model_dump(mode="json"),
                "aspect_ratio": project.aspect_ratio,
            },
        )
        assert isinstance(character_bible, CharacterBiblePayload)
        self._validate_character_bible_against_story(character_bible, story)

        visual_bible, _visual_agent, visual_run = await self._runtime.run_text_skill(
            workspace_id=project.workspace_id,
            project_id=project.id,
            workflow_run_id=workflow.id,
            actor_id=actor.id,
            step_key="design_visual_anchors",
            skill_id="visual_anchor_design",
            prompt=self._visual_prompt(project, story, character_bible),
            max_tokens=2000,
            parse=parse_visual_bible,
            idempotency_key=f"{idempotency_key}:visual",
            input_version_refs=[str(story_row.id)],
            provider_kind="shooting_visual",
            provider_context={
                "story_core": story.model_dump(mode="json"),
                "character_bible": character_bible.model_dump(mode="json"),
                "aspect_ratio": project.aspect_ratio,
            },
        )
        assert isinstance(visual_bible, VisualBiblePayload)
        if visual_bible.aspect_ratio != project.aspect_ratio:
            raise ValidationAppError(
                "visual bible aspect ratio differs from the project",
                details={"code": "ASPECT_RATIO_MISMATCH"},
            )

        voice, _voice_agent, voice_run = await self._runtime.run_text_skill(
            workspace_id=project.workspace_id,
            project_id=project.id,
            workflow_run_id=workflow.id,
            actor_id=actor.id,
            step_key="design_voices",
            skill_id="voice_design",
            prompt=self._voice_prompt(story, script),
            max_tokens=2200,
            parse=parse_voice_bible,
            idempotency_key=f"{idempotency_key}:voices",
            input_version_refs=[str(story_row.id), str(script_row.id)],
            provider_kind="shooting_voice",
            provider_context={
                "story_core": story.model_dump(mode="json"),
                "episode_script": script.model_dump(mode="json"),
            },
        )
        assert isinstance(voice, VoiceBiblePayload)
        self._validate_voice_bible(voice, story)

        storyboard, _board_agent, storyboard_run = await self._runtime.run_text_skill(
            workspace_id=project.workspace_id,
            project_id=project.id,
            workflow_run_id=workflow.id,
            actor_id=actor.id,
            step_key="create_storyboard",
            skill_id="storyboarding",
            prompt=self._storyboard_prompt(
                project=project,
                story=story,
                script=script,
                character_bible=character_bible,
                visual_bible=visual_bible,
                voice_bible=voice,
            ),
            max_tokens=5200,
            parse=parse_storyboard_plan,
            idempotency_key=f"{idempotency_key}:storyboard",
            input_version_refs=[str(story_row.id), str(script_row.id)],
            provider_kind="shooting_storyboard",
            provider_context={
                "story_core": story.model_dump(mode="json"),
                "episode_script": script.model_dump(mode="json"),
                "aspect_ratio": project.aspect_ratio,
            },
        )
        assert isinstance(storyboard, StoryboardPlanPayload)
        validate_storyboard_against_story(story=story, script=script, storyboard=storyboard)

        risk = build_risk_report(storyboard, character_count=len(story.characters))
        selection = await self._build_selection_plan(project=project, storyboard=storyboard)
        cost = self._build_cost_estimate(
            project=project,
            storyboard=storyboard,
            selection=selection,
            representative_shot_id=risk.representative_shot_id,
        )
        trial = TrialPlanPayload(
            representative_shot_id=risk.representative_shot_id,
            selection_reason=risk.representative_shot_reason,
            planned_operations=[
                "character_reference.generate",
                "keyframe.generate",
                "video.generate",
                "voice.generate",
                "quality.inspect",
            ],
            quality_dimensions=[
                "identity",
                "body_integrity",
                "voice_assignment",
                "voice_stability",
                "mouth_motion",
                "performance",
                "visual_style",
            ],
        )

        outputs: list[CreativeArtifactVersion] = []
        for kind, payload, run in (
            (ArtifactKind.CHARACTER_BIBLE, character_bible, character_run),
            (ArtifactKind.VISUAL_BIBLE, visual_bible, visual_run),
            (ArtifactKind.VOICE_BIBLE, voice, voice_run),
            (ArtifactKind.STORYBOARD_PLAN, storyboard, storyboard_run),
            (ArtifactKind.RISK_REPORT, risk, None),
            (ArtifactKind.SELECTION_PLAN, selection, None),
            (ArtifactKind.COST_ESTIMATE, cost, None),
            (ArtifactKind.TRIAL_PLAN, trial, None),
        ):
            outputs.append(
                await self._director.publish_artifact_version(
                    project_id=project.id,
                    actor=actor,
                    artifact_kind=kind,
                    payload=payload.model_dump(mode="json"),
                    source_kind="agent" if run is not None else "service",
                    source_run_id=run.agent_run_id if run is not None else None,
                    commit=False,
                )
            )
        package_run = WorkflowStepRun(
            project_id=project.id,
            workflow_run_id=workflow.id,
            step_key="preflight",
            skill_id="production_preflight",
            skill_version="1.0.0",
            execution_kind="domain_service",
            idempotency_key=f"{idempotency_key}:package",
            status="succeeded",
            input_version_refs=[str(story_row.id), str(script_row.id)],
            output_version_refs=[str(item.id) for item in outputs],
            service_run_ref=f"preflight:{workflow.id}:{idempotency_key}",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        self._session.add(package_run)
        visual_run.output_version_refs = [str(outputs[1].id)]
        character_run.output_version_refs = [str(outputs[0].id)]
        voice_run.output_version_refs = [str(outputs[2].id)]
        storyboard_run.output_version_refs = [str(outputs[3].id)]
        await self._session.commit()
        return tuple(outputs)  # type: ignore[return-value]

    async def _shooting_context(
        self, *, project_id: UUID, actor: User
    ) -> tuple[Project, DirectorWorkflowRun]:
        project = await self._projects.get_project_for_owner(project_id=project_id, actor=actor)
        workflow = await self._director.get_workflow(project_id=project_id, actor=actor)
        if workflow.status not in {
            WorkflowStatus.DRAFTING_SHOOTING_PLAN.value,
            WorkflowStatus.AWAITING_SHOOTING_CONFIRMATION.value,
        }:
            raise ValidationAppError("shooting stage is not writable")
        return project, workflow

    async def _current_artifact(
        self, workflow: DirectorWorkflowRun, kind: ArtifactKind
    ) -> CreativeArtifactVersion:
        raw = workflow.current_artifact_versions.get(kind.value)
        if raw is None:
            raise ValidationAppError(
                "confirmed creative input is missing",
                details={"code": "SHOOTING_INPUT_MISSING", "artifact_kind": kind.value},
            )
        row = await self._session.get(CreativeArtifactVersion, UUID(raw))
        if row is None or row.status != "locked":
            raise ValidationAppError(
                "shooting inputs must be confirmed and locked",
                details={"code": "SHOOTING_INPUT_NOT_LOCKED", "artifact_kind": kind.value},
            )
        return row

    async def _build_selection_plan(
        self, *, project: Project, storyboard: StoryboardPlanPayload
    ) -> SelectionPlanPayload:
        plans = [
            await self._purpose_plan(
                project=project,
                public_purpose="character_reference",
                binding_purpose="keyframe",
                operation="image.generate",
                required={"image.t2i"},
            ),
            await self._purpose_plan(
                project=project,
                public_purpose="keyframe",
                binding_purpose="keyframe",
                operation="image.generate",
                required={"image.i2i"},
            ),
            await self._purpose_plan(
                project=project,
                public_purpose="video",
                binding_purpose="video",
                operation="video.generate",
                required={"video.i2v.first_frame"},
                requested_video_durations=frozenset(
                    shot.duration_seconds for shot in storyboard.shots
                ),
            ),
            self._voice_plan(),
        ]
        status: Literal["ready", "configuration_required", "unsupported"] = (
            "unsupported"
            if any(item.status == "unsupported" for item in plans)
            else "configuration_required"
            if any(item.status == "configuration_required" for item in plans)
            else "ready"
        )
        return SelectionPlanPayload(status=status, plans=plans)

    @staticmethod
    def _voice_plan() -> SelectedModelPlan:
        settings = get_settings()
        if settings.tts_enabled:
            return SelectedModelPlan(
                purpose="voice",
                provider_type="local_tts",
                protocol_profile="espeak-ng-v1",
                model_id=settings.tts_engine,
                invoke_model_value=settings.tts_voice,
                required_capabilities=["audio.tts"],
                supported_capabilities=["audio.tts"],
                evidence={"configured": True, "local_execution": True},
                pricing_snapshot={
                    "unit_amount": "0",
                    "currency": "LOCAL",
                    "unit": "utterance",
                    "source": "local_zero_cost",
                },
                status="ready",
            )
        return SelectedModelPlan(
            purpose="voice",
            required_capabilities=["audio.tts"],
            status="configuration_required",
            blockers=["LOCAL_TTS_NOT_ENABLED"],
        )

    async def _purpose_plan(
        self,
        *,
        project: Project,
        public_purpose: Literal["character_reference", "keyframe", "video", "voice"],
        binding_purpose: str,
        operation: str,
        required: set[str],
        requested_video_durations: frozenset[Decimal] = frozenset(),
    ) -> SelectedModelPlan:
        project_binding = await self._session.scalar(
            select(ProjectProviderBinding).where(
                ProjectProviderBinding.project_id == project.id,
                ProjectProviderBinding.purpose == binding_purpose,
            )
        )
        if project_binding is None:
            return SelectedModelPlan(
                purpose=public_purpose,
                required_capabilities=sorted(required),
                status="configuration_required",
                blockers=[f"MODEL_BINDING_MISSING:{binding_purpose}"],
            )
        binding = await self._session.get(ProviderModelBinding, project_binding.model_binding_id)
        if binding is None:
            return SelectedModelPlan(
                purpose=public_purpose,
                required_capabilities=sorted(required),
                status="configuration_required",
                blockers=[f"MODEL_BINDING_NOT_FOUND:{binding_purpose}"],
            )
        connection = await self._session.get(ProviderConnection, binding.connection_id)
        entry = (
            await self._session.get(ModelCatalogEntry, binding.catalog_entry_id)
            if binding.catalog_entry_id is not None
            else None
        )
        if connection is None:
            return SelectedModelPlan(
                purpose=public_purpose,
                model_binding_id=binding.id,
                required_capabilities=sorted(required),
                status="configuration_required",
                blockers=["PROVIDER_CONNECTION_MISSING"],
            )
        evaluation = await evaluate_candidate(
            self._session,
            binding=binding,
            connection=connection,
            catalog_entry=entry,
            operation=operation,
            required_capabilities=frozenset(required),
        )
        all_blockers = [item.code for item in evaluation.issues]
        # Product quality evidence is created by the first budget-controlled
        # representative trial. Requiring it before that trial creates an
        # impossible cold-start loop. All other eligibility failures remain
        # fail-closed.
        blockers = [
            blocker
            for blocker in all_blockers
            if blocker != "MODEL_QUALITY_GATE_MISSING"
        ]
        manifest = dict(entry.capability_manifest_json or {}) if entry is not None else {}
        operations = manifest.get("operations")
        raw_operation_manifest = (
            operations.get(operation) if isinstance(operations, dict) else None
        )
        operation_manifest: dict[str, object] = (
            dict(raw_operation_manifest)
            if isinstance(raw_operation_manifest, dict)
            else {}
        )
        if public_purpose == "video":
            blockers.extend(
                _video_preflight_blockers(
                    operation_manifest=operation_manifest,
                    project_aspect_ratio=project.aspect_ratio,
                    requested_durations=requested_video_durations,
                )
            )
        blockers = list(dict.fromkeys(blockers))
        configuration_codes = {
            "MODEL_BINDING_DISABLED",
            "PROVIDER_CONNECTION_DISABLED",
            "MODEL_NOT_ACCOUNT_VERIFIED",
            "MODEL_QUALITY_GATE_MISSING",
            "MODEL_NOT_IN_CATALOG",
            "MODEL_NO_INVOKE_VALUE",
        }
        plan_status: Literal["ready", "configuration_required", "unsupported"] = (
            "ready"
            if not blockers
            else "configuration_required"
            if blockers and set(blockers) <= configuration_codes
            else "unsupported"
        )
        return SelectedModelPlan(
            purpose=public_purpose,
            model_binding_id=binding.id,
            provider_type=connection.provider_type,
            protocol_profile=connection.protocol_profile,
            model_id=binding.model_id,
            invoke_model_value=binding.invoke_model_value,
            manifest_hash=entry.contract_manifest_hash if entry is not None else None,
            required_capabilities=sorted(required),
            supported_capabilities=evaluation.supported_capabilities,
            evidence={
                **evaluation.evidence,
                "trial_only_until_quality_gated": not binding.quality_gated,
            },
            pricing_snapshot=(
                dict(binding.pricing_snapshot_json or {})
                if binding and binding.pricing_snapshot_json
                else dict(entry.pricing_snapshot_json or {})
                if entry
                else {}
            ),
            status=plan_status,
            blockers=blockers,
        )

    @staticmethod
    def _build_cost_estimate(
        *,
        project: Project,
        storyboard: StoryboardPlanPayload,
        selection: SelectionPlanPayload,
        representative_shot_id: str,
    ) -> CostEstimatePayload:
        currency = project.budget_currency.upper()
        model_status: dict[str, str] = {item.purpose: item.status for item in selection.plans}
        model_pricing = {item.purpose: item.pricing_snapshot for item in selection.plans}

        def line(purpose: str, quantity: int) -> CostLine:
            configured = model_status.get(purpose) == "ready"
            pricing = model_pricing.get(
                cast(Literal["character_reference", "keyframe", "video", "voice"], purpose)
            ) or {}
            raw_unit = pricing.get("unit_amount")
            raw_currency = str(pricing.get("currency") or currency).upper()
            if raw_currency == "LOCAL" and raw_unit is not None:
                raw_currency = currency
            try:
                unit = Decimal(str(raw_unit)) if raw_unit is not None else None
            except (ArithmeticError, ValueError):
                unit = None
            return CostLine(
                purpose=purpose,
                quantity=quantity,
                unit_amount=unit,
                estimated_amount=(unit * quantity if unit is not None else None),
                currency=raw_currency,
                status=(
                    "known"
                    if configured and unit is not None and raw_currency == currency
                    else "provider_not_reported"
                    if configured
                    else "configuration_required"
                ),
            )

        count = len(storyboard.shots)
        representative = next(
            shot
            for shot in storyboard.shots
            if shot.shot_id == representative_shot_id
        )
        trial_reference_count = len(set(representative.characters))
        production_reference_count = sum(
            len(set(shot.characters)) for shot in storyboard.shots
        )
        trial = [
            line("character_reference", trial_reference_count),
            line("keyframe", 1),
            line("video", 1),
            line("voice", 1),
        ]
        production = [
            line("character_reference", production_reference_count),
            line("keyframe", count),
            line("video", count),
            line("voice", count),
        ]
        repair = [line("keyframe", 1), line("video", 1), line("voice", 1)]

        def total(lines: list[CostLine]) -> Decimal | None:
            values = [item.estimated_amount for item in lines]
            return (
                sum((value for value in values if value is not None), Decimal("0"))
                if all(value is not None for value in values)
                else None
            )

        return CostEstimatePayload(
            pricing_snapshot_id=f"preflight-{datetime.now(UTC).date().isoformat()}",
            currency=currency,
            trial=trial,
            production=production,
            repair=repair,
            trial_total=total(trial),
            production_total=total(production),
            repair_total=total(repair),
            disclaimer=(
                "The selected providers do not expose a verified price in the current "
                "catalog. The user must set a hard authorization limit before media calls."
            ),
        )

    @staticmethod
    def _validate_character_bible_against_story(
        bible: CharacterBiblePayload, story: StoryCorePayload
    ) -> None:
        expected = [item.name for item in story.characters]
        actual = [item.name for item in bible.characters]
        if actual != expected:
            raise ValidationAppError(
                "character bible must preserve the locked story cast in order",
                details={"code": "CHARACTER_BIBLE_CAST_MISMATCH"},
            )

    @staticmethod
    def _validate_voice_bible(bible: VoiceBiblePayload, story: StoryCorePayload) -> None:
        if [item.character_name for item in bible.voices] != [
            item.name for item in story.characters
        ]:
            raise ValidationAppError(
                "voice bible must map every locked character exactly once",
                details={"code": "VOICE_BIBLE_CAST_MISMATCH"},
            )

    @staticmethod
    def _character_prompt(story: StoryCorePayload) -> str:
        return (
            "You are the casting department for a fictional short drama. "
            "Return ONLY a character_bible JSON object. Never use or request a "
            "real person's photo. character_bible policy must be fictional_characters_only, "
            "real_person_reference_allowed false, and exactly preserve every input character "
            "name/order. Each character needs character_id, name, age_range, facial_features, "
            "hair, body_shape, wardrobe, distinguishing_features, locked_prompt and "
            "negative_prompt. Make "
            "characters visually distinguishable without stereotypes. Story:\n"
            f"{json.dumps(story.model_dump(mode='json'), ensure_ascii=False)}"
        )

    @staticmethod
    def _visual_prompt(
        project: Project,
        story: StoryCorePayload,
        character_bible: CharacterBiblePayload,
    ) -> str:
        inputs = {
            "story": story.model_dump(mode="json"),
            "characters": character_bible.model_dump(mode="json"),
        }
        return (
            "You are a visual director. Return ONLY a visual_bible JSON object with medium "
            "photorealistic_live_action, exact aspect_ratio, era_and_setting, color_palette, "
            "lighting, lens_language, continuity_rules and preview_is_generated_media false. "
            "No generated image is being requested in this planning step. Exact aspect ratio: "
            f"{project.aspect_ratio}. Inputs:\n"
            f"{json.dumps(inputs, ensure_ascii=False)}"
        )

    @staticmethod
    def _voice_prompt(story: StoryCorePayload, script: EpisodeScriptPayload) -> str:
        inputs = {
            "story": story.model_dump(mode="json"),
            "script": script.model_dump(mode="json"),
        }
        return (
            "You are a Mandarin voice director. Return ONLY JSON with language zh-CN, "
            "voice_clone_allowed false and voices. Preserve every story character in order. "
            "Each voice needs character_id, character_name, voice_description, pace "
            "slow|medium|fast, emotional_range, voice_clone false. Do not imitate a real "
            "person. Inputs:\n"
            f"{json.dumps(inputs, ensure_ascii=False)}"
        )

    @staticmethod
    def _storyboard_prompt(
        *,
        project: Project,
        story: StoryCorePayload,
        script: EpisodeScriptPayload,
        character_bible: CharacterBiblePayload,
        visual_bible: VisualBiblePayload,
        voice_bible: VoiceBiblePayload,
    ) -> str:
        inputs = {
            "story": story.model_dump(mode="json"),
            "script": script.model_dump(mode="json"),
            "characters": character_bible.model_dump(mode="json"),
            "visual": visual_bible.model_dump(mode="json"),
            "voices": voice_bible.model_dump(mode="json"),
        }
        return (
            "You are a short-drama storyboard director. Return ONLY JSON matching: "
            "template_key live_action_dialogue_short_v1, exact aspect_ratio, exact "
            "target_duration_seconds, and 3-6 ordered shots. shot_id must be shot-1...; "
            "durations total the target within one second. Each shot needs location, "
            "time_of_day, shot_type, camera_move, 1-2 character names, action, dialogue, "
            "image_prompt, video_prompt and transition. Preserve every locked dialogue line "
            "verbatim, in original order and exactly once. Prefer singles/over-shoulder cuts "
            "over two-front-facing-character frames. Image/video prompts must include the "
            "locked character and visual anchors but stay provider-neutral. Exact aspect "
            f"ratio: {project.aspect_ratio}. Inputs:\n{json.dumps(inputs, ensure_ascii=False)}"
        )
