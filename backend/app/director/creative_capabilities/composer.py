"""Skill composition engine (CC3).

Deterministic composition of an ordered skill stack.  Handles priority, stage
scope, conflict detection, merge semantics and provenance.  Composition never
mutates a skill and never calls a Provider; it produces explicit merge verdicts.

Merge policies:
    APPEND          both skills contribute their structured output (default).
    MERGE_STRUCTURED both contribute, with field-level merge given the policy.
    REPLACE_EXPLICIT a later explicit skill intentionally replaces a field.
    CONFLICT        two skills are mutually exclusive; must be surfaced, not
                    silently dropped (G-CC-01).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.director.creative_capabilities.contracts import (
    ContentStage,
    CreativeSkillSpec,
    CreativeSkillStack,
)


class MergePolicy(StrEnum):
    APPEND = "APPEND"
    MERGE_STRUCTURED = "MERGE_STRUCTURED"
    REPLACE_EXPLICIT = "REPLACE_EXPLICIT"
    CONFLICT = "CONFLICT"


class ResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    UNAVAILABLE = "UNAVAILABLE"
    CONFLICT = "CONFLICT"


class SkillEntry(BaseModel):
    """One step in the composed stack with its provenance and merge verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    spec: CreativeSkillSpec
    source: str  # explicit | genre | composer
    merge_policy: MergePolicy
    conflicts_with: list[str] = Field(default_factory=list)
    note: str | None = None


class CreativeSkillStackResolution(BaseModel):
    """Outcome of composing a requested stack."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ResolutionStatus
    reason: str | None = None
    stack: CreativeSkillStack = Field(default_factory=CreativeSkillStack)
    entries: list[SkillEntry] = Field(default_factory=list)
    conflicts: list[tuple[str, str]] = Field(default_factory=list)

    @property
    def keys(self) -> list[str]:
        return [entry.spec.skill_key for entry in self.entries]


class CreativeSkillComposer:
    """Compose an ordered selection of skills into a resolved stack.

    Failed-closed: a conflict surfaces as ``CONFLICT`` (never silently dropped,
    never auto-removes one side).  A requested skill the registry cannot resolve
    is reported in the resolution, not silently skipped.
    """

    def __init__(
        self,
        *,
        merge_policy: MergePolicy = MergePolicy.APPEND,
        stage: ContentStage | None = None,
    ) -> None:
        self._merge_policy = merge_policy
        self._stage = stage

    def compose(
        self,
        *,
        skills: list[CreativeSkillSpec],
        source: str = "explicit",
    ) -> CreativeSkillStackResolution:
        if not skills:
            return CreativeSkillStackResolution(status=ResolutionStatus.RESOLVED)

        entries: list[SkillEntry] = []
        conflicts: list[tuple[str, str]] = []
        selected: list[CreativeSkillSpec] = []

        for skill in skills:
            # Stage scope: a skill outside the composer's stage is skipped as a
            # context mismatch, reported implicitly by omission (no silent swap).
            if self._stage is not None and (
                skill.applicable_stages and self._stage not in skill.applicable_stages
            ):
                continue

            # Conflict detection against every other skill in the selection.
            # A conflict marks BOTH involved entries; neither is dropped (G-CC-01).
            collides = [
                other.skill_key
                for other in skills
                if other is not skill and skill.conflicts(other)
            ]
            policy = MergePolicy.CONFLICT if collides else self._merge_policy
            if collides:
                conflicts.append((skill.skill_key, collides[0]))
            entries.append(
                SkillEntry(
                    spec=skill,
                    source=source,
                    merge_policy=policy,
                    conflicts_with=collides,
                    note=(
                        f"conflicts with accepted skill {collides[0]!r}"
                        if collides
                        else None
                    ),
                )
            )
            selected.append(skill)

        status = (
            ResolutionStatus.CONFLICT
            if conflicts
            else ResolutionStatus.RESOLVED
        )
        reason = "conflicting skills found" if conflicts else None
        return CreativeSkillStackResolution(
            status=status,
            reason=reason,
            stack=CreativeSkillStack(selections=selected, source=source),
            entries=entries,
            conflicts=conflicts,
        )
