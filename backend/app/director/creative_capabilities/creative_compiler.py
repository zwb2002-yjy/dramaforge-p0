"""CreativeCapabilityCompiler (CC9).

Compiles user intent + project context + genre + skill stack + style + shot
language + quality policy into a single ``CompiledCreativeIntent``.  It never
produces a ProviderRequest and never creates a second Execution Graph.

The priority gate is authoritative::

    explicit user value > accepted proposal > project override > pack default

A pack (genre/style/shot-language) supplies only a *default*; if the user or
project already made an explicit choice, the pack default is NOT applied.  The
compiled intent records every pack identity (frozen provenance) so a resume uses
the same hashes (G-CC-04).
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.director.creative_capabilities.contracts import CreativeSkillSpec, CreativeSkillStack
from app.director.creative_capabilities.packs import (
    GenreProfileSpec,
    StylePackSpec,
    VisualBiblePatch,
)
from app.director.creative_capabilities.shot_language import (
    QualityPolicySpec,
    ShotDirectorIntentPatch,
    ShotLanguagePackSpec,
)
from app.director.creative_capabilities.shot_language_compiler import ShotLanguageCompiler
from app.director.creative_capabilities.visual_bible import VisualBibleCompiler


class CompiledCreativeIntent(BaseModel):
    """The compiler output: guidance + patches + provenance (all frozen)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    story_guidance: dict[str, object] = Field(default_factory=dict)
    visual_bible_patch: VisualBiblePatch | None = None
    shot_director_intent_patch: ShotDirectorIntentPatch | None = None
    effective_values: dict[str, object] = Field(default_factory=dict)
    value_sources: dict[str, str] = Field(default_factory=dict)
    overridden_defaults: list[dict[str, object]] = Field(default_factory=list)
    skill_guidance: list[dict[str, object]] = Field(default_factory=list)
    workflow_hints: list[str] = Field(default_factory=list)
    reference_guidance: list[str] = Field(default_factory=list)
    quality_hints: list[str] = Field(default_factory=list)
    provenance: dict[str, object] = Field(default_factory=dict)


class _CompilerInput(BaseModel):
    user_intent: dict[str, object] = Field(default_factory=dict)
    project_context: dict[str, object] = Field(default_factory=dict)


def _deep_merge(*layers: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for layer in layers:
        for key, value in layer.items():
            existing = result.get(key)
            if isinstance(value, Mapping) and isinstance(existing, Mapping):
                result[key] = _deep_merge(
                    existing,
                    dict(value),
                )
            else:
                result[key] = value
    return result


def _value_at_path(values: Mapping[str, object], path: str) -> object | None:
    current: object = values
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _meaningful_mapping(values: Mapping[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in values.items():
        if isinstance(value, Mapping):
            nested = _meaningful_mapping(value)
            if nested:
                normalized[key] = nested
        elif isinstance(value, (str, list, tuple, set)) and len(value) == 0:
            continue
        elif value is not None:
            normalized[key] = value
    for canonical, aliases in (
        ("shot_size", ("framing.shot_size",)),
        ("camera_angle", ("framing.angle",)),
        ("camera_motion", ("camera.movement",)),
        ("continuity", ("continuity_constraints",)),
    ):
        if canonical in normalized:
            continue
        for alias in aliases:
            value = _value_at_path(normalized, alias)
            if value is not None:
                normalized[canonical] = value
                break
    return normalized


def _leaf_values(value: Mapping[str, object], prefix: str = "") -> dict[str, object]:
    leaves: dict[str, object] = {}
    for key, nested in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(nested, Mapping):
            leaves.update(_leaf_values(nested, path))
        else:
            leaves[path] = nested
    return leaves


def _pack_defaults(
    *,
    genre: GenreProfileSpec | None,
    style: StylePackSpec | None,
    shot_patch: ShotDirectorIntentPatch | None,
) -> dict[str, object]:
    defaults: dict[str, object] = {}
    if genre is not None:
        defaults.update(
            {
                "story_rhythm": genre.story_rhythm.value,
                "scene_pacing": genre.scene_pacing.value,
                "dialogue_density": genre.dialogue_density.value,
                "hook_strategy": genre.hook_strategy,
                "turn_frequency": genre.turn_frequency,
                "shot_pacing": genre.shot_pacing,
            }
        )
    if style is not None:
        defaults.update(
            {
                "palette": dict(style.palette),
                "lighting": style.lighting,
                "contrast": style.contrast,
                "texture": style.texture,
                "lens_language": style.lens_language,
                "composition": style.composition,
                "camera_behavior": style.camera_behavior.value,
                "motion_feel": style.motion_feel.value,
                "production_design": style.production_design,
                "post_processing": style.post_processing,
            }
        )
    if shot_patch is not None:
        defaults.update(
            shot_patch.model_dump(
                mode="python",
                exclude={"pack_key", "pack_version", "provenance"},
                exclude_none=True,
                exclude_defaults=True,
            )
        )
    return defaults


class CreativeCapabilityCompiler:
    """Deterministically compile a capability selection into a frozen intent."""

    def __init__(self) -> None:
        self._visual_bible = VisualBibleCompiler()

    def compile(
        self,
        *,
        user_intent: dict[str, object] | None = None,
        accepted_proposal: dict[str, object] | None = None,
        project_context: dict[str, object] | None = None,
        genre: GenreProfileSpec | None = None,
        skill_stack: list[CreativeSkillSpec] | CreativeSkillStack | None = None,
        style: StylePackSpec | None = None,
        shot_language: ShotLanguagePackSpec | None = None,
        quality_policy: QualityPolicySpec | None = None,
    ) -> CompiledCreativeIntent:
        user = _meaningful_mapping(user_intent or {})
        accepted = _meaningful_mapping(accepted_proposal or {})
        project = _meaningful_mapping(project_context or {})

        explicit = _deep_merge(project, accepted, user)
        raw_shot_patch = (
            ShotLanguageCompiler().compile(pack=shot_language)
            if shot_language is not None
            else None
        )
        shot_patch = (
            ShotLanguageCompiler().compile(pack=shot_language, explicit_values=explicit)
            if shot_language is not None
            else None
        )
        raw_pack_defaults = _pack_defaults(
            genre=genre,
            style=style,
            shot_patch=raw_shot_patch,
        )
        pack_defaults = _pack_defaults(
            genre=genre,
            style=style,
            shot_patch=shot_patch,
        )
        effective_values = _deep_merge(pack_defaults, project, accepted, user)
        value_sources: dict[str, str] = {}
        for source, layer in (
            ("pack_default", pack_defaults),
            ("project_override", project),
            ("accepted_proposal", accepted),
            ("user_confirmed", user),
        ):
            for path in _leaf_values(layer):
                value_sources[path] = source
        overridden_defaults = [
            {
                "path": path,
                "default_value": default_value,
                "effective_value": _leaf_values(effective_values).get(path),
                "effective_source": value_sources.get(path),
            }
            for path, default_value in _leaf_values(raw_pack_defaults).items()
            if value_sources.get(path) != "pack_default"
        ]

        # --- story guidance: genre defaults only where user/project silent ------
        # Priority gate: explicit user value > project override > pack default.
        # A genre default is applied only when neither the user nor the project
        # already made an explicit choice.
        story_guidance: dict[str, object] = {}
        if genre is not None:
            if explicit.get("story_rhythm") is None:
                story_guidance["story_rhythm"] = genre.story_rhythm.value
            if explicit.get("scene_pacing") is None:
                story_guidance["scene_pacing"] = genre.scene_pacing.value
            if explicit.get("hook_strategy") is None:
                story_guidance["hook_strategy"] = genre.hook_strategy
            if explicit.get("turn_frequency") is None:
                story_guidance["turn_frequency"] = genre.turn_frequency

        # --- VisualBible patch: style default, respecting explicit values.
        # priority gate: explicit user value > project override > pack default.
        # Merge user first, then project, so the user's explicit choice wins.
        visual_bible_patch: VisualBiblePatch | None = None
        if style is not None:
            visual_bible_patch = self._visual_bible.compile(style=style, project_values=explicit)

        # --- skill identity: carry the resolved versions ------------------------
        skills = (
            skill_stack.selections
            if isinstance(skill_stack, CreativeSkillStack)
            else (skill_stack or [])
        )
        skill_identities = [skill.identity for skill in skills]
        skill_guidance: list[dict[str, object]] = [
            {
                "skill_key": skill.skill_key,
                "skill_version": skill.skill_version,
                "contract_hash": skill.contract_hash,
                "strategy": skill.strategy,
                "outputs": [field.model_dump(mode="json") for field in skill.output_contract],
                "quality_hints": list(skill.quality_hints),
            }
            for skill in skills
        ]

        # --- workflow hints: genre preferences + quality emphasis --------------
        workflow_hints: list[str] = []
        if genre is not None:
            for key, value in genre.workflow_preferences.items():
                workflow_hints.append(f"{key}={value}")
        quality_hints: list[str] = []
        if quality_policy is not None:
            quality_hints = [f"{d.kind.value}:{d.key}" for d in quality_policy.dimensions]
        for skill in skills:
            quality_hints.extend(skill.quality_hints)

        # --- provenance: frozen identities for every pack ----------------------
        provenance: dict[str, object] = {}
        if genre is not None:
            provenance["genre"] = {
                "key": genre.genre_key,
                "version": genre.genre_version,
                "contract_hash": genre.contract_hash,
            }
        provenance["skills"] = skill_identities
        if style is not None:
            provenance["style"] = {
                "key": style.style_key,
                "version": style.style_version,
                "contract_hash": style.contract_hash,
            }
        if shot_language is not None:
            provenance["shot_language"] = {
                "key": shot_language.pack_key,
                "version": shot_language.pack_version,
                "contract_hash": shot_language.contract_hash,
            }
        if quality_policy is not None:
            provenance["quality_policy"] = {
                "key": quality_policy.policy_key,
                "version": quality_policy.version,
                "contract_hash": quality_policy.contract_hash,
            }

        return CompiledCreativeIntent(
            story_guidance=story_guidance,
            visual_bible_patch=visual_bible_patch,
            shot_director_intent_patch=shot_patch,
            effective_values=effective_values,
            value_sources=value_sources,
            overridden_defaults=overridden_defaults,
            skill_guidance=skill_guidance,
            workflow_hints=workflow_hints,
            reference_guidance=list(style.reference_guidance) if style is not None else [],
            quality_hints=quality_hints,
            provenance=provenance,
        )
