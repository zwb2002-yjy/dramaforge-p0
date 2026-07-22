"""Canonical definition of the formal P0 Shot production pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

SHOT_PIPELINE_TEMPLATE_KEY = "shot-p0-v1"


@dataclass(frozen=True, slots=True)
class ShotPipelineNode:
    key: str
    node_type: str
    display_name: str


SHOT_PIPELINE_NODES: tuple[ShotPipelineNode, ...] = (
    ShotPipelineNode("prompt", "prompt_compose", "Prompt"),
    ShotPipelineNode("keyframe", "keyframe", "Keyframe"),
    ShotPipelineNode("face_review", "face_review", "Face review"),
    ShotPipelineNode("video", "video", "Video"),
    ShotPipelineNode("video_drift_review", "video_review", "Video drift review"),
    ShotPipelineNode("voice", "voice", "Voice"),
    ShotPipelineNode("subtitle", "subtitle", "Subtitle"),
    ShotPipelineNode("composite", "composite", "Composite"),
    ShotPipelineNode(
        "continuity_review",
        "continuity_review",
        "Continuity review",
    ),
)

SHOT_PIPELINE_EDGES: tuple[tuple[str, str], ...] = (
    ("prompt", "keyframe"),
    ("keyframe", "face_review"),
    ("face_review", "video"),
    ("video", "video_drift_review"),
    ("video_drift_review", "composite"),
    ("voice", "composite"),
    ("subtitle", "composite"),
    ("composite", "continuity_review"),
)

SHOT_NODE_BY_KEY: Mapping[str, ShotPipelineNode] = MappingProxyType(
    {node.key: node for node in SHOT_PIPELINE_NODES}
)
SHOT_NODES: tuple[str, ...] = tuple(SHOT_NODE_BY_KEY)
SHOT_EDGES = SHOT_PIPELINE_EDGES


def shot_pipeline_definition(**context: object) -> dict[str, object]:
    """Return a fresh JSON-safe graph definition for the formal Shot template."""
    reserved = {"nodes", "edges"}.intersection(context)
    if reserved:
        names = ", ".join(sorted(reserved))
        raise ValueError(f"pipeline context cannot replace canonical fields: {names}")
    return {
        "nodes": [
            {
                "key": node.key,
                "type": node.node_type,
                "display_name": node.display_name,
            }
            for node in SHOT_PIPELINE_NODES
        ],
        "edges": [list(edge) for edge in SHOT_PIPELINE_EDGES],
        **context,
    }
