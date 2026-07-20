"""Four-layer continuity checks."""

from __future__ import annotations

from app.consistency.continuity import continuity_four_layers


def test_continuity_passes_aligned_shot() -> None:
    r = continuity_four_layers(
        subtitle="The city never sleeps.",
        visual_desc="Lin Xia medium shot neon rain street city glow",
        lead_name="Lin Xia",
    )
    assert r.status in {"passed", "warning"}
    assert not any(v.severity == "block" for v in r.violations)


def test_continuity_blocks_empty_subtitle() -> None:
    r = continuity_four_layers(subtitle="  ", visual_desc="neon rain street")
    assert r.status == "blocked"
    assert any(v.rule_key == "subtitle.non_empty" for v in r.violations)


def test_continuity_blocks_missing_prop() -> None:
    r = continuity_four_layers(
        subtitle="Look at the phone",
        visual_desc="Lin Xia medium shot empty hands",
        lead_name="Lin Xia",
        prop_mentioned="phone",
        prop_in_visual=False,
    )
    assert r.status == "blocked"
    assert any(v.layer == "prop" for v in r.violations)


def test_continuity_blocks_costume_mismatch() -> None:
    r = continuity_four_layers(
        subtitle="I refuse.",
        visual_desc="Lin Xia rooftop dawn",
        lead_name="Lin Xia",
        costume_locked="wet jacket",
        costume_in_visual="red dress",
    )
    assert r.status == "blocked"
    assert any(v.rule_key == "costume.locked_match" for v in r.violations)


def test_violation_has_remediation_and_shot_link() -> None:
    r = continuity_four_layers(
        subtitle="",
        visual_desc="x",
        shot_id="shot-1",
        character_asset_id="asset-1",
    )
    assert r.violations
    v = r.violations[0]
    assert v.remediation
    assert v.shot_id == "shot-1"
