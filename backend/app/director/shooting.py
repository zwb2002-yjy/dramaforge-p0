"""Shooting-plan contracts and deterministic preflight checks.

The LLM proposes creative details.  The validators and preflight rules remain
deterministic so a fluent response cannot silently waive a production risk.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.director.creative import EpisodeScriptPayload, StoryCorePayload, parse_json_object
from app.shared.errors import ValidationAppError


class CharacterVisualAnchor(BaseModel):
    character_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    age_range: str = Field(min_length=1, max_length=80)
    facial_features: str = Field(min_length=1, max_length=500)
    hair: str = Field(min_length=1, max_length=300)
    body_shape: str = Field(min_length=1, max_length=300)
    wardrobe: str = Field(min_length=1, max_length=500)
    distinguishing_features: list[str] = Field(default_factory=list, max_length=6)
    locked_prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str = Field(default="", max_length=1000)


class CharacterBiblePayload(BaseModel):
    policy: Literal["fictional_characters_only"] = "fictional_characters_only"
    real_person_reference_allowed: Literal[False] = False
    characters: list[CharacterVisualAnchor] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_unique_characters(self) -> CharacterBiblePayload:
        ids = {item.character_id for item in self.characters}
        names = {item.name for item in self.characters}
        if len(ids) != len(self.characters) or len(names) != len(self.characters):
            raise ValueError("character ids and names must be unique")
        return self


class VisualBiblePayload(BaseModel):
    medium: Literal["photorealistic_live_action"] = "photorealistic_live_action"
    aspect_ratio: Literal["9:16", "16:9"]
    era_and_setting: str = Field(min_length=1, max_length=500)
    color_palette: str = Field(min_length=1, max_length=400)
    lighting: str = Field(min_length=1, max_length=400)
    lens_language: str = Field(min_length=1, max_length=500)
    continuity_rules: list[str] = Field(min_length=1, max_length=12)
    preview_is_generated_media: Literal[False] = False


class VoiceDesign(BaseModel):
    character_id: str = Field(min_length=1, max_length=80)
    character_name: str = Field(min_length=1, max_length=80)
    voice_description: str = Field(min_length=1, max_length=500)
    pace: Literal["slow", "medium", "fast"] = "medium"
    emotional_range: list[str] = Field(min_length=1, max_length=8)
    voice_clone: Literal[False] = False


class VoiceBiblePayload(BaseModel):
    language: Literal["zh-CN"] = "zh-CN"
    voice_clone_allowed: Literal[False] = False
    voices: list[VoiceDesign] = Field(min_length=1, max_length=4)


class ShotDialogue(BaseModel):
    speaker: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=300)
    emotion: str = Field(min_length=1, max_length=100)


class StoryboardShot(BaseModel):
    shot_id: str = Field(pattern=r"^shot-[1-6]$")
    shot_number: int = Field(ge=1, le=6)
    duration_seconds: Decimal = Field(ge=Decimal("2.0"), le=Decimal("10.0"))
    location: str = Field(min_length=1, max_length=300)
    time_of_day: str = Field(min_length=1, max_length=80)
    shot_type: Literal["wide", "medium", "medium_close", "close", "over_shoulder", "insert"]
    camera_move: Literal["static", "push_in", "pull_out", "pan", "tracking"]
    characters: list[str] = Field(min_length=1, max_length=2)
    action: str = Field(min_length=1, max_length=500)
    dialogue: list[ShotDialogue] = Field(default_factory=list, max_length=4)
    image_prompt: str = Field(min_length=1, max_length=3000)
    video_prompt: str = Field(min_length=1, max_length=3000)
    transition: str = Field(min_length=1, max_length=200)


class StoryboardPlanPayload(BaseModel):
    template_key: Literal["live_action_dialogue_short_v1"] = "live_action_dialogue_short_v1"
    aspect_ratio: Literal["9:16", "16:9"]
    target_duration_seconds: int = Field(ge=15, le=30)
    shots: list[StoryboardShot] = Field(min_length=3, max_length=6)

    @model_validator(mode="after")
    def validate_shot_sequence(self) -> StoryboardPlanPayload:
        expected = list(range(1, len(self.shots) + 1))
        if [item.shot_number for item in self.shots] != expected:
            raise ValueError("shot_number must be a contiguous ordered sequence")
        if [item.shot_id for item in self.shots] != [f"shot-{i}" for i in expected]:
            raise ValueError("shot_id must match the ordered shot number")
        total = sum((item.duration_seconds for item in self.shots), Decimal("0"))
        if abs(total - Decimal(self.target_duration_seconds)) > Decimal("1.0"):
            raise ValueError("shot durations must total the target duration within one second")
        return self


class RiskItem(BaseModel):
    risk_id: str = Field(min_length=1, max_length=100)
    shot_id: str | None = Field(default=None, max_length=40)
    category: Literal[
        "identity", "multi_person", "motion", "lip_sync", "continuity", "duration", "model"
    ]
    severity: Literal["info", "warning", "blocking"]
    evidence: str = Field(min_length=1, max_length=1000)
    mitigation: str = Field(min_length=1, max_length=1000)
    requires_trial: bool = False


class RiskReportPayload(BaseModel):
    policy_id: Literal["live-dialogue-preflight-v1"] = "live-dialogue-preflight-v1"
    status: Literal["ready", "needs_revision", "blocked"]
    representative_shot_id: str = Field(pattern=r"^shot-[1-6]$")
    representative_shot_reason: str = Field(min_length=1, max_length=1000)
    risks: list[RiskItem] = Field(default_factory=list, max_length=40)


class SelectedModelPlan(BaseModel):
    purpose: Literal["character_reference", "keyframe", "video", "voice"]
    model_binding_id: UUID | None = None
    provider_type: str | None = None
    protocol_profile: str | None = None
    model_id: str | None = None
    invoke_model_value: str | None = None
    manifest_hash: str | None = None
    required_capabilities: list[str] = Field(default_factory=list)
    supported_capabilities: list[str] = Field(default_factory=list)
    evidence: dict[str, bool] = Field(default_factory=dict)
    pricing_snapshot: dict[str, object] = Field(default_factory=dict)
    status: Literal["ready", "configuration_required", "unsupported"]
    blockers: list[str] = Field(default_factory=list)


class SelectionPlanPayload(BaseModel):
    policy_id: Literal["director-model-selection-v1"] = "director-model-selection-v1"
    status: Literal["ready", "configuration_required", "unsupported"]
    plans: list[SelectedModelPlan] = Field(min_length=3, max_length=4)
    fallback_allowed: Literal[False] = False
    advanced_parameters_hidden_in_quick_mode: Literal[True] = True


class CostLine(BaseModel):
    purpose: str = Field(min_length=1, max_length=80)
    quantity: int = Field(ge=1, le=100)
    unit_amount: Decimal | None = Field(default=None, ge=0)
    estimated_amount: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(min_length=3, max_length=3)
    status: Literal["known", "provider_not_reported", "configuration_required"]


class CostEstimatePayload(BaseModel):
    pricing_snapshot_id: str = Field(min_length=1, max_length=160)
    currency: str = Field(min_length=3, max_length=3)
    trial: list[CostLine] = Field(min_length=1)
    production: list[CostLine] = Field(min_length=1)
    repair: list[CostLine] = Field(min_length=1)
    trial_total: Decimal | None = Field(default=None, ge=0)
    production_total: Decimal | None = Field(default=None, ge=0)
    repair_total: Decimal | None = Field(default=None, ge=0)
    requires_user_budget_limit: Literal[True] = True
    disclaimer: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_one_currency(self) -> CostEstimatePayload:
        expected = self.currency.upper()
        mismatched = [
            item.purpose
            for item in [*self.trial, *self.production, *self.repair]
            if item.currency.upper() != expected
        ]
        if mismatched:
            raise ValueError("all cost lines must use the estimate currency")
        return self


class TrialPlanPayload(BaseModel):
    policy_id: Literal["representative-shot-v1"] = "representative-shot-v1"
    representative_shot_id: str = Field(pattern=r"^shot-[1-6]$")
    selection_reason: str = Field(min_length=1, max_length=1000)
    planned_operations: list[str] = Field(min_length=1, max_length=12)
    quality_dimensions: list[str] = Field(min_length=1, max_length=12)
    budget_authorization_required: Literal[True] = True


class QualityDimensionResult(BaseModel):
    dimension: Literal[
        "request_contract",
        "identity",
        "technical_integrity",
        "voice_assignment",
        "mouth_motion",
        "continuity",
        "narrative_and_performance",
    ]
    status: Literal["passed", "warning", "needs_human", "blocked", "not_applicable"]
    summary: str = Field(min_length=1, max_length=1000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=30)
    signals: dict[str, object] = Field(default_factory=dict)


class QualityReportPayload(BaseModel):
    policy_id: Literal["live-dialogue-quality-v1"] = "live-dialogue-quality-v1"
    batch_id: UUID
    logical_shot_id: str = Field(pattern=r"^shot-[1-6]$")
    overall_status: Literal["passed", "warning", "needs_human", "blocked"]
    dimensions: list[QualityDimensionResult] = Field(min_length=7, max_length=7)
    hard_blockers: list[str] = Field(default_factory=list, max_length=30)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    recommended_action: Literal["accept", "review", "repair", "stop"]


class TrialReviewPayload(BaseModel):
    batch_id: UUID
    quality_report_version_id: UUID
    decision: Literal["accept", "repair", "stop"]
    accepted_quality: bool
    user_note: str = Field(default="", max_length=4000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_acceptance(self) -> TrialReviewPayload:
        if self.accepted_quality != (self.decision == "accept"):
            raise ValueError("accepted_quality must match the accept decision")
        return self


class ProductionQualityReportPayload(BaseModel):
    policy_id: Literal["live-dialogue-quality-v1"] = "live-dialogue-quality-v1"
    batch_id: UUID
    shot_reports: list[QualityReportPayload] = Field(min_length=1, max_length=6)
    overall_status: Literal["passed", "warning", "needs_human", "blocked"]
    hard_blockers: list[str] = Field(default_factory=list, max_length=180)

    @model_validator(mode="after")
    def validate_reports(self) -> ProductionQualityReportPayload:
        if any(report.batch_id != self.batch_id for report in self.shot_reports):
            raise ValueError("every shot report must belong to the production batch")
        expected = (
            "blocked"
            if self.hard_blockers
            or any(report.overall_status == "blocked" for report in self.shot_reports)
            else "needs_human"
            if any(report.overall_status == "needs_human" for report in self.shot_reports)
            else "warning"
            if any(report.overall_status == "warning" for report in self.shot_reports)
            else "passed"
        )
        if self.overall_status != expected:
            raise ValueError("overall_status must be derived from shot reports")
        return self


class ProductionReviewPayload(BaseModel):
    batch_id: UUID
    quality_report_version_id: UUID
    decisions: dict[str, Literal["accept", "repair", "stop"]] = Field(
        min_length=1, max_length=6
    )
    user_note: str = Field(default="", max_length=4000)
    accepted_shot_ids: list[str] = Field(default_factory=list, max_length=6)
    repair_shot_ids: list[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def validate_decisions(self) -> ProductionReviewPayload:
        accepted = sorted(key for key, value in self.decisions.items() if value == "accept")
        repairs = sorted(key for key, value in self.decisions.items() if value == "repair")
        if sorted(self.accepted_shot_ids) != accepted:
            raise ValueError("accepted_shot_ids must match decisions")
        if sorted(self.repair_shot_ids) != repairs:
            raise ValueError("repair_shot_ids must match decisions")
        return self


class RepairChange(BaseModel):
    target: Literal["prompt", "reference", "model", "parameter", "storyboard"]
    summary: str = Field(min_length=1, max_length=1000)
    preview_before_ref: str | None = Field(default=None, max_length=500)
    preview_after_ref: str | None = Field(default=None, max_length=500)


class RepairOptionPayload(BaseModel):
    repair_option_id: str = Field(pattern=r"^repair-[a-f0-9]{12}$")
    title: str = Field(min_length=1, max_length=200)
    diagnosis: str = Field(min_length=1, max_length=2000)
    affected_shot_ids: list[str] = Field(min_length=1, max_length=6)
    invalidated_node_keys: list[str] = Field(min_length=1, max_length=20)
    reusable_artifact_ids: list[str] = Field(default_factory=list, max_length=50)
    changes: list[RepairChange] = Field(min_length=1, max_length=10)
    estimated_cost: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(min_length=3, max_length=3)
    estimated_time_seconds: int | None = Field(default=None, ge=0)
    residual_risks: list[str] = Field(default_factory=list, max_length=20)


class RepairPlanPayload(BaseModel):
    batch_id: UUID
    quality_report_version_id: UUID
    options: list[RepairOptionPayload] = Field(min_length=2, max_length=3)
    additional_budget_required: Literal[True] = True

    @model_validator(mode="after")
    def validate_unique_options(self) -> RepairPlanPayload:
        ids = [option.repair_option_id for option in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError("repair option ids must be unique")
        return self


class ShootingDraftPayload(BaseModel):
    character_bible: CharacterBiblePayload
    visual_bible: VisualBiblePayload
    voice_bible: VoiceBiblePayload
    storyboard_plan: StoryboardPlanPayload


class CharacterVisualDraftPayload(BaseModel):
    character_bible: CharacterBiblePayload
    visual_bible: VisualBiblePayload


def parse_character_bible(text: str) -> CharacterBiblePayload:
    return CharacterBiblePayload.model_validate(parse_json_object(text))


def parse_character_visual_draft(text: str) -> CharacterVisualDraftPayload:
    return CharacterVisualDraftPayload.model_validate(parse_json_object(text))


def parse_visual_bible(text: str) -> VisualBiblePayload:
    return VisualBiblePayload.model_validate(parse_json_object(text))


def parse_voice_bible(text: str) -> VoiceBiblePayload:
    return VoiceBiblePayload.model_validate(parse_json_object(text))


def parse_storyboard_plan(text: str) -> StoryboardPlanPayload:
    return StoryboardPlanPayload.model_validate(parse_json_object(text))


def validate_shooting_artifact_payload(
    artifact_kind: str, payload: dict[str, object]
) -> dict[str, object]:
    if artifact_kind == "quality_report" and "shot_reports" in payload:
        try:
            return ProductionQualityReportPayload.model_validate(payload).model_dump(
                mode="json"
            )
        except ValidationError as exc:
            raise ValidationAppError(
                "invalid quality_report payload",
                details={
                    "code": "SHOOTING_ARTIFACT_SCHEMA_INVALID",
                    "artifact_kind": artifact_kind,
                    "errors": exc.errors(include_context=False),
                },
            ) from exc
    validators: dict[str, type[BaseModel]] = {
        "character_bible": CharacterBiblePayload,
        "visual_bible": VisualBiblePayload,
        "voice_bible": VoiceBiblePayload,
        "storyboard_plan": StoryboardPlanPayload,
        "risk_report": RiskReportPayload,
        "selection_plan": SelectionPlanPayload,
        "cost_estimate": CostEstimatePayload,
        "trial_plan": TrialPlanPayload,
        "quality_report": QualityReportPayload,
        "trial_review": TrialReviewPayload,
        "production_review": ProductionReviewPayload,
        "repair_plan": RepairPlanPayload,
    }
    validator = validators.get(artifact_kind)
    if validator is None:
        return payload
    try:
        return validator.model_validate(payload).model_dump(mode="json")
    except ValidationError as exc:
        raise ValidationAppError(
            f"invalid {artifact_kind} payload",
            details={
                "code": "SHOOTING_ARTIFACT_SCHEMA_INVALID",
                "artifact_kind": artifact_kind,
                "errors": exc.errors(include_context=False),
            },
        ) from exc


def validate_storyboard_against_story(
    *,
    story: StoryCorePayload,
    script: EpisodeScriptPayload,
    storyboard: StoryboardPlanPayload,
) -> None:
    character_names = {item.name for item in story.characters}
    shot_characters = {name for shot in storyboard.shots for name in shot.characters}
    unknown_characters = sorted(shot_characters - character_names)
    if unknown_characters:
        raise ValidationAppError(
            "storyboard references characters outside the locked story",
            details={"code": "STORYBOARD_CHARACTER_MISMATCH", "names": unknown_characters},
        )
    expected_dialogue = [(item.speaker, item.text) for item in script.dialogue]
    actual_dialogue = [
        (item.speaker, item.text) for shot in storyboard.shots for item in shot.dialogue
    ]
    if actual_dialogue != expected_dialogue:
        raise ValidationAppError(
            "storyboard dialogue must preserve the locked script exactly",
            details={"code": "STORYBOARD_DIALOGUE_MISMATCH"},
        )
    if storyboard.target_duration_seconds != script.target_duration_seconds:
        raise ValidationAppError(
            "storyboard duration must match the locked script",
            details={"code": "STORYBOARD_DURATION_MISMATCH"},
        )


def build_risk_report(
    storyboard: StoryboardPlanPayload,
    *,
    character_count: int,
) -> RiskReportPayload:
    risks: list[RiskItem] = []
    scores: dict[str, int] = {shot.shot_id: 0 for shot in storyboard.shots}
    if character_count > 2:
        risks.append(
            RiskItem(
                risk_id="too-many-characters",
                category="identity",
                severity="blocking",
                evidence=f"The v1 template contains {character_count} main characters.",
                mitigation="Reduce the speaking cast to one or two characters.",
                requires_trial=True,
            )
        )
    for shot in storyboard.shots:
        if len(shot.characters) > 1:
            scores[shot.shot_id] += 4
            risks.append(
                RiskItem(
                    risk_id=f"{shot.shot_id}-multi-person",
                    shot_id=shot.shot_id,
                    category="multi_person",
                    severity="warning",
                    evidence="Two characters share the frame, increasing identity confusion risk.",
                    mitigation="Prefer over-shoulder singles or lock both character references.",
                    requires_trial=True,
                )
            )
        if shot.dialogue:
            scores[shot.shot_id] += 3
            risks.append(
                RiskItem(
                    risk_id=f"{shot.shot_id}-dialogue",
                    shot_id=shot.shot_id,
                    category="lip_sync",
                    severity="warning",
                    evidence="The shot contains visible dialogue performance.",
                    mitigation="Use this shot to validate voice, mouth motion and performance.",
                    requires_trial=True,
                )
            )
        if shot.camera_move in {"tracking", "pan"}:
            scores[shot.shot_id] += 2
            risks.append(
                RiskItem(
                    risk_id=f"{shot.shot_id}-motion",
                    shot_id=shot.shot_id,
                    category="motion",
                    severity="warning",
                    evidence=f"Camera move '{shot.camera_move}' increases geometry drift risk.",
                    mitigation="Use static or subtle motion if the trial is unstable.",
                    requires_trial=True,
                )
            )
    executable_singles = [
        shot for shot in storyboard.shots if len(shot.characters) == 1 and shot.dialogue
    ]
    representative_pool = executable_singles or storyboard.shots
    representative = max(
        representative_pool,
        key=lambda item: (scores[item.shot_id], len(item.dialogue), -item.shot_number),
    )
    status: Literal["ready", "needs_revision", "blocked"] = (
        "blocked" if any(item.severity == "blocking" for item in risks) else "ready"
    )
    return RiskReportPayload(
        status=status,
        representative_shot_id=representative.shot_id,
        representative_shot_reason=(
            "This executable single-character shot exposes identity, motion and dialogue "
            "risks before full production."
            if executable_singles
            else "This shot exposes the largest combined production risk before full production."
        ),
        risks=risks,
    )
