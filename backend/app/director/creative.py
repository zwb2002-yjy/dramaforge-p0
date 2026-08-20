"""Creative-stage contracts and deterministic validation."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.shared.errors import ValidationAppError


class CharacterMotivation(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    identity: str = Field(min_length=1, max_length=300)
    desire: str = Field(min_length=1, max_length=300)
    fear_or_cost: str = Field(min_length=1, max_length=300)


class StoryConcept(BaseModel):
    concept_id: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=100)
    logline: str = Field(min_length=1, max_length=400)
    theme: str = Field(min_length=1, max_length=200)
    character_relationship: str = Field(min_length=1, max_length=400)
    core_conflict: str = Field(min_length=1, max_length=400)
    ending_direction: str = Field(min_length=1, max_length=300)
    why_it_fits: str = Field(min_length=1, max_length=300)


class ConceptSetPayload(BaseModel):
    entry_mode: Literal["no_idea", "one_sentence", "import_script"]
    creation_goal: Literal["self_expression", "high_traffic", "balanced"] | None = None
    adaptation_mode: Literal["faithful", "balanced", "free"] | None = None
    source_rights_confirmed: bool = False
    preference_summary: str = ""
    concepts: list[StoryConcept] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_entry_mode(self) -> ConceptSetPayload:
        ids = {concept.concept_id for concept in self.concepts}
        if len(ids) != 3:
            raise ValueError("concept_id must be unique")
        if self.entry_mode == "no_idea" and self.creation_goal is None:
            raise ValueError("creation_goal is required for no_idea entry")
        if self.entry_mode == "import_script":
            if not self.source_rights_confirmed:
                raise ValueError("source rights must be confirmed for script import")
            if self.adaptation_mode is None:
                raise ValueError("adaptation_mode is required for script import")
        return self


class StoryCorePayload(BaseModel):
    selected_concept_id: str = Field(min_length=1, max_length=40)
    theme: str = Field(min_length=1, max_length=200)
    core_conflict: str = Field(min_length=1, max_length=500)
    emotional_direction: str = Field(min_length=1, max_length=300)
    ending: str = Field(min_length=1, max_length=500)
    characters: list[CharacterMotivation] = Field(min_length=1, max_length=4)


class DialogueLine(BaseModel):
    speaker: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=300)
    emotion: str = Field(min_length=1, max_length=100)


class EpisodeScriptPayload(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    target_duration_seconds: int = Field(ge=15, le=30)
    setup: str = Field(min_length=1, max_length=500)
    turn: str = Field(min_length=1, max_length=500)
    ending: str = Field(min_length=1, max_length=500)
    dialogue: list[DialogueLine] = Field(min_length=1, max_length=12)


class StoryReviewPayload(BaseModel):
    status: Literal["passed", "needs_revision"]
    logic_issues: list[str] = Field(default_factory=list)
    pacing_issues: list[str] = Field(default_factory=list)
    duration_risks: list[str] = Field(default_factory=list)
    closure_issues: list[str] = Field(default_factory=list)
    revision_suggestions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_evidence_for_revision(self) -> StoryReviewPayload:
        if self.status == "needs_revision" and not any(
            (
                self.logic_issues,
                self.pacing_issues,
                self.duration_risks,
                self.closure_issues,
            )
        ):
            raise ValueError("needs_revision requires at least one issue")
        return self


class CreativePackagePayload(BaseModel):
    story_core: StoryCorePayload
    episode_script: EpisodeScriptPayload
    story_review: StoryReviewPayload


class StoryDraftPayload(BaseModel):
    story_core: StoryCorePayload
    episode_script: EpisodeScriptPayload


class PreferenceUnderstandingPayload(BaseModel):
    liked: list[str] = Field(default_factory=list, max_length=10)
    disliked: list[str] = Field(default_factory=list, max_length=10)
    inferred_preferences: list[str] = Field(default_factory=list, max_length=10)
    avoid: list[str] = Field(default_factory=list, max_length=10)
    interpretation_summary: str = Field(min_length=1, max_length=1000)


def parse_json_object(text: str) -> dict[str, object]:
    import json

    raw = (text or "").strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model response is not a JSON object") from None
        value = json.loads(raw[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model response must be a JSON object")
    return {str(key): item for key, item in value.items()}


def parse_concept_set(text: str) -> ConceptSetPayload:
    return ConceptSetPayload.model_validate(parse_json_object(text))


def parse_creative_package(text: str) -> CreativePackagePayload:
    return CreativePackagePayload.model_validate(parse_json_object(text))


def parse_story_draft(text: str) -> StoryDraftPayload:
    return StoryDraftPayload.model_validate(parse_json_object(text))


def parse_story_review(text: str) -> StoryReviewPayload:
    return StoryReviewPayload.model_validate(parse_json_object(text))


def parse_preference_understanding(text: str) -> PreferenceUnderstandingPayload:
    return PreferenceUnderstandingPayload.model_validate(parse_json_object(text))


def validate_creative_artifact_payload(
    artifact_kind: str, payload: dict[str, object]
) -> dict[str, object]:
    # Keep the public command boundary centralized while allowing each stage to
    # own its schemas.  The local import avoids a creative<->shooting import
    # cycle because shooting validators also reuse the locked story contracts.
    from app.director.shooting import validate_shooting_artifact_payload

    validators: dict[str, type[BaseModel]] = {
        "preference_understanding": PreferenceUnderstandingPayload,
        "concept_set": ConceptSetPayload,
        "story_core": StoryCorePayload,
        "episode_script": EpisodeScriptPayload,
        "story_review": StoryReviewPayload,
    }
    validator = validators.get(artifact_kind)
    if validator is None:
        return validate_shooting_artifact_payload(artifact_kind, payload)
    try:
        return validator.model_validate(payload).model_dump(mode="json")
    except ValidationError as exc:
        raise ValidationAppError(
            f"invalid {artifact_kind} payload",
            details={
                "code": "CREATIVE_ARTIFACT_SCHEMA_INVALID",
                "artifact_kind": artifact_kind,
                "errors": exc.errors(include_context=False),
            },
        ) from exc


def _normalize_closure_text(value: str) -> str:
    """Normalize prose for a conservative, language-agnostic closure check."""

    return "".join(re.findall(r"[0-9a-z\u4e00-\u9fff]+", value.casefold()))


def _closure_matches(draft: StoryDraftPayload) -> bool:
    """Accept a script when its ending or final dialogue realizes the story ending.

    A literal substring check rejects normal paraphrases and also ignores that the
    decisive closure is often carried by the final line of dialogue.  Keep this
    gate deterministic, but compare the normalized story ending against the
    scripted ending, the final two dialogue lines, and their combination.
    """

    expected = _normalize_closure_text(draft.story_core.ending)
    final_dialogue = "".join(
        line.text for line in draft.episode_script.dialogue[-2:]
    )
    candidates = (
        draft.episode_script.ending,
        final_dialogue,
        draft.episode_script.ending + final_dialogue,
    )
    for candidate in candidates:
        actual = _normalize_closure_text(candidate)
        if not actual:
            continue
        if expected in actual or actual in expected:
            return True
        if SequenceMatcher(None, expected, actual, autojunk=False).ratio() >= 0.55:
            return True

    # A creator's decisive closing line may be quoted exactly while the action
    # around it is naturally paraphrased. Accept that case only when the
    # scripted ending also overlaps the locked ending, so copying one line
    # cannot disguise an unrelated final action.
    scripted_ending = _normalize_closure_text(draft.episode_script.ending)
    ending_overlap = (
        SequenceMatcher(None, expected, scripted_ending, autojunk=False).ratio()
        if scripted_ending
        else 0.0
    )
    if ending_overlap >= 0.30:
        normalized_dialogue = _normalize_closure_text(final_dialogue)
        expected_clauses = [
            _normalize_closure_text(part)
            for part in re.split(r"[，,。；;：:！？!?…]+", draft.story_core.ending)
        ]
        if any(
            len(clause) >= 6 and clause in normalized_dialogue
            for clause in expected_clauses
        ):
            return True
    return False


def review_story_deterministically(draft: StoryDraftPayload) -> StoryReviewPayload:
    logic_issues: list[str] = []
    pacing_issues: list[str] = []
    duration_risks: list[str] = []
    closure_issues: list[str] = []
    suggestions: list[str] = []
    character_names = {item.name for item in draft.story_core.characters}
    unknown_speakers = sorted(
        {line.speaker for line in draft.episode_script.dialogue} - character_names
    )
    if unknown_speakers:
        logic_issues.append("对白包含未在人物动机中定义的说话人：" + "、".join(unknown_speakers))
        suggestions.append("补充人物动机或把对白归属改为已定义角色。")
    dialogue_chars = sum(len(line.text) for line in draft.episode_script.dialogue)
    # Mandarin dialogue is commonly around 3.5–4.5 chars/s; leave room for acting beats.
    safe_chars = int(draft.episode_script.target_duration_seconds * 3.5)
    if dialogue_chars > safe_chars:
        duration_risks.append(
            f"对白约 {dialogue_chars} 字，超过 "
            f"{draft.episode_script.target_duration_seconds} 秒作品的稳妥范围。"
        )
        suggestions.append("删减对白或把信息改成可由动作/画面表达。")
    if len(draft.episode_script.dialogue) > 8:
        pacing_issues.append("15–30 秒模板中的对白轮次过多，容易造成切镜和口型压力。")
        suggestions.append("合并相邻对白，把核心交锋控制在 3–8 句。")
    if not _closure_matches(draft):
        closure_issues.append("故事内核的结局与剧本落点表达不一致。")
        suggestions.append("让最后一个动作或对白明确落到用户确认的结局。")
    issues = logic_issues + pacing_issues + duration_risks + closure_issues
    return StoryReviewPayload(
        status="needs_revision" if issues else "passed",
        logic_issues=logic_issues,
        pacing_issues=pacing_issues,
        duration_risks=duration_risks,
        closure_issues=closure_issues,
        revision_suggestions=suggestions,
    )
