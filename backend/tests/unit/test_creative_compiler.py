"""CC9 — CreativeCapabilityCompiler priority gate + provenance."""

from __future__ import annotations

from app.director.creative_capabilities.creative_compiler import (
    CreativeCapabilityCompiler,
)
from app.director.creative_capabilities.packs_library import (
    GENRE_PROFILES,
    STYLE_PACKS,
)
from app.director.creative_capabilities.shot_language_library import (
    QUALITY_POLICIES,
    SHOT_LANGUAGE_PACKS,
)
from app.director.creative_capabilities.skill_library import BASELINE_SKILLS


def _style(key: str):
    return next(s for s in STYLE_PACKS if s.style_key == key)


def _genre(key: str):
    return next(g for g in GENRE_PROFILES if g.genre_key == key)


def test_user_explicit_value_beats_style_default() -> None:
    """Style blue palette vs user warm amber -> warm amber (the CC9 gate)."""
    style = _style("film_noir_v1")  # palette has a strong accent role
    compiler = CreativeCapabilityCompiler()
    result = compiler.compile(
        user_intent={"palette": {"accent": "#ffaa55"}, "note": "warm amber"},
        style=style,
    )
    assert result.visual_bible_patch is not None
    # The user's explicit warm-amber palette is preserved; the style default for
    # that role is NOT applied because the user already made an explicit choice.
    # The patch only fills roles the user/project did not set.
    patches = result.visual_bible_patch.patches
    palette_patch = patches.get("palette", {})
    assert isinstance(palette_patch, dict)
    assert "accent" not in palette_patch


def test_style_default_applies_when_user_silent() -> None:
    style = _style("cinematic_realism_v1")
    compiler = CreativeCapabilityCompiler()
    result = compiler.compile(style=style, project_context={})
    assert result.visual_bible_patch is not None
    assert "lighting" in result.visual_bible_patch.patches
    assert result.reference_guidance
    assert result.visual_bible_patch.provenance == "style-pack"


def test_product_value_priority() -> None:
    """explicit project value > pack default: project override wins."""
    style = _style("cinematic_realism_v1")
    compiler = CreativeCapabilityCompiler()
    result = compiler.compile(
        project_context={"lighting": "hard studio rim"},
        style=style,
    )
    assert result.visual_bible_patch is not None
    assert "lighting" not in result.visual_bible_patch.patches


def test_genre_story_guidance_respects_user_override() -> None:
    genre = _genre("short_drama_suspense_v1")
    compiler = CreativeCapabilityCompiler()
    result = compiler.compile(
        user_intent={"story_rhythm": "slow_burn"},
        genre=genre,
    )
    assert "story_rhythm" not in result.story_guidance  # user explicitly chose
    assert "hook_strategy" in result.story_guidance  # no user value -> default


def test_genre_hook_and_turn_respect_user_override() -> None:
    """The priority gate (explicit user > pack default) applies to every genre
    field, not just story_rhythm/scene_pacing (G-CC-03 / review finding A)."""
    genre = _genre("short_drama_suspense_v1")
    compiler = CreativeCapabilityCompiler()
    result = compiler.compile(
        user_intent={"hook_strategy": "user's own hook", "turn_frequency": "user"},
        project_context={"story_rhythm": "project_value"},
        genre=genre,
    )
    # User's explicit hook/turn win over the genre default -> suppressed.
    assert "hook_strategy" not in result.story_guidance
    assert "turn_frequency" not in result.story_guidance
    # Project's story_rhythm is explicit and wins over the genre default too.
    assert "story_rhythm" not in result.story_guidance


def test_provenance_froze_all_pack_identities() -> None:
    style = _style("cinematic_realism_v1")
    genre = _genre("short_drama_suspense_v1")
    shot_language = SHOT_LANGUAGE_PACKS[0]
    quality = QUALITY_POLICIES[0]
    compiler = CreativeCapabilityCompiler()
    result = compiler.compile(
        style=style,
        genre=genre,
        skill_stack=list(BASELINE_SKILLS[:2]),
        shot_language=shot_language,
        quality_policy=quality,
    )
    prov = result.provenance
    assert prov["genre"]["key"] == "short_drama_suspense_v1"
    assert prov["genre"]["contract_hash"] == genre.contract_hash
    assert prov["style"]["key"] == "cinematic_realism_v1"
    assert prov["style"]["contract_hash"] == style.contract_hash
    assert prov["shot_language"]["key"] == shot_language.pack_key
    assert prov["quality_policy"]["key"] == quality.policy_key
    assert prov["skills"]
    assert prov["skills"][0].endswith("@1")


def test_provenance_identical_across_runs_for_resume() -> None:
    """G-CC-04: a historical resume uses the same hashes."""
    style = _style("chinese_drama_v1")
    compiler = CreativeCapabilityCompiler()
    a = compiler.compile(style=style, genre=_genre("short_drama_romance_v1"))
    b = compiler.compile(style=style, genre=_genre("short_drama_romance_v1"))
    assert a.provenance == b.provenance
    assert a.visual_bible_patch == b.visual_bible_patch


def test_compiler_output_is_frozen_and_forbid_extra() -> None:
    import pytest
    from app.director.creative_capabilities.creative_compiler import CompiledCreativeIntent
    from pydantic import ValidationError

    out = CreativeCapabilityCompiler().compile(style=_style("cinematic_realism_v1"))
    with pytest.raises(ValidationError):
        CompiledCreativeIntent.model_validate({**out.model_dump(), "extra": 1})


def test_compiler_does_not_create_provider_or_graph() -> None:

    out = CreativeCapabilityCompiler().compile(
        style=_style("cinematic_realism_v1"),
        genre=_genre("short_drama_suspense_v1"),
    )
    # A compiled intent only carries guidance/patches/provenance — no provider
    # request, no graph definition.
    fields = set(out.model_dump().keys())
    assert {"story_guidance", "visual_bible_patch", "provenance"} <= fields
    assert "provider_request" not in fields
    assert "graph" not in fields


def test_effective_values_follow_all_four_priority_layers_and_explain_defaults() -> None:
    style = _style("cinematic_realism_v1").model_copy(
        update={"production_design": "black suit on the lead"}
    )
    shot_language = SHOT_LANGUAGE_PACKS[1].model_copy(
        update={"camera_motion": "dolly_in"}
    )
    result = CreativeCapabilityCompiler().compile(
        user_intent={
            "production_design": "white suit on the lead",
            "camera_motion": "static_no_push",
        },
        accepted_proposal={
            "production_design": "red suit proposal",
            "camera_motion": "slow_push proposal",
        },
        project_context={
            "production_design": "navy suit project override",
            "camera_motion": "tripod project override",
        },
        style=style,
        shot_language=shot_language,
    )
    assert result.effective_values["production_design"] == "white suit on the lead"
    assert result.effective_values["camera_motion"] == "static_no_push"
    assert result.value_sources["production_design"] == "user_confirmed"
    assert result.value_sources["camera_motion"] == "user_confirmed"
    overridden = {row["path"]: row for row in result.overridden_defaults}
    assert overridden["production_design"]["default_value"] == "black suit on the lead"
    assert overridden["production_design"]["effective_source"] == "user_confirmed"
    assert overridden["camera_motion"]["default_value"] == "dolly_in"
    assert result.shot_director_intent_patch is not None
    assert result.shot_director_intent_patch.camera_motion is None


def test_selected_skill_and_shot_language_compile_real_semantics_not_only_identity() -> None:
    skill = next(item for item in BASELINE_SKILLS if item.skill_key == "emotional-performance-v1")
    shot_language = SHOT_LANGUAGE_PACKS[0]
    result = CreativeCapabilityCompiler().compile(
        skill_stack=[skill],
        shot_language=shot_language,
    )
    assert result.skill_guidance[0]["strategy"] == skill.strategy
    assert result.skill_guidance[0]["outputs"]
    assert skill.quality_hints[0] in result.quality_hints
    assert result.shot_director_intent_patch is not None
    assert result.shot_director_intent_patch.camera_motion == shot_language.camera_motion
    assert result.shot_director_intent_patch.reaction_rule == shot_language.reaction_strategy


def test_nested_saved_shot_values_override_alias_defaults_while_blank_fields_do_not() -> None:
    shot_language = SHOT_LANGUAGE_PACKS[1].model_copy(update={"camera_motion": "dolly_in"})
    explicit = CreativeCapabilityCompiler().compile(
        user_intent={
            "framing": {"shot_size": "", "angle": ""},
            "camera": {"movement": "static_no_push", "focal_length_mm": 50},
            "continuity_constraints": [],
        },
        shot_language=shot_language,
    )
    assert explicit.effective_values["camera_motion"] == "static_no_push"
    assert explicit.value_sources["camera_motion"] == "user_confirmed"
    assert explicit.shot_director_intent_patch is not None
    assert explicit.shot_director_intent_patch.camera_motion is None
    assert explicit.shot_director_intent_patch.lens_intent is None
    # Blank/default form fields do not suppress actual pack guidance.
    assert explicit.shot_director_intent_patch.shot_size == shot_language.preferred_shot_sizes[0]
    assert explicit.shot_director_intent_patch.continuity == shot_language.continuity_rules
