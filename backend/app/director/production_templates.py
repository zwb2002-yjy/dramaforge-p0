"""Published Production Graph templates owned by the Director workflow.

These definitions are deliberately provider-neutral.  A confirmed
``SelectionPlan`` is frozen into each NodeRun snapshot when the template is
materialized; the graph itself only describes production dependencies.
"""

from __future__ import annotations

from collections.abc import Iterable

DIALOGUE_POST_DUB_SHOT_V1 = "dialogue-post-dub-shot-v1"
QUALITY_POLICY_V1 = "live-dialogue-quality-v1"


def _node(key: str, node_type: str, display_name: str) -> dict[str, object]:
    return {
        "key": key,
        "type": node_type,
        "display_name": display_name,
        "cacheable": True,
    }


def dialogue_post_dub_definition(
    *,
    character_reference_keys: Iterable[str],
    primary_character_reference_key: str,
    context: dict[str, object],
) -> dict[str, object]:
    """Return a fresh graph for one dialogue shot.

    Character references are media nodes rather than request-thread Provider
    calls.  Only the shot's primary on-screen character is injected into the
    current single-reference image compiler; additional fictional character
    references are still generated as auditable assets for later shots.
    """

    reference_keys = tuple(dict.fromkeys(character_reference_keys))
    if primary_character_reference_key not in reference_keys:
        raise ValueError("primary character reference must be present in the graph")
    nodes = [
        *[
            _node(key, "keyframe", f"Character reference: {key.removeprefix('character_')}")
            for key in reference_keys
        ],
        _node("prompt", "prompt_compose", "Prompt contract"),
        _node("keyframe", "keyframe", "Shot keyframe"),
        _node("face_review", "face_review", "Identity evidence"),
        _node("video", "video", "Shot video"),
        _node("video_drift_review", "video_review", "Video drift evidence"),
        _node("voice", "voice", "Mandarin dialogue voice"),
        _node("subtitle", "subtitle", "Subtitle"),
        _node("composite", "composite", "Shot composite"),
        _node("continuity_review", "continuity_review", "Continuity evidence"),
    ]
    edges = [
        ["prompt", "keyframe"],
        [primary_character_reference_key, "keyframe"],
        ["keyframe", "face_review"],
        ["keyframe", "video"],
        ["video", "video_drift_review"],
        ["video", "composite"],
        ["voice", "composite"],
        ["subtitle", "composite"],
        ["composite", "continuity_review"],
    ]
    return {
        "template_key": DIALOGUE_POST_DUB_SHOT_V1,
        "template_version": "1.0.0",
        "quality_policy_id": QUALITY_POLICY_V1,
        "nodes": nodes,
        "edges": edges,
        **context,
    }
