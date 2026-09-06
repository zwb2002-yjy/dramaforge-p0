"""CC5 + CC6 — genre profiles, style packs, and the VisualBible compiler."""

from __future__ import annotations

from app.director.creative_capabilities.packs import (
    StylePackSpec,
    VisualBiblePatch,
)
from app.director.creative_capabilities.packs_library import (
    GENRE_PROFILES,
    STYLE_PACKS,
)
from app.director.creative_capabilities.visual_bible import (
    VisualBibleCompiler,
    _value_at_path,
)


def test_six_genre_profiles_with_distinct_rhythm() -> None:
    assert len(GENRE_PROFILES) == 6
    keys = {g.genre_key for g in GENRE_PROFILES}
    assert len(keys) == 6
    # Genres have distinct story rhythm (structural identity, not just name).
    assert len({g.story_rhythm for g in GENRE_PROFILES}) >= 4
    for g in GENRE_PROFILES:
        assert g.contract_hash
        assert g.preferred_skill_stack


def test_ten_style_packs_structured_not_prompts() -> None:
    assert len(STYLE_PACKS) == 10
    keys = {s.style_key for s in STYLE_PACKS}
    assert len(keys) == 10
    for s in STYLE_PACKS:
        # A style pack must be structured, not a bare prompt string.
        assert s.lighting
        assert s.palette
        assert s.camera_behavior is not None
        assert s.motion_feel is not None
        assert s.production_design
        assert s.contract_hash


def test_style_packs_never_bind_a_provider() -> None:
    # No style references a provider/model name (model adaptation stays in the
    # Manifest + Compiler).
    for s in STYLE_PACKS:
        blob = " ".join(
            [
                s.description,
                s.lighting,
                s.composition,
                s.production_design,
                s.post_processing,
                " ".join(s.negative_tendencies),
                " ".join(s.reference_guidance),
            ]
        ).lower()
        for provider in ("agnes", "kling", "minimax", "volcengine", "deepseek", "seedream"):
            assert provider not in blob, f"{s.style_key} binds provider {provider}"


def test_value_at_path() -> None:
    data = {"palette": {"accent": "#fff"}, "lighting": "natural"}
    assert _value_at_path(data, "palette.accent") == "#fff"
    assert _value_at_path(data, "lighting") == "natural"
    assert _value_at_path(data, "missing") is None
    assert _value_at_path(data, "palette.missing") is None


def test_visual_bible_compiler_respects_explicit_project_value() -> None:
    style = next(s for s in STYLE_PACKS if s.style_key == "film_noir_v1")
    compiler = VisualBibleCompiler()
    # Project explicitly overrides lighting -> style default must NOT apply.
    patch = compiler.compile(
        style=style,
        project_values={"lighting": "soft studio"},
    )
    assert "lighting" not in patch.patches
    # Palette role absent in project -> style default applies.
    assert "palette" in patch.patches


def test_visual_bible_compiler_patches_missing_defaults() -> None:
    style = style_for("cinematic_realism_v1")
    patch = VisualBibleCompiler().compile(style=style, project_values={})
    assert patch.style_key == "cinematic_realism_v1"
    assert "lighting" in patch.patches
    assert "contrast" in patch.patches
    assert patch.patches["camera_behavior"] == "tripod"
    assert patch.patches["motion_feel"] == "weighted"
    assert patch.provenance == "style-pack"


def test_visual_bible_patch_is_frozen_and_forbid() -> None:
    import pytest
    from pydantic import ValidationError

    style = style_for("chinese_drama_v1")
    patch = VisualBibleCompiler().compile(style=style, project_values={})
    assert isinstance(patch, VisualBiblePatch)
    with pytest.raises(ValidationError):
        VisualBiblePatch(
            style_key="x", style_version="1", patches={}, suggestions=[], provenance="s", extra="x"
        )


def style_for(key: str) -> StylePackSpec:
    return next(s for s in STYLE_PACKS if s.style_key == key)
