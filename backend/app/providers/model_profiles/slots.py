"""Model slots: the business-facing *purpose* a model serves (spec §5–§10).

A :class:`ModelSlot` answers "where in the production workflow is a model
needed" (``planning.script``, ``visual.keyframe``, ``video.shot``), while a
:class:`~app.providers.capabilities.Capability` answers "what the model can do"
(``text.generate``, ``image.generate``). Slots declare the capabilities they
require so a :class:`ProductionModelProfile` binding can be validated without
business code branching on a provider or model name (spec §134 rules 1–2).

P0 execution scope (spec §8) wires the first five slots into workflow nodes;
the remaining slots are valid configuration vocabulary for advanced mode and
future execution.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from app.providers.capabilities import Capability


class ModelSlot(StrEnum):
    """Stable business slot vocabulary. Never branch on a provider here."""

    PLANNING_BRIEF = "planning.brief"
    PLANNING_SCRIPT = "planning.script"
    PLANNING_STORYBOARD = "planning.storyboard"

    VISUAL_CHARACTER = "visual.character"
    VISUAL_STORYBOARD = "visual.storyboard"
    VISUAL_KEYFRAME = "visual.keyframe"
    VISUAL_IMAGE_EDIT = "visual.image_edit"

    VIDEO_SHOT = "video.shot"

    AUDIO_TTS = "audio.tts"


class ModelSlotDefinition(BaseModel):
    """One slot's capability contract (spec §9). Centralizes the Slot→Capability
    mapping instead of scattering it across business code."""

    slot: ModelSlot
    required_capabilities: list[Capability]
    fallback_slot: ModelSlot | None = None
    description: str


MODEL_SLOT_DEFINITIONS: dict[ModelSlot, ModelSlotDefinition] = {
    ModelSlot.PLANNING_BRIEF: ModelSlotDefinition(
        slot=ModelSlot.PLANNING_BRIEF,
        required_capabilities=[Capability.TEXT_GENERATE],
        description="生成与修改策划 Brief 文本。",
    ),
    ModelSlot.PLANNING_SCRIPT: ModelSlotDefinition(
        slot=ModelSlot.PLANNING_SCRIPT,
        required_capabilities=[Capability.TEXT_GENERATE],
        description="生成与修改剧本文本。",
    ),
    ModelSlot.PLANNING_STORYBOARD: ModelSlotDefinition(
        slot=ModelSlot.PLANNING_STORYBOARD,
        required_capabilities=[Capability.TEXT_GENERATE],
        description="从剧本推导分镜规划 / Shot Plan。",
    ),
    ModelSlot.VISUAL_CHARACTER: ModelSlotDefinition(
        slot=ModelSlot.VISUAL_CHARACTER,
        required_capabilities=[Capability.IMAGE_GENERATE],
        description="生成角色参考图（canonical）。",
    ),
    ModelSlot.VISUAL_STORYBOARD: ModelSlotDefinition(
        slot=ModelSlot.VISUAL_STORYBOARD,
        required_capabilities=[Capability.IMAGE_GENERATE],
        description="生成分镜示意草图。",
    ),
    ModelSlot.VISUAL_KEYFRAME: ModelSlotDefinition(
        slot=ModelSlot.VISUAL_KEYFRAME,
        required_capabilities=[Capability.IMAGE_GENERATE],
        description="生成镜头关键帧。",
    ),
    ModelSlot.VISUAL_IMAGE_EDIT: ModelSlotDefinition(
        slot=ModelSlot.VISUAL_IMAGE_EDIT,
        required_capabilities=[Capability.IMAGE_EDIT],
        description="基于参考图编辑 / 重绘图片。",
    ),
    ModelSlot.VIDEO_SHOT: ModelSlotDefinition(
        slot=ModelSlot.VIDEO_SHOT,
        required_capabilities=[
            Capability.VIDEO_TEXT_TO_VIDEO,
            Capability.VIDEO_IMAGE_TO_VIDEO,
            Capability.VIDEO_FIRST_LAST_FRAME,
            Capability.VIDEO_REFERENCE_TO_VIDEO,
        ],
        description=(
            "镜头视频。一个 Slot 可服务多个视频 Capability；具体模型不必支持全部，"
            "最终 Router 按实际请求 Capability 验证（spec §10）。"
        ),
    ),
    ModelSlot.AUDIO_TTS: ModelSlotDefinition(
        slot=ModelSlot.AUDIO_TTS,
        required_capabilities=[Capability.AUDIO_TTS],
        description="对白 / 旁白语音合成。",
    ),
}

# Slots whose workflow wiring is in P0 scope (spec §8 first batch).
P0_SLOTS: frozenset[ModelSlot] = frozenset(
    {
        ModelSlot.PLANNING_BRIEF,
        ModelSlot.PLANNING_SCRIPT,
        ModelSlot.PLANNING_STORYBOARD,
        ModelSlot.VISUAL_KEYFRAME,
        ModelSlot.VIDEO_SHOT,
    }
)

# Simple-mode groups (spec §30/§78): LLM / Image / Video map onto these slots.
# ``bindings`` stays the single source of truth; simple mode is a batch patch.
SIMPLE_MODE_SLOT_GROUPS: dict[str, list[ModelSlot]] = {
    "llm": [
        ModelSlot.PLANNING_BRIEF,
        ModelSlot.PLANNING_SCRIPT,
        ModelSlot.PLANNING_STORYBOARD,
    ],
    "image": [
        ModelSlot.VISUAL_CHARACTER,
        ModelSlot.VISUAL_STORYBOARD,
        ModelSlot.VISUAL_KEYFRAME,
    ],
    "video": [ModelSlot.VIDEO_SHOT],
}


def slot_definition(slot: ModelSlot) -> ModelSlotDefinition:
    """Return the definition for a slot, raising for unknown slots."""
    definition = MODEL_SLOT_DEFINITIONS.get(slot)
    if definition is None:
        raise KeyError(f"unknown model slot: {slot}")
    return definition


def slot_satisfies(slot: ModelSlot, capability: Capability) -> bool:
    """True when ``slot`` declares ``capability`` among its requirements."""
    return capability in slot_definition(slot).required_capabilities


def slots_for_capability(capability: Capability) -> list[ModelSlot]:
    """Slots that declare ``capability`` — used to filter the slot picker."""
    return [slot for slot, definition in MODEL_SLOT_DEFINITIONS.items()
            if capability in definition.required_capabilities]


def validate_slot_definitions() -> None:
    """Invariant check (M1 tests): unique ids, valid capabilities, acyclic
    fallback_slot graph."""
    seen: set[str] = set()
    for slot, definition in MODEL_SLOT_DEFINITIONS.items():
        if definition.slot != slot:
            raise ValueError(f"definition key {slot} does not match body {definition.slot}")
        if str(slot) in seen:
            raise ValueError(f"duplicate model slot id: {slot}")
        seen.add(str(slot))
        for capability in definition.required_capabilities:
            if not isinstance(capability, Capability):
                raise ValueError(f"slot {slot} has non-Capability requirement: {capability!r}")
    # Acyclic fallback graph: simple DFS cycle detection.
    visiting: set[ModelSlot] = set()
    visited: set[ModelSlot] = set()

    def visit(node: ModelSlot) -> None:
        if node in visited:
            return
        if node in visiting:
            raise ValueError(f"fallback_slot cycle detected at {node}")
        visiting.add(node)
        definition = MODEL_SLOT_DEFINITIONS.get(node)
        if definition is not None and definition.fallback_slot is not None:
            visit(definition.fallback_slot)
        visiting.discard(node)
        visited.add(node)

    for slot in MODEL_SLOT_DEFINITIONS:
        visit(slot)


validate_slot_definitions()
