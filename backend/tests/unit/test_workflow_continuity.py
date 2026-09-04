"""WF10 — cross-scene continuity context / report / freeze."""

from __future__ import annotations

from uuid import uuid4

from app.director.workflows.continuity import (
    ContinuityVerdict,
    SceneContinuityContext,
    build_scene_continuity_report,
    load_continuity_context,
    persist_continuity_context,
)


def _context() -> SceneContinuityContext:
    return SceneContinuityContext(
        scene_id=uuid4(),
        character_asset_versions={"A": uuid4(), "B": uuid4()},
        wardrobe_asset_versions={"A": uuid4(), "B": uuid4()},
        location_asset_versions={"street": uuid4()},
        visual_bible_revision=3,
        voice_design={"A": "warm", "B": "cold"},
        story_entry_state="morning",
        story_exit_target="evening",
        previous_formal_evidence=[uuid4()],
    )


def test_continuity_context_freeze_and_resume_keeps_frozen_version() -> None:
    context = _context()
    frozen = context.freeze()
    # Scene 1 was submitted with Character A v2. Later the project moves to v3.
    assert frozen.character_asset_versions["A"] == context.character_asset_versions["A"]
    # A resume of Scene 1 reuses the originally frozen AssetVersion, not v3.
    resume_actual = {
        "character:A": context.character_asset_versions["A"],
        "character:B": context.character_asset_versions["B"],
        "wardrobe:A": context.wardrobe_asset_versions["A"],
        "wardrobe:B": context.wardrobe_asset_versions["B"],
        "location:street": context.location_asset_versions["street"],
    }
    report = build_scene_continuity_report(
        scene_id=context.scene_id,
        context=frozen,
        actual_asset_versions=resume_actual,
    )
    assert report.overall == ContinuityVerdict.PASS


def test_continuity_report_warns_on_asset_version_drift() -> None:
    context = _context()
    actual = {
        "character:A": uuid4(),  # drifted to a new version
        "character:B": context.character_asset_versions["B"],
        "wardrobe:A": context.wardrobe_asset_versions["A"],
        "wardrobe:B": context.wardrobe_asset_versions["B"],
        "location:street": context.location_asset_versions["street"],
    }
    report = build_scene_continuity_report(
        scene_id=context.scene_id, context=context, actual_asset_versions=actual
    )
    assert report.overall == ContinuityVerdict.WARNING


def test_continuity_report_blocks_on_missing_binding() -> None:
    context = _context()
    actual = {
        "character:B": context.character_asset_versions["B"],
        "wardrobe:A": context.wardrobe_asset_versions["A"],
        "wardrobe:B": context.wardrobe_asset_versions["B"],
        "location:street": context.location_asset_versions["street"],
    }
    report = build_scene_continuity_report(
        scene_id=context.scene_id, context=context, actual_asset_versions=actual
    )
    assert report.overall == ContinuityVerdict.BLOCKED


def test_persist_and_load_continuity_context_round_trip() -> None:
    context = _context()
    design_state = persist_continuity_context({}, context)
    loaded = load_continuity_context(design_state)
    assert loaded is not None
    assert loaded.scene_id == context.scene_id
    assert loaded.character_asset_versions == context.character_asset_versions
    assert load_continuity_context({}) is None
