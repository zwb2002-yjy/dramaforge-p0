"""Shooting-plan contracts and deterministic preflight checks.

The LLM proposes creative details.  The validators and preflight rules remain
deterministic so a fluent response cannot silently waive a production risk.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

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

    @field_validator("character_id", mode="before")
    @classmethod
    def normalize_numeric_character_id(cls, value: object) -> object:
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        return value


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

    @field_validator("character_id", mode="before")
    @classmethod
    def normalize_numeric_character_id(cls, value: object) -> object:
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        return value


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

    @field_validator("shot_id", mode="before")
    @classmethod
    def normalize_numeric_shot_id(cls, value: object) -> object:
        if isinstance(value, int) and not isinstance(value, bool):
            return f"shot-{value}"
        return value

    @field_validator("shot_type", mode="before")
    @classmethod
    def normalize_descriptive_shot_type(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower().replace("-", "_")
        if "过肩" in normalized:
            return "over_shoulder"
        if "中近" in normalized or "近中" in normalized:
            return "medium_close"
        if "全景" in normalized or "远景" in normalized:
            return "wide"
        if "插入" in normalized or "细节" in normalized:
            return "insert"
        if "特写" in normalized or "近景" in normalized:
            return "close"
        if "中景" in normalized:
            return "medium"
        if "over" in normalized and "shoulder" in normalized:
            return "over_shoulder"
        if "medium" in normalized and "close" in normalized:
            return "medium_close"
        for shot_type in ("wide", "medium", "close", "insert"):
            if shot_type in normalized:
                return shot_type
        return value

    @field_validator("camera_move", mode="before")
    @classmethod
    def normalize_descriptive_camera_move(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        if "推" in normalized:
            return "push_in"
        if "拉远" in normalized or "拉出" in normalized:
            return "pull_out"
        if "固定" in normalized or "静止" in normalized:
            return "static"
        if "环绕" in normalized or "跟" in normalized:
            return "tracking"
        if "摇" in normalized or "横移" in normalized:
            return "pan"
        if "push" in normalized:
            return "push_in"
        if "pull" in normalized:
            return "pull_out"
        if "static" in normalized or "locked" in normalized:
            return "static"
        if "tracking" in normalized or "track" in normalized:
            return "tracking"
        if "pan" in normalized:
            return "pan"
        return value

    @field_validator("dialogue", mode="before")
    @classmethod
    def normalize_single_dialogue_object(cls, value: object) -> object:
        if isinstance(value, dict):
            return [value]
        if isinstance(value, str):
            dialogue = value.strip()
            if not dialogue:
                return []
            for separator in ("：", ":"):
                if separator in dialogue:
                    speaker, text = dialogue.split(separator, 1)
                    return [
                        {
                            "speaker": speaker.strip(),
                            "text": text.strip(),
                            "emotion": "unspecified",
                        }
                    ]
        return value

    @field_validator("duration_seconds", mode="before")
    @classmethod
    def normalize_descriptive_duration(cls, value: object) -> object:
        if isinstance(value, str):
            matched = re.search(r"\d+(?:\.\d+)?", value)
            if matched is not None:
                return matched.group(0)
        return value


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
    decisions: dict[str, Literal["accept", "repair", "stop"]] = Field(min_length=1, max_length=6)
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


def _named_payload(text: str, key: str) -> dict[str, object]:
    payload = parse_json_object(text)
    wrapped = payload.get(key)
    if set(payload) == {key} and isinstance(wrapped, dict):
        return {str(item_key): item for item_key, item in wrapped.items()}
    return payload


def _bounded_prose(value: object, *, max_length: int) -> object:
    if isinstance(value, str):
        prose = value.strip()
    elif isinstance(value, dict | list):
        prose = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        return value
    if len(prose) <= max_length:
        return prose
    return f"{prose[: max_length - 1]}…"


def _continuity_rule_list(value: object) -> object:
    if isinstance(value, str):
        return [value.strip()]
    if isinstance(value, dict):
        return [
            f"{key}: {_bounded_prose(item, max_length=900)}"
            for key, item in list(value.items())[:12]
        ]
    if isinstance(value, list):
        return [_bounded_prose(item, max_length=900) for item in value[:12]]
    return value


def parse_character_bible(text: str) -> CharacterBiblePayload:
    payload = parse_json_object(text)
    wrapped = payload.get("character_bible")
    if set(payload) == {"character_bible"} and isinstance(wrapped, list):
        payload = {"characters": wrapped}
    else:
        payload = _named_payload(text, "character_bible")
    return CharacterBiblePayload.model_validate(payload)


def parse_character_visual_draft(text: str) -> CharacterVisualDraftPayload:
    return CharacterVisualDraftPayload.model_validate(parse_json_object(text))


def parse_visual_bible(text: str, *, aspect_ratio: str | None = None) -> VisualBiblePayload:
    payload = _named_payload(text, "visual_bible")
    if "aspect_ratio" not in payload and aspect_ratio is not None:
        payload["aspect_ratio"] = aspect_ratio
    for field_name, max_length in (
        ("color_palette", 400),
        ("lighting", 400),
        ("lens_language", 500),
    ):
        if field_name in payload:
            payload[field_name] = _bounded_prose(payload[field_name], max_length=max_length)
    if "continuity_rules" in payload:
        payload["continuity_rules"] = _continuity_rule_list(payload["continuity_rules"])
    return VisualBiblePayload.model_validate(payload)


def parse_voice_bible(text: str, *, character_names: list[str] | None = None) -> VoiceBiblePayload:
    bible = VoiceBiblePayload.model_validate(_named_payload(text, "voice_bible"))
    if character_names is None or len(bible.voices) != len(character_names):
        return bible
    voices_by_name = {voice.character_name.strip(): voice for voice in bible.voices}
    if len(voices_by_name) == len(character_names) and set(voices_by_name) == set(character_names):
        ordered = [voices_by_name[name] for name in character_names]
    else:
        # The model was explicitly asked to preserve input order.  Some providers
        # translate or decorate the display label; restore the locked identity key
        # without changing any creative voice attributes.
        ordered = [
            voice.model_copy(update={"character_name": name})
            for voice, name in zip(bible.voices, character_names, strict=True)
        ]
    return bible.model_copy(update={"voices": ordered})


def parse_storyboard_plan(
    text: str, *, expected_shot_count: int | None = None
) -> StoryboardPlanPayload:
    payload = _named_payload(text, "storyboard_plan")
    shots = payload.get("shots")
    if isinstance(shots, list):
        for index, shot in enumerate(shots, start=1):
            if not isinstance(shot, dict):
                continue
            if "shot_number" not in shot:
                shot["shot_number"] = index
            if "duration_seconds" not in shot and "duration" in shot:
                shot["duration_seconds"] = shot["duration"]
        missing_duration = [
            shot for shot in shots if isinstance(shot, dict) and "duration_seconds" not in shot
        ]
        target = payload.get("target_duration_seconds")
        known_values: list[Decimal] = []
        for shot in shots:
            if not isinstance(shot, dict) or "duration_seconds" not in shot:
                continue
            value = StoryboardShot.normalize_descriptive_duration(shot["duration_seconds"])
            try:
                known_values.append(Decimal(str(value)))
            except Exception:  # noqa: BLE001 - schema validation reports the exact bad value
                known_values = []
                break
        if missing_duration and isinstance(target, int) and known_values:
            remaining = Decimal(target) - sum(known_values, Decimal("0"))
            inferred = remaining / len(missing_duration)
            if Decimal("2") <= inferred <= Decimal("10"):
                for shot in missing_duration:
                    shot["duration_seconds"] = inferred
        elif missing_duration and isinstance(target, int) and len(missing_duration) == len(shots):
            inferred = Decimal(target) / len(missing_duration)
            if Decimal("2") <= inferred <= Decimal("10"):
                for shot in missing_duration:
                    shot["duration_seconds"] = inferred
    storyboard = StoryboardPlanPayload.model_validate(payload)
    if expected_shot_count is not None and len(storyboard.shots) != expected_shot_count:
        raise ValueError(f"storyboard must contain exactly {expected_shot_count} shots")
    return storyboard


def validate_shooting_artifact_payload(
    artifact_kind: str, payload: dict[str, object]
) -> dict[str, object]:
    if artifact_kind == "quality_report" and "shot_reports" in payload:
        try:
            return ProductionQualityReportPayload.model_validate(payload).model_dump(mode="json")
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
