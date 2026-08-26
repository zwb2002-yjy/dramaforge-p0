"""P8-07 SceneAssembler (03 §78).

Deterministic assembly of a semantic SceneLayoutSpec into concrete coordinates.
The LLM provides only the semantic layout; the assembler owns the coordinates,
never the LLM.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GRID_SIZE = 20  # normalized 0..20 coordinate space


class SceneObjectSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    name: str
    position: Literal["north", "south", "east", "west", "center"] = "center"
    note: str | None = None


class CharacterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    enters_from: Literal["north", "south", "east", "west"] | None = None
    position: str | None = None


class SceneLayoutSpec(BaseModel):
    """Semantic layout provided by the LLM (never final coordinates)."""

    model_config = ConfigDict(extra="forbid")

    door: SceneObjectSpec | None = None
    windows: list[SceneObjectSpec] = Field(default_factory=list)
    furniture: list[SceneObjectSpec] = Field(default_factory=list)
    characters: list[CharacterSpec] = Field(default_factory=list)
    room_size: str = "medium"


_POSITION_XY: dict[str, tuple[int, int]] = {
    "north": (10, 3),
    "south": (10, 17),
    "east": (17, 10),
    "west": (3, 10),
    "center": (10, 10),
}


def _norm(value: int) -> float:
    return round(value / GRID_SIZE, 4)


class SceneAssembler:
    """Deterministically converts a semantic layout into 2D coordinates."""

    def assemble(self, spec: SceneLayoutSpec) -> dict[str, object]:
        elements: list[dict[str, object]] = []
        if spec.door is not None:
            x, y = _POSITION_XY[spec.door.position]
            elements.append(
                {"kind": "door", "name": spec.door.name, "x": _norm(x), "y": _norm(y)}
            )
        for window in spec.windows:
            x, y = _POSITION_XY[window.position]
            elements.append(
                {"kind": "window", "name": window.name, "x": _norm(x), "y": _norm(y)}
            )
        for furniture in spec.furniture:
            x, y = _POSITION_XY[furniture.position]
            elements.append(
                {
                    "kind": furniture.kind,
                    "name": furniture.name,
                    "x": _norm(x),
                    "y": _norm(y),
                    "note": furniture.note,
                }
            )
        for index, character in enumerate(spec.characters):
            if character.enters_from is not None:
                x, y = _POSITION_XY[character.enters_from]
            else:
                x, y = (10, 10 + index * 2)
            elements.append(
                {
                    "kind": "character",
                    "name": character.name,
                    "x": _norm(x),
                    "y": _norm(y),
                    "enters_from": character.enters_from,
                }
            )
        return {
            "room_size": spec.room_size,
            "grid_size": GRID_SIZE,
            "elements": elements,
            "generator": "deterministic_scene_assembler_v1",
        }
