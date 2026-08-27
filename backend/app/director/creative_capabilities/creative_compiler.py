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
from app.director.creative_capabilities.visual_bible import VisualBibleCompiler


class CompiledCreativeIntent(BaseModel):
    """The compiler output: guidance + patches + provenance (all frozen)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    story_guidance: dict[str, object] = Field(default_factory=dict)
    visual_bible_patch: VisualBiblePatch | None = None
    shot_director_intent_patch: ShotDirectorIntentPatch | None = None
    workflow_hints: list[str] = Field(default_factory=list)
    reference_guidance: list[str] = Field(default_factory=list)
    quality_hints: list[str] = Field(default_factory=list)
    provenance: dict[str, object] = Field(default_factory=dict)


class _CompilerInput(BaseModel):
    user_intent: dict[str, object] = Field(default_factory=dict)
    project_context: dict[str, object] = Field(default_factory=dict)


class CreativeCapabilityCompiler:
    """Deterministically compile a capability selection into a frozen intent."""

    def __init__(self) -> None:
        self._visual_bible = VisualBibleCompiler()

    def compile(
        self,
        *,
        user_intent: dict[str, object] | None = None,
        project_context: dict[str, object] | None = None,
        genre: GenreProfileSpec | None = None,
        skill_stack: list[CreativeSkillSpec] | CreativeSkillStack | None = None,
        style: StylePackSpec | None = None,
        shot_language: ShotLanguagePackSpec | None = None,
        quality_policy: QualityPolicySpec | None = None,
    ) -> CompiledCreativeIntent:
        user = dict(user_intent or {})
        project = dict(project_context or {})

        # --- story guidance: genre defaults only where user/project silent ------
        story_guidance: dict[str, object] = {}
        if genre is not None:
            if user.get("story_rhythm") is None and project.get("story_rhythm") is None:
                story_guidance["story_rhythm"] = genre.story_rhythm.value
            if user.get("scene_pacing") is None and project.get("scene_pacing") is None:
                story_guidance["scene_pacing"] = genre.scene_pacing.value
            story_guidance["hook_strategy"] = genre.hook_strategy
            story_guidance["turn_frequency"] = genre.turn_frequency

        # --- VisualBible patch: style default, respecting explicit values.
        # priority gate: explicit user value > project override > pack default.
        # Merge user first, then project, so the user's explicit choice wins.
        explicit = {**project, **user}
        visual_bible_patch: VisualBiblePatch | None = None
        if style is not None:
            visual_bible_patch = self._visual_bible.compile(
                style=style, project_values=explicit
            )

        # --- skill identity: carry the resolved versions ------------------------
        skills = (
            skill_stack.selections
            if isinstance(skill_stack, CreativeSkillStack)
            else (skill_stack or [])
        )
        skill_identities = [skill.identity for skill in skills]

        # --- workflow hints: genre preferences + quality emphasis --------------
        workflow_hints: list[str] = []
        if genre is not None:
            for key, value in genre.workflow_preferences.items():
                workflow_hints.append(f"{key}={value}")
        quality_hints: list[str] = []
        if quality_policy is not None:
            quality_hints = [
                f"{d.kind.value}:{d.key}" for d in quality_policy.dimensions
            ]

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
            workflow_hints=workflow_hints,
            reference_guidance=list(style.reference_guidance) if style is not None else [],
            quality_hints=quality_hints,
            provenance=provenance,
        )
