"""P0 continuity four-layer checks (rule → asset → shot → remediation)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContinuityViolation:
    rule_key: str
    layer: str  # character | prop | costume | subtitle_visual
    severity: str  # block | warning
    message: str
    remediation: str
    shot_id: str | None = None
    asset_id: str | None = None


@dataclass
class ContinuityReport:
    status: str  # passed | warning | blocked
    violations: list[ContinuityViolation] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "violations": [
                {
                    "rule_key": v.rule_key,
                    "layer": v.layer,
                    "severity": v.severity,
                    "message": v.message,
                    "remediation": v.remediation,
                    "shot_id": v.shot_id,
                    "asset_id": v.asset_id,
                }
                for v in self.violations
            ],
        }


def continuity_four_layers(
    *,
    subtitle: str,
    visual_desc: str,
    lead_name: str | None = None,
    prior_visual: str | None = None,
    shot_id: str | None = None,
    character_asset_id: str | None = None,
    prop_mentioned: str | None = None,
    prop_in_visual: bool | None = None,
    costume_locked: str | None = None,
    costume_in_visual: str | None = None,
) -> ContinuityReport:
    """Run four continuity layers; block rules cannot be soft-passed."""
    viols: list[ContinuityViolation] = []

    # Layer 1: character presence in deliverable shot
    if lead_name:
        if lead_name.lower() not in visual_desc.lower() and lead_name.split()[0].lower() not in visual_desc.lower():
            viols.append(
                ContinuityViolation(
                    rule_key="character.lead_in_frame",
                    layer="character",
                    severity="warning",
                    message=f"lead '{lead_name}' not mentioned in visual",
                    remediation="regenerate keyframe with locked lead prompt",
                    shot_id=shot_id,
                    asset_id=character_asset_id,
                )
            )

    # Layer 2: prop continuity
    if prop_mentioned and prop_in_visual is False:
        viols.append(
            ContinuityViolation(
                rule_key="prop.required_visible",
                layer="prop",
                severity="block",
                message=f"required prop '{prop_mentioned}' missing from visual",
                remediation="re-run keyframe/composite with prop reference",
                shot_id=shot_id,
            )
        )

    # Layer 3: costume continuity
    if costume_locked and costume_in_visual:
        if costume_locked.lower() not in costume_in_visual.lower():
            viols.append(
                ContinuityViolation(
                    rule_key="costume.locked_match",
                    layer="costume",
                    severity="block",
                    message=f"costume mismatch: locked='{costume_locked}' visual='{costume_in_visual}'",
                    remediation="restore locked wardrobe reference and re-run face/keyframe",
                    shot_id=shot_id,
                    asset_id=character_asset_id,
                )
            )

    # Layer 4: subtitle ↔ visual narrative overlap
    if not subtitle.strip():
        viols.append(
            ContinuityViolation(
                rule_key="subtitle.non_empty",
                layer="subtitle_visual",
                severity="block",
                message="empty subtitle on deliverable shot",
                remediation="edit subtitle node and re-run composite",
                shot_id=shot_id,
            )
        )
    elif not visual_desc.strip():
        viols.append(
            ContinuityViolation(
                rule_key="visual.non_empty",
                layer="subtitle_visual",
                severity="block",
                message="empty visual description",
                remediation="fill shot visual_description before composite",
                shot_id=shot_id,
            )
        )
    else:
        tokens = [t for t in subtitle.lower().replace("(", " ").replace(")", " ").split() if len(t) > 3]
        # skip pure stage directions like "(none)"
        meaningful = [t for t in tokens if t not in {"none", "whisper"}]
        if meaningful and not any(t in visual_desc.lower() for t in meaningful[:4]):
            viols.append(
                ContinuityViolation(
                    rule_key="subtitle.visual_overlap",
                    layer="subtitle_visual",
                    severity="warning",
                    message="subtitle tokens weak overlap with visual",
                    remediation="align dialogue wording with on-screen action",
                    shot_id=shot_id,
                )
            )

    # Cross-shot soft check
    if prior_visual and visual_desc:
        if prior_visual.strip() == visual_desc.strip():
            viols.append(
                ContinuityViolation(
                    rule_key="shot.duplicate_visual",
                    layer="character",
                    severity="warning",
                    message="visual identical to prior shot",
                    remediation="vary camera or action for adjacent shots",
                    shot_id=shot_id,
                )
            )

    if any(v.severity == "block" for v in viols):
        status = "blocked"
    elif viols:
        status = "warning"
    else:
        status = "passed"
    return ContinuityReport(status=status, violations=viols)
