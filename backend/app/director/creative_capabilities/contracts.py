"""Creative capability contracts (CC1).

The 5-layer capability model:

    Creative Intent -> Genre/Production Profile -> Director Skills
                     -> Style + Shot Language -> Workflow Template -> Execution

These are *typed, frozen, versioned* contract facts.  A capability spec
describes how creative intent guides a production — it is never an Execution
Graph and never touches a Provider.  The contract hash covers only the semantic
contract (never a runtime timestamp, callable memory address, or Provider
secret), so a pack's identity is reproducible from its declared inputs.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


def _semantic_json(obj: BaseModel) -> str:
    """Serialize a contract to canonical JSON for hashing (no callables/sets)."""
    return json.dumps(
        obj.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def contract_hash(contract: BaseModel) -> str:
    """SHA-256 over the semantic contract only.

    Deterministic across runs: no timestamp, no callable address, no secret.
    """
    return hashlib.sha256(_semantic_json(contract).encode("utf-8")).hexdigest()


class SkillCategory(StrEnum):
    STORY = "story"
    SCREENWRITING = "screenwriting"
    DIRECTING = "directing"
    CINEMATOGRAPHY = "cinematography"
    PERFORMANCE = "performance"
    CONTINUITY = "continuity"
    PRODUCTION = "production"
    REVIEW = "review"


class ContentStage(StrEnum):
    """Applicable production stage for a skill/style/shot-language hint."""

    PREMISE = "premise"
    SCRIPT = "script"
    STORYBOARD = "storyboard"
    SHOT = "shot"
    POST = "post"


class CreativeInputField(BaseModel):
    """A single structured input the skill requires from creative intent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    description: str
    required: bool = False
    default: str | None = None


class CreativeOutputField(BaseModel):
    """A single structured output the skill contributes to the compiled intent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    description: str
    kind: str = "hint"
    weight: float = Field(default=1.0, ge=0.0, le=1.0)


class CreativeSkillSpec(BaseModel):
    """One executable competence a director may draw on (never a graph/provider)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_key: str
    skill_version: str
    display_name: str
    category: SkillCategory
    description: str

    applicable_stages: list[ContentStage] = Field(default_factory=list)
    intent_tags: list[str] = Field(default_factory=list)
    required_context: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    compatible_with: list[str] = Field(default_factory=list)

    input_contract: list[CreativeInputField] = Field(default_factory=list)
    output_contract: list[CreativeOutputField] = Field(default_factory=list)
    strategy: str
    quality_hints: list[str] = Field(default_factory=list)

    # ``contract_hash`` is derived from the semantic contract only.
    @property
    def contract_hash(self) -> str:
        return contract_hash(self)

    @property
    def identity(self) -> str:
        return f"{self.skill_key}@{self.skill_version}"

    def conflicts(self, other: CreativeSkillSpec) -> bool:
        return other.skill_key in self.conflicts_with


class CreativeSkillResolution(BaseModel):
    """Outcome of resolving a requested skill against the registry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requested_skill_key: str
    resolved_skill_key: str | None
    status: str  # RESOLVED | UNAVAILABLE
    reason: str | None = None
    contract_hash: str | None = None
    skill_version: str | None = None


class CreativeSkillStack(BaseModel):
    """An ordered, provenance-tracked stack of selected skills."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selections: list[CreativeSkillSpec] = Field(default_factory=list)
    source: str = "explicit"  # explicit | genre | composer

    def keys(self) -> list[str]:
        return [item.skill_key for item in self.selections]

    def versions(self) -> list[str]:
        return [item.identity for item in self.selections]
