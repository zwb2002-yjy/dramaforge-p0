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
