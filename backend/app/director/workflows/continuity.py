"""Cross-scene continuity context + report + freeze (WF10).

A ``SceneContinuityContext`` carries the frozen AssetVersion identities, visual
bible, voice design and story entry/exit state so a later scene (or a resume)
uses the originally frozen AssetVersion (G-WF-08).  A ``SceneContinuityReport``
compares the dimensions and returns PASS / WARNING / BLOCKED; only a true
blocking contract issue stops production.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContinuityVerdict(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"


class SceneContinuityContext(BaseModel):
    """Frozen continuity context for one scene."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_id: UUID
    character_asset_versions: dict[str, UUID] = Field(default_factory=dict)
    wardrobe_asset_versions: dict[str, UUID] = Field(default_factory=dict)
    location_asset_versions: dict[str, UUID] = Field(default_factory=dict)
    visual_bible_revision: int | None = None
    voice_design: dict[str, str] = Field(default_factory=dict)
    story_entry_state: str = ""
    story_exit_target: str = ""
    previous_formal_evidence: list[UUID] = Field(default_factory=list)

    def freeze(self) -> SceneContinuityContext:
        """Return an immutable frozen copy (already frozen; idempotent)."""
        return self.model_copy()


class ContinuityDimensionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: str
    status: ContinuityVerdict
    detail: str = ""


class SceneContinuityReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_id: UUID
    overall: ContinuityVerdict = ContinuityVerdict.PASS
    results: list[ContinuityDimensionResult] = Field(default_factory=list)


def build_scene_continuity_report(
    *,
    scene_id: UUID,
    context: SceneContinuityContext,
    actual_asset_versions: dict[str, UUID],
) -> SceneContinuityReport:
    """Compare the frozen context against actual asset versions.

    Deterministic: every dimension whose frozen AssetVersion diverges is a
    WARNING; a missing frozen binding for a required character is BLOCKED.
    """
    results: list[ContinuityDimensionResult] = []
    all_versions = {
        f"character:{key}": value for key, value in context.character_asset_versions.items()
    }
    all_versions.update(
        {
            f"wardrobe:{key}": value
            for key, value in context.wardrobe_asset_versions.items()
        }
    )
    all_versions.update(
        {
            f"location:{key}": value
            for key, value in context.location_asset_versions.items()
        }
    )

    blocked = False
    for key, frozen in all_versions.items():
        actual = actual_asset_versions.get(key)
        if actual is None:
            results.append(
                ContinuityDimensionResult(
                    dimension=key,
                    status=ContinuityVerdict.BLOCKED,
                    detail="frozen binding is present but no actual binding found",
                )
            )
            blocked = True
        elif actual != frozen:
            results.append(
                ContinuityDimensionResult(
                    dimension=key,
                    status=ContinuityVerdict.WARNING,
                    detail=(
                        f"asset version changed: frozen {frozen}, actual {actual}"
                    ),
                )
            )
        else:
            results.append(
                ContinuityDimensionResult(
                    dimension=key,
                    status=ContinuityVerdict.PASS,
                    detail="asset version matches the frozen context",
                )
            )

    if blocked:
        overall = ContinuityVerdict.BLOCKED
    elif any(item.status is ContinuityVerdict.WARNING for item in results):
        overall = ContinuityVerdict.WARNING
    else:
        overall = ContinuityVerdict.PASS
    return SceneContinuityReport(scene_id=scene_id, overall=overall, results=results)


def persist_continuity_context(
    design_state: dict[str, object],
    context: SceneContinuityContext,
) -> dict[str, object]:
    """Store a frozen continuity context into ``Scene.design_state``."""
    result = dict(design_state)
    result["continuity_context"] = context.model_dump(mode="json")
    return result


def load_continuity_context(design_state: dict[str, object]) -> SceneContinuityContext | None:
    """Read a frozen continuity context from ``Scene.design_state``."""
    raw = design_state.get("continuity_context")
    if raw is None:
        return None
    return SceneContinuityContext.model_validate(raw)
