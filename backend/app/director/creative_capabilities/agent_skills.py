"""Bounded, detached Agent context from the existing creative skill contracts.

This module only reads server-validated profile selections and compiles creative
guidance. It grants no tools and applies no proposal, production or formal fact.
Freeze the returned JSON on the Turn; recovery must use that snapshot rather
than resolve the current library again.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from app.director.creative_capabilities.composer import (
    CreativeSkillComposer,
    ResolutionStatus,
)
from app.director.creative_capabilities.contracts import ContentStage
from app.director.creative_capabilities.creative_compiler import CreativeCapabilityCompiler
from app.director.creative_capabilities.packs import GenreProfileSpec, StylePackSpec
from app.director.creative_capabilities.registry import CreativeSkillRegistry, build_skill_registry
from app.director.creative_capabilities.shot_language import ShotLanguagePackSpec
from app.director.creative_capabilities.skill_library import BASELINE_SKILLS

_MAX_SKILLS = 32
_MAX_CONTEXT_BYTES = 65_536


def _json(value: object) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("Agent skill context must contain finite JSON values") from exc


def _detached(values: dict[str, object] | None, max_bytes: int) -> dict[str, object]:
    encoded = _json(values or {})
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ValueError("Agent skill context exceeds byte limit")
    result = json.loads(encoded)
    if not isinstance(result, dict):
        raise ValueError("Agent creative values must be an object")
    return result


def _selection(values: Sequence[str], label: str) -> list[str]:
    if isinstance(values, (str, bytes)) or len(values) > _MAX_SKILLS:
        raise ValueError(f"Invalid {label} skill selection")
    keys = list(values)
    if any(not isinstance(key, str) or not key or key != key.strip() for key in keys):
        raise ValueError(f"Invalid {label} skill identity")
    if len(set(keys)) != len(keys):
        raise ValueError(f"Duplicate {label} skill identity")
    return keys


def build_agent_skill_context(
    *,
    selected_skill_ids: Sequence[str],
    requested_skill_ids: Sequence[str] | None = None,
    profile_version: int | None = None,
    stage: ContentStage | None = None,
    user_intent: dict[str, object] | None = None,
    accepted_proposal: dict[str, object] | None = None,
    project_context: dict[str, object] | None = None,
    genre: GenreProfileSpec | None = None,
    style: StylePackSpec | None = None,
    shot_language: ShotLanguagePackSpec | None = None,
    registry: CreativeSkillRegistry | None = None,
    max_bytes: int = 24_000,
) -> dict[str, object]:
    """Return method-only guidance for selected skills, with frozen identities.

    ``selected_skill_ids`` and ``profile_version`` come from the owned canonical
    ProjectCreativeProfile, never from model output. A model may request a subset
    but may not activate a recommendation or an unselected library skill.
    ``accepted_proposal`` contains only server-verified accepted values. Creative
    input dictionaries are data, not authority for tool permissions or user gates.

    The existing compiler owns user > accepted > project > pack precedence.
    Stage-inapplicable profile skills are reported as inactive; an explicit
    request for such a skill is rejected. No input or library object is mutated.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= _MAX_CONTEXT_BYTES:
        raise ValueError("Invalid Agent skill context byte limit")
    if profile_version is not None and (type(profile_version) is not int or profile_version < 1):
        raise ValueError("Invalid creative profile version")
    selected = _selection(selected_skill_ids, "profile")
    requested = (
        selected if requested_skill_ids is None else _selection(requested_skill_ids, "requested")
    )
    if not set(requested).issubset(selected):
        raise ValueError("Requested skill is not selected in the creative profile")
    library = registry if registry is not None else build_skill_registry(BASELINE_SKILLS)
    selected_specs = {}
    for key in selected:
        spec = library.get(key)
        if spec is None:
            raise ValueError("Selected creative skill is unavailable")
        # Existing contracts contain mutable lists despite being frozen models.
        selected_specs[key] = spec.model_copy(deep=True)

    active = []
    inactive = []
    for key in requested:
        spec = selected_specs[key]
        if stage is not None and spec.applicable_stages and stage not in spec.applicable_stages:
            if requested_skill_ids is not None:
                raise ValueError("Requested skill does not apply to the current stage")
            inactive.append(key)
        else:
            active.append(spec)
    resolution = CreativeSkillComposer().compose(skills=active, source="explicit")
    if resolution.status != ResolutionStatus.RESOLVED:
        raise ValueError("Selected creative skills conflict")

    compiled = CreativeCapabilityCompiler().compile(
        user_intent=_detached(user_intent, max_bytes),
        accepted_proposal=_detached(accepted_proposal, max_bytes),
        project_context=_detached(project_context, max_bytes),
        genre=genre,
        style=style,
        shot_language=shot_language,
        skill_stack=resolution.stack,
    )
    guidance = []
    for spec, item in zip(active, compiled.skill_guidance, strict=True):
        guidance.append(
            {
                **item,
                "display_name": spec.display_name,
                "required_context": list(spec.required_context),
                "inputs": [field.model_dump(mode="json") for field in spec.input_contract],
            }
        )
    snapshot: dict[str, object] = {
        "profile_version": profile_version,
        "selected_skill_ids": selected,
        "requested_skill_ids": list(requested),
        "inactive_skill_ids": inactive,
        "stage": stage.value if stage is not None else None,
        "authority": {
            "kind": "creative_method_only",
            "grants_tool_permissions": False,
            "bypasses_user_gates": False,
            "value_precedence": [
                "user_confirmed",
                "accepted_proposal",
                "project_override",
                "pack_default",
            ],
        },
        "skill_guidance": guidance,
        "effective_values": compiled.effective_values,
        "value_sources": compiled.value_sources,
        "overridden_defaults": compiled.overridden_defaults,
        "provenance": compiled.provenance,
    }
    snapshot["context_hash"] = hashlib.sha256(_json(snapshot).encode("utf-8")).hexdigest()
    return _detached(snapshot, max_bytes)
