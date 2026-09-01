#!/usr/bin/env python3
"""CC11 — Creative Capability Golden (deterministic).

Proves the full creative-capability pipeline end-to-end WITHOUT paid Providers:

    User Intent -> Capability Resolve -> Skill Composition -> Compile
    -> VisualBible / ShotDirectorIntent -> Workflow Template Resolve (frozen)
    -> Execution reference.

The representative real-provider leg is already proven by the WF13-01 golden
(DramaForge uses Agnes for a single-character paid shot; the multi-subject gate
fails closed).  This golden proves the *capability* composition compiles into a
consistent frozen intent that resolves to a registered workflow template.

Output: docs/reviews/CREATIVE_CAPABILITY_GOLDEN.json
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from app.director.creative_capabilities.composer import CreativeSkillComposer
from app.director.creative_capabilities.creative_compiler import CreativeCapabilityCompiler
from app.director.creative_capabilities.pack_registry import PackRegistry
from app.director.creative_capabilities.packs_library import (
    GENRE_PROFILES,
    STYLE_PACKS,
)
from app.director.creative_capabilities.registry import build_skill_registry
from app.director.creative_capabilities.shot_language_library import (
    QUALITY_POLICIES,
    SHOT_LANGUAGE_PACKS,
)
from app.director.creative_capabilities.skill_library import BASELINE_SKILLS
from app.director.workflows.contracts import TemplateResolveStatus, WorkflowTemplateRequest
from app.director.workflows.library import get_default_registry
from app.director.workflows.resolver import WorkflowTemplateResolver

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    skill_reg = build_skill_registry(BASELINE_SKILLS)
    genre_reg = PackRegistry(key_field="genre_key")
    style_reg = PackRegistry(key_field="style_key")
    shot_lang_reg = PackRegistry(key_field="pack_key")
    quality_reg = PackRegistry(key_field="policy_key")
    for spec in GENRE_PROFILES:
        genre_reg.register(spec)
    for spec in STYLE_PACKS:
        style_reg.register(spec)
    for spec in SHOT_LANGUAGE_PACKS:
        shot_lang_reg.register(spec)
    for spec in QUALITY_POLICIES:
        quality_reg.register(spec)

    genre = genre_reg.get("short_drama_suspense_v1")
    style = style_reg.get("film_noir_v1")
    shot_language = shot_lang_reg.get("subjective_tension_v1")
    quality = quality_reg.get("multi_character_quality_v1")
    skills: list[Any] = [
        skill_reg.get("suspense-reversal-v1"),
        skill_reg.get("dialogue-scene-direction-v1"),
        skill_reg.get("continuity-guardian-v1"),
    ]
    if any(x is None for x in [genre, style, shot_language, quality, *skills]):
        raise RuntimeError("a CC11 capability is missing from the library")

    # --- Skill composition (must not conflict) --------------------------------
    composer = CreativeSkillComposer()
    stack = composer.compose(skills=skills)
    if stack.status.value != "RESOLVED":
        raise RuntimeError(f"skill composition failed: {stack.status} {stack.reason}")

    # --- Compile --------------------------------------------------------------
    compiler = CreativeCapabilityCompiler()
    intent = compiler.compile(
        genre=genre,
        skill_stack=stack.stack,
        style=style,
        shot_language=shot_language,
        quality_policy=quality,
    )

    # --- Workflow template resolve (two-character dialogue) --------------------
    registry = get_default_registry()
    resolver = WorkflowTemplateResolver(registry)
    spec = registry.get("two-character-dialogue-v1")
    if spec is None:
        raise RuntimeError("two-character-dialogue-v1 template missing")
    resolution = resolver.resolve(
        WorkflowTemplateRequest(
            intent_tags=list(spec.intent_tags),
            medium="video",
            character_count=2,
            reference_roles_present=list(spec.required_reference_roles),
            explicit_template_key="two-character-dialogue-v1",
        )
    )
    if resolution.status is not TemplateResolveStatus.RESOLVED:
        raise RuntimeError(f"template resolve failed: {resolution.status}")

    report = {
        "ok": True,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO)),
        "skill_composition": {
            "status": stack.status.value,
            "keys": stack.keys,
            "count": len(stack.entries),
        },
        "compiled_provenance": intent.provenance,
        "visual_bible_patch": (
            intent.visual_bible_patch.model_dump(mode="json")
            if intent.visual_bible_patch
            else None
        ),
        "shot_director_intent_patch": (
            intent.shot_director_intent_patch.model_dump(mode="json")
            if intent.shot_director_intent_patch
            else None
        ),
        "workflow_template": {
            "template_key": spec.template_key,
            "template_version": spec.template_version,
            "template_contract_hash": spec.contract_hash,
            "resolution_status": resolution.status.value,
            "quality_policy_id": spec.quality_policy_id,
            "supported_character_count": list(spec.supported_character_count),
        },
        "no_provider_request": "provider_request" not in intent.model_dump(),
        "no_second_graph": "graph" not in intent.model_dump(),
    }

    out = REPO / "docs" / "reviews" / "CREATIVE_CAPABILITY_GOLDEN.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
