"""Additional published production graph templates (WF4).

Each template is registered as a distinct ``WorkflowTemplateSpec`` and carries at
least one real contract difference: reference roles, graph topology, quality
policy, capability requirements or repair policy.  They are provider-neutral.
"""

from __future__ import annotations

from collections.abc import Iterable


def _node(key: str, node_type: str, display_name: str) -> dict[str, object]:
    return {
        "key": key,
        "type": node_type,
        "display_name": display_name,
        "cacheable": True,
    }


def single_character_monologue_definition(
    *,
    character_reference_keys: Iterable[str],
    primary_character_reference_key: str,
    context: dict[str, object],
) -> dict[str, object]:
    """Single-character monologue: voice is primary, no timed subtitle track.

    Graph topology differs from dialogue-post-dub by dropping the ``subtitle``
    node: a monologue is a continuous character performance, not a post-dub
    dialogue exchange.  Repair policy emphasizes identity drift.
    """
    reference_keys = tuple(dict.fromkeys(character_reference_keys))
    if primary_character_reference_key not in reference_keys:
        raise ValueError("primary character reference must be present in the graph")
    nodes = [
        *[
            _node(key, "keyframe", f"Character reference: {key.removeprefix('character_')}")
            for key in reference_keys
        ],
        _node("prompt", "prompt_compose", "Monologue prompt contract"),
        _node("keyframe", "keyframe", "Shot keyframe"),
        _node("identity_review", "identity_review", "Identity evidence"),
        _node("video", "video", "Shot video"),
        _node("video_drift_review", "video_review", "Video drift evidence"),
        _node("voice", "voice", "Monologue voice"),
        _node("composite", "composite", "Shot composite"),
        _node("continuity_review", "continuity_review", "Continuity evidence"),
    ]
    edges = [
        ["prompt", "keyframe"],
        [primary_character_reference_key, "keyframe"],
        ["keyframe", "identity_review"],
        ["keyframe", "video"],
        ["video", "video_drift_review"],
        ["video", "composite"],
        ["voice", "composite"],
        ["composite", "continuity_review"],
    ]
    return {
        "template_key": "single-character-monologue-v1",
        "template_version": "1.0.0",
        "quality_policy_id": "monologue-quality-v1",
        "nodes": nodes,
        "edges": edges,
        **context,
    }


def two_character_dialogue_definition(
    *,
    character_reference_keys: Iterable[str],
    primary_character_reference_key: str,
    context: dict[str, object],
) -> dict[str, object]:
    """Two-character dialogue: explicit per-character reference + per-character voice.

    Genuine contract difference from the single-character dialogue template:
    requires two subject references and two voice tracks, and the identity
    review is composed from both characters rather than one primary reference.
    """
    reference_keys = tuple(dict.fromkeys(character_reference_keys))
    if primary_character_reference_key not in reference_keys:
        raise ValueError("primary character reference must be present in the graph")
    if len(reference_keys) < 2:
        raise ValueError("two-character dialogue requires at least two references")
    nodes = [
        *[
            _node(key, "keyframe", f"Character reference: {key.removeprefix('character_')}")
            for key in reference_keys
        ],
        _node("prompt", "prompt_compose", "Two-character prompt contract"),
        _node("keyframe", "keyframe", "Shot keyframe"),
        _node("identity_review", "identity_review", "Per-character identity evidence"),
        _node("video", "video", "Shot video"),
        _node("video_drift_review", "video_review", "Video drift evidence"),
        _node("voice_a", "voice", "Character A voice"),
        _node("voice_b", "voice", "Character B voice"),
        _node("composite", "composite", "Shot composite"),
        _node("continuity_review", "continuity_review", "Continuity evidence"),
    ]
    edges = [
        ["prompt", "keyframe"],
        [primary_character_reference_key, "keyframe"],
        *[[key, "keyframe"] for key in reference_keys],
        ["keyframe", "identity_review"],
        ["keyframe", "video"],
        ["video", "video_drift_review"],
        ["video", "composite"],
        ["voice_a", "composite"],
        ["voice_b", "composite"],
        ["composite", "continuity_review"],
    ]
    return {
        "template_key": "two-character-dialogue-v1",
        "template_version": "1.0.0",
        "quality_policy_id": "two-character-dialogue-quality-v1",
        "nodes": nodes,
        "edges": edges,
        **context,
    }


def action_motion_shot_definition(
    *,
    character_reference_keys: Iterable[str],
    primary_character_reference_key: str,
    context: dict[str, object],
) -> dict[str, object]:
    """Action / high-motion shot: no dialogue voice, motion + drift emphasis.

    Graph topology omits ``voice`` and ``subtitle``; the repair policy is
    motion-focused (body anatomy, limb separation) rather than dialogue sync.
    """
    reference_keys = tuple(dict.fromkeys(character_reference_keys))
    if primary_character_reference_key not in reference_keys:
        raise ValueError("primary character reference must be present in the graph")
    nodes = [
        *[
            _node(key, "keyframe", f"Character reference: {key.removeprefix('character_')}")
            for key in reference_keys
        ],
        _node("prompt", "prompt_compose", "Action prompt contract"),
        _node("keyframe", "keyframe", "Shot keyframe"),
        _node("identity_review", "identity_review", "Identity evidence"),
        _node("video", "video", "Shot video"),
        _node("video_drift_review", "video_review", "Motion/video drift evidence"),
        _node("composite", "composite", "Shot composite"),
        _node("continuity_review", "continuity_review", "Continuity evidence"),
    ]
    edges = [
        ["prompt", "keyframe"],
        [primary_character_reference_key, "keyframe"],
        ["keyframe", "identity_review"],
        ["keyframe", "video"],
        ["video", "video_drift_review"],
        ["video", "composite"],
        ["composite", "continuity_review"],
    ]
    return {
        "template_key": "action-motion-shot-v1",
        "template_version": "1.0.0",
        "quality_policy_id": "action-motion-quality-v1",
        "nodes": nodes,
        "edges": edges,
        **context,
    }


def establishing_reaction_insert_definition(
    *,
    character_reference_keys: Iterable[str],
    primary_character_reference_key: str,
    context: dict[str, object],
) -> dict[str, object]:
    """Establishing / reaction / insert shot: low character-control requirement.

    No identity review node: an establishing or insert shot does not require a
    controlled subject identity.  Environment reference is the primary input.
    """
    nodes = [
        _node("environment", "keyframe", "Environment reference"),
        _node("prompt", "prompt_compose", "Establishing prompt contract"),
        _node("keyframe", "keyframe", "Shot keyframe"),
        _node("video", "video", "Shot video"),
        _node("video_drift_review", "video_review", "Video drift evidence"),
        _node("composite", "composite", "Shot composite"),
        _node("continuity_review", "continuity_review", "Continuity evidence"),
    ]
    edges = [
        ["environment", "prompt"],
        ["prompt", "keyframe"],
        ["keyframe", "video"],
        ["video", "video_drift_review"],
        ["video", "composite"],
        ["composite", "continuity_review"],
    ]
    return {
        "template_key": "establishing-reaction-insert-v1",
        "template_version": "1.0.0",
        "quality_policy_id": "establishing-quality-v1",
        "nodes": nodes,
        "edges": edges,
        **context,
    }


def montage_sequence_definition(
    *,
    character_reference_keys: Iterable[str],
    primary_character_reference_key: str,
    context: dict[str, object],
) -> dict[str, object]:
    """Scene-scope montage sequence: aggregates multiple shot pipelines.

    Contract difference: ``scope`` is a scene, not a shot.  The graph describes
    a sequence of short contributions assembled into a montage composite.
    """
    nodes = [
        _node("contributions", "montage_inputs", "Montage shot contributions"),
        _node("prompt", "prompt_compose", "Montage prompt contract"),
        _node("montage", "montage", "Montage composite"),
        _node("continuity_review", "continuity_review", "Montage continuity evidence"),
    ]
    edges = [
        ["contributions", "montage"],
        ["prompt", "montage"],
        ["montage", "continuity_review"],
    ]
    return {
        "template_key": "montage-sequence-v1",
        "template_version": "1.0.0",
        "quality_policy_id": "montage-sequence-quality-v1",
        "nodes": nodes,
        "edges": edges,
        **context,
    }
