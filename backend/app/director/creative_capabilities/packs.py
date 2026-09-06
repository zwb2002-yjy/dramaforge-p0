"""Genre + style + shot-language + quality contracts (CC5/CC6/CC7/CC8).

These are structured, frozen, versioned preference facts.  A Genre is *default*
strategy (user may override); a Style is a structured look (never bound to a
Provider); a Shot Language compiles into a ``ShotDirectorIntentPatch``; a
Quality policy separates hard blockers from warnings from human judgment.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.director.creative_capabilities.contracts import contract_hash


class StoryRhythm(StrEnum):
    PUNCHY = "punchy"
    STEADY = "steady"
    SLOW_BURN = "slow_burn"
    RHYTHMIC = "rhythmic"


class DialogDensity(StrEnum):
    LIGHT = "light"
    BALANCED = "balanced"
    HEAVY = "heavy"


class ScenePacing(StrEnum):
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"


class GenreProfileSpec(BaseModel):
    """Default creative direction for a genre.  Never calls a Provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    genre_key: str
    genre_version: str
    display_name: str
    description: str

    story_rhythm: StoryRhythm
    scene_pacing: ScenePacing
    dialogue_density: DialogDensity
    hook_strategy: str
    turn_frequency: str
    shot_pacing: str

    preferred_skill_stack: list[str] = Field(default_factory=list)
    workflow_preferences: dict[str, object] = Field(default_factory=dict)
    quality_emphasis: list[str] = Field(default_factory=list)

    @property
    def contract_hash(self) -> str:
        return contract_hash(self)

    @property
    def identity(self) -> str:
        return f"{self.genre_key}@{self.genre_version}"


# --- Style pack ---------------------------------------------------------------


class CameraBehavior(StrEnum):
    STATIC = "static"
    HANDHELD = "handheld"
    TRIPOD = "tripod"
    STABILIZED = "stabilized"
    DRONE = "drone"


class MotionFeel(StrEnum):
    SMOOTH = "smooth"
    WEIGHTED = "weighted"
    FLOATING = "floating"
    RHYTHMIC = "rhythmic"


class StylePackSpec(BaseModel):
    """Structured visual look — never bound to a Provider (no model choice).

    Model adaptation stays with the Manifest + Compiler; a style pack only adds
    defaults/guidance, and may form a Proposal (never silently replaces project
    explicit values).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    style_key: str
    style_version: str
    display_name: str
    medium: str  # video | image | multi
    description: str

    palette: dict[str, str] = Field(default_factory=dict)  # role -> color/hex
    lighting: str
    contrast: str
    texture: str
    lens_language: str
    composition: str
    camera_behavior: CameraBehavior
    motion_feel: MotionFeel
    production_design: str
    post_processing: str
    negative_tendencies: list[str] = Field(default_factory=list)
    reference_guidance: list[str] = Field(default_factory=list)

    @property
    def contract_hash(self) -> str:
        return contract_hash(self)

    @property
    def identity(self) -> str:
        return f"{self.style_key}@{self.style_version}"


class VisualBiblePatch(BaseModel):
    """A style pack compiled into a *patch* over existing project values.

    ``explicit project values > style default``; a patch only supplies a default
    or forms a Proposal, and never replaces an explicit project value (CC9 gate).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    style_key: str
    style_version: str
    patches: dict[str, object] = Field(default_factory=dict)
    suggestions: list[str] = Field(default_factory=list)
    provenance: str = "style-pack"
