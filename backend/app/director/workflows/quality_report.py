"""WF6/WF10 quality report contracts.

A per-character identity report so one drifting character can never be hidden by
an aggregate pass.  The overall status is derived from the recorded per-character
results; a failed/blocked character forces ``overall_status`` to ``blocked``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IdentityResultStatus(StrEnum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    BLOCKED = "blocked"


class PerCharacterIdentityResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    asset_id: UUID
    status: IdentityResultStatus
    evidence: str = ""
    rule: str = ""


class MultiCharacterIdentityReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    results: list[PerCharacterIdentityResult] = Field(default_factory=list)
    overall_status: Literal["passed", "needs_human", "blocked"] = "needs_human"

    @property
    def all_passed(self) -> bool:
        """Every character must pass; a single non-pass blocks an aggregate pass."""
        return bool(self.results) and all(
            item.status is IdentityResultStatus.PASSED for item in self.results
        )

    @model_validator(mode="after")
    def derive_overall(self) -> MultiCharacterIdentityReport:
        if (
            any(
                item.status
                in {IdentityResultStatus.FAILED, IdentityResultStatus.BLOCKED}
                for item in self.results
            )
            and self.overall_status == "passed"
        ):
            # A failing character can never be masked by an aggregate pass.
            raise ValueError("overall identity cannot pass when a character fails")
        if (
            self.all_passed
            and self.overall_status == "passed"
            and not self.results
        ):
            raise ValueError("overall identity cannot pass with no character evidence")
        if self.all_passed and self.overall_status != "passed":
            return self.model_copy(update={"overall_status": "passed"})
        if not self.results and self.overall_status == "passed":
            raise ValueError("overall identity cannot pass with no character evidence")
        return self
