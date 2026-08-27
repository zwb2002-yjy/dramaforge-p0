"""Multi-character shot participation contract (WF5).

A typed value object that records each visible character's explicit identity /
reference / control binding for a shot.  It is stored in
``Shot.director_state`` (JSON) and is NOT a new Character ORM.

Rules enforced here:
- At most ``MAX_VISIBLE_CONTROLLED_CHARACTERS`` visible controlled characters
  (a platform safety limit; a template may be stricter).
- No two participations may reference the same character id.
- Each visible participant must carry an ``asset_version_id`` (the frozen
  identity AssetVersion) unless the shot template explicitly permits an
  offscreen/background-only presence.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_VISIBLE_CONTROLLED_CHARACTERS = 4


class ScreenRole(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    BACKGROUND = "background"
    OFFSCREEN = "offscreen"


class DialogueRole(StrEnum):
    SPEAKING = "speaking"
    LISTENING = "listening"
    NONE = "none"


class ShotCharacterParticipation(BaseModel):
    """One character's participation and subject binding in a shot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    character_id: UUID
    asset_version_id: UUID | None = None
    screen_role: ScreenRole = ScreenRole.SECONDARY
    importance: int = Field(default=50, ge=0, le=100)
    wardrobe_asset_version_id: UUID | None = None
    identity_reference_ids: list[UUID] = Field(default_factory=list)
    position: str = ""
    pose: str = ""
    gaze_target: str = ""
    action: str = ""
    expression: str = ""
    dialogue_role: DialogueRole = DialogueRole.NONE

    @property
    def is_visible_controlled(self) -> bool:
        """True when the character occupies the frame and needs identity control.

        A visible (non-offscreen) character must carry an identity AssetVersion
        binding; the plan validator enforces that invariant.
        """
        return self.screen_role is not ScreenRole.OFFSCREEN


class ShotParticipationPlan(BaseModel):
    """A shot's full multi-character participation plan (stored in director_state)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    participations: list[ShotCharacterParticipation] = Field(default_factory=list)

    @property
    def visible_controlled(self) -> list[ShotCharacterParticipation]:
        return [item for item in self.participations if item.is_visible_controlled]

    @property
    def character_ids(self) -> list[UUID]:
        return [item.character_id for item in self.participations]

    @property
    def primary(self) -> ShotCharacterParticipation | None:
        for item in self.participations:
            if item.screen_role is ScreenRole.PRIMARY:
                return item
        return None

    @property
    def visible_controlled_count(self) -> int:
        return len(self.visible_controlled)

    @model_validator(mode="after")
    def validate_participation_plan(self) -> ShotParticipationPlan:
        ids = self.character_ids
        if len(ids) != len(set(ids)):
            raise ValueError("a character may participate at most once per shot")
        if self.visible_controlled_count > MAX_VISIBLE_CONTROLLED_CHARACTERS:
            raise ValueError(
                f"shot has {self.visible_controlled_count} visible controlled "
                f"characters (max {MAX_VISIBLE_CONTROLLED_CHARACTERS})"
            )
        for item in self.visible_controlled:
            if item.asset_version_id is None:
                raise ValueError(
                    f"visible character {item.character_id} is missing an "
                    "identity AssetVersion binding"
                )
        return self


def participation_director_state(plan: ShotParticipationPlan) -> dict[str, object]:
    """Serialize a participation plan into ``Shot.director_state``.

    Keeps the shot state backward-compatible: it stores the plan under
    ``workflow_participations`` without disturbing existing director_state keys.
    """
    return {
        "workflow_participations": [
            item.model_dump(mode="json") for item in plan.participations
        ],
        "max_visible_controlled_characters": MAX_VISIBLE_CONTROLLED_CHARACTERS,
    }
