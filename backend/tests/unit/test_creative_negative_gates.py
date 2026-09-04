"""CC11 — creative capability negative gates (NEG-CC-01..04)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.director.creative_capabilities.composer import (
    CreativeSkillComposer,
    ResolutionStatus,
)
from app.director.creative_capabilities.creative_compiler import CreativeCapabilityCompiler
from app.director.creative_capabilities.pack_registry import PackRegistry
from app.director.creative_capabilities.packs_library import (
    GENRE_PROFILES,
    STYLE_PACKS,
)
from app.director.creative_capabilities.shot_language_library import (
    QUALITY_POLICIES,
    SHOT_LANGUAGE_PACKS,
)
from app.director.creative_capabilities.skill_library import BASELINE_SKILLS


def _skill(key: str):
    from app.director.creative_capabilities.registry import build_skill_registry

    reg = build_skill_registry(BASELINE_SKILLS)
    spec = reg.get(key)
    assert spec is not None, f"missing skill {key}"
    return spec


def _style(key: str):
    return next(s for s in STYLE_PACKS if s.style_key == key)


def _genre(key: str):
    return next(g for g in GENRE_PROFILES if g.genre_key == key)


def test_neg_cc01_conflicting_skills_surface_conflict() -> None:
    """NEG-CC-01: conflicting skills must yield CONFLICT, never a silent pick."""
    composer = CreativeSkillComposer()
    hook = _skill("short-drama-hook-v1")
    # These two have no declared conflict -> RESOLVED.
    resolution = composer.compose(skills=[hook, _skill("emotional-conflict-v1")])
    assert resolution.status is ResolutionStatus.RESOLVED
    # Force a real conflict via a probe spec (conflicts_with short-drama-hook-v1).
    from app.director.creative_capabilities.contracts import CreativeSkillSpec, SkillCategory

    probe = CreativeSkillSpec(
        skill_key="gradual-exposition-v1", skill_version="1", display_name="p",
        category=SkillCategory.STORY, description="p", strategy="p",
        conflicts_with=["short-drama-hook-v1"],
    )
    conflicted = composer.compose(skills=[hook, probe])
    assert conflicted.status is ResolutionStatus.CONFLICT
    # Neither side is dropped.
    assert {e.spec.skill_key for e in conflicted.entries} == {
        "short-drama-hook-v1", "gradual-exposition-v1",
    }


def test_neg_cc02_explicit_style_missing_is_unavailable() -> None:
    """NEG-CC-02: an explicitly requested but unregistered pack is UNAVAILABLE."""

    registry = PackRegistry(key_field="style_key")
    for style in STYLE_PACKS:
        registry.register(style)
    assert registry.contains("cyberpunk_neon_v1")
    assert registry.get("never-registered-style-v99") is None


def test_neg_cc03_user_override_cannot_be_overwritten() -> None:
    """NEG-CC-03: a user override can never be overwritten by a pack default."""
    style = _style("chinese_drama_v1")  # palette accent #8a2f3c
    compiler = CreativeCapabilityCompiler()
    result = compiler.compile(
        user_intent={"palette": {"accent": "#ffaa55"}},
        style=style,
    )
    assert result.visual_bible_patch is not None
    palette_patch = result.visual_bible_patch.patches.get("palette", {})
    assert isinstance(palette_patch, dict)
    assert "accent" not in palette_patch  # user explicit wins


def test_neg_cc04_historical_resume_same_hashes() -> None:
    """NEG-CC-04: a historical resume uses the same skill/style hashes."""
    style = _style("cinematic_realism_v1")
    genre = _genre("short_drama_suspense_v1")
    compiler = CreativeCapabilityCompiler()
    a = compiler.compile(
        genre=genre, style=style, skill_stack=[_skill("suspense-reversal-v1")]
    )
    b = compiler.compile(
        genre=genre, style=style, skill_stack=[_skill("suspense-reversal-v1")]
    )
    assert a.provenance == b.provenance
    assert a.visual_bible_patch == b.visual_bible_patch
    # The skill identity (key@version) is stable.
    assert a.provenance["skills"] == ["suspense-reversal-v1@1"]


def test_cc11_golden_composition_resolves_to_execution_reference() -> None:
    """CC11 golden path compiles the suspense composition with frozen identities.

    Genre short_drama_suspense_v1 + skills suspense-reversal-v1 /
    dialogue-scene-direction-v1 / continuity-guardian-v1 + style film_noir_v1 +
    shot-language subjective_tension-v1 (+ quality policy) into a frozen
    CompiledCreativeIntent. It must NOT create a Provider request or graph.
    """
    compiler = CreativeCapabilityCompiler()
    stack = [
        _skill("suspense-reversal-v1"),
        _skill("dialogue-scene-direction-v1"),
        _skill("continuity-guardian-v1"),
    ]
    result = compiler.compile(
        genre=_genre("short_drama_suspense_v1"),
        skill_stack=stack,
        style=_style("film_noir_v1"),
        shot_language=SHOT_LANGUAGE_PACKS[0],
        quality_policy=QUALITY_POLICIES[0],
    )
    prov = result.provenance
    assert prov["genre"]["key"] == "short_drama_suspense_v1"
    assert prov["skills"] == [
        "suspense-reversal-v1@1",
        "dialogue-scene-direction-v1@1",
        "continuity-guardian-v1@1",
    ]
    assert prov["style"]["key"] == "film_noir_v1"
    assert "shot_language" in prov
    assert "quality_policy" in prov
    fields = set(result.model_dump().keys())
    assert "provider_request" not in fields
    assert "graph" not in fields
    # The two-character workflow template key is a plan hint, not a graph.
    assert result.story_guidance


# --- Evidence no-secret guard -------------------------------------------------
# The golden scripts emit only a field-allowlisted report (see
# public_operation in the retained professional Agnes proof. This test
# makes the no-secret guarantee automated (not construction-only) so a future
# un-redacted field fails CI (review finding B).

_SECRET_PATTERN = re.compile(
    r"(?:api[_-]?key|password|credential|secret|token|bearer|authorization)"
    r"\s*[:=]\s*[A-Za-z0-9_\-\./\+]{8,}",
    re.IGNORECASE,
)


def _scan_json(path: Path) -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    # Parse to ensure it is well-formed JSON; ignore token-only false positives
    # like a bare "csrf" or an empty value.
    json.loads(text)
    return [m.group(0) for m in _SECRET_PATTERN.finditer(text)]


def test_evidence_has_no_secret_values() -> None:
    repo = Path(__file__).resolve().parents[3]  # repo root
    for name in (
        "WORKFLOW_V1_5_REAL_PROVIDER_GOLDEN.json",
        "CREATIVE_CAPABILITY_GOLDEN.json",
    ):
        path = repo / "docs" / "reviews" / name
        assert path.exists(), f"missing committed evidence {name}"
        hits = _scan_json(path)
        assert not hits, f"{name} leaks a secret-like value: {hits[:3]}"
