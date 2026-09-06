"""Shot language packs + quality policy registry (CC7/CC8).

A ShotLanguagePack compiles into a ``ShotDirectorIntentPatch`` (a typed, frozen
delta over a ``ShotDirectorIntent``).  A QualityPolicy separates hard technical
blockers from warnings from human-judgment dimensions; it never turns subjective
aesthetics into a hard blocker.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.director.creative_capabilities.contracts import contract_hash


class ShotLanguagePackSpec(BaseModel):
    """Structured shot-language guidance (CC7).  Never calls a Provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pack_key: str
    pack_version: str
    display_name: str
    description: str

    preferred_shot_sizes: list[str] = Field(default_factory=list)
    camera_angles: list[str] = Field(default_factory=list)
    lens_intent: str = ""
    camera_motion: str = ""
    cutting_rules: list[str] = Field(default_factory=list)
    reaction_strategy: str = ""
    coverage_strategy: str = ""
    continuity_rules: list[str] = Field(default_factory=list)

    @property
    def contract_hash(self) -> str:
        return contract_hash(self)

    @property
    def identity(self) -> str:
        return f"{self.pack_key}@{self.pack_version}"


class ShotDirectorIntentPatch(BaseModel):
    """A frozen delta over a ShotDirectorIntent (only non-None fields apply)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pack_key: str
    pack_version: str
    shot_size: str | None = None
    camera_angle: str | None = None
    lens_intent: str | None = None
    camera_motion: str | None = None
    composition: str | None = None
    focus_strategy: str | None = None
    coverage: list[str] = Field(default_factory=list)
    reaction_rule: str | None = None
    cutting_rule: str | None = None
    continuity: list[str] = Field(default_factory=list)
    provenance: str = "shot-language-pack"


# --- Quality policy (CC8) ------------------------------------------------------


class QualityDimensionKind(StrEnum):
    TECHNICAL_BLOCKER = "TECHNICAL_BLOCKER"
    QUALITY_WARNING = "QUALITY_WARNING"
    HUMAN_JUDGMENT = "HUMAN_JUDGMENT"


class QualityDimension(BaseModel):
    """One measured dimension and how failures are classified."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    description: str
    kind: QualityDimensionKind
    # For TECHNICAL_BLOCKER: the measured value must satisfy this predicate.
    # For QUALITY_WARNING: breaching it flags a warning, never blocks.
    # For HUMAN_JUDGMENT: always routed to a human, never auto-blocked.
    threshold: str | None = None


class QualityPolicySpec(BaseModel):
    """A quality policy: what is a hard blocker, a warning, or a human call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_key: str
    version: str
    display_name: str
    description: str
    dimensions: list[QualityDimension] = Field(default_factory=list)

    @property
    def hard_blockers(self) -> list[QualityDimension]:
        return [d for d in self.dimensions if d.kind is QualityDimensionKind.TECHNICAL_BLOCKER]

    @property
    def human_review_dimensions(self) -> list[QualityDimension]:
        return [d for d in self.dimensions if d.kind is QualityDimensionKind.HUMAN_JUDGMENT]

    @property
    def warning_thresholds(self) -> list[QualityDimension]:
        return [d for d in self.dimensions if d.kind is QualityDimensionKind.QUALITY_WARNING]

    @property
    def contract_hash(self) -> str:
        return contract_hash(self)

    def recommended_repairs(self) -> list[str]:
        return []

    @property
    def identity(self) -> str:
        return f"{self.policy_key}@{self.version}"


class QualityPolicyRegistry:
    """In-memory quality policy registry.  Version-aware, never touches Provider."""

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, QualityPolicySpec]] = {}
        self._keys: dict[str, QualityPolicySpec] = {}

    def register(self, spec: QualityPolicySpec) -> QualityPolicySpec:
        versions = self._entries.setdefault(spec.policy_key, {})
        existing = versions.get(spec.version)
        if existing is not None and existing.contract_hash != spec.contract_hash:
            raise ValueError(f"quality policy contract mismatch for {spec.identity}")
        versions[spec.version] = spec
        self._keys[spec.policy_key] = max(versions.values(), key=lambda s: s.version)
        return spec

    def get(self, policy_key: str) -> QualityPolicySpec | None:
        return self._keys.get(policy_key)

    def contains(self, policy_key: str) -> bool:
        return policy_key in self._entries

    def all(self) -> list[QualityPolicySpec]:
        return list(self._keys.values())
