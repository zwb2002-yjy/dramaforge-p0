"""DirectorAutonomy behavior policy (V1 G3).

The policy only controls Director activity and UI density.  Runtime, model
resolution, ProductionGraph, Artifact, and EditingAdapter never read this
module.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

DirectorAutonomy = Literal["AUTO", "ASSIST", "MANUAL"]


class DirectorAutonomyPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: DirectorAutonomy
    active_analysis: bool
    show_recommendations: bool
    auto_generate_proposals: bool
    advanced_default_visible: bool
    paid_media_requires_authorization: bool


def policy_for(mode: DirectorAutonomy) -> DirectorAutonomyPolicy:
    if mode == "AUTO":
        return DirectorAutonomyPolicy(
            mode="AUTO",
            active_analysis=True,
            show_recommendations=True,
            auto_generate_proposals=True,
            advanced_default_visible=False,
            paid_media_requires_authorization=True,
        )
    if mode == "ASSIST":
        return DirectorAutonomyPolicy(
            mode="ASSIST",
            active_analysis=True,
            show_recommendations=True,
            auto_generate_proposals=True,
            advanced_default_visible=False,
            paid_media_requires_authorization=True,
        )
    return DirectorAutonomyPolicy(
        mode="MANUAL",
        active_analysis=False,
        show_recommendations=False,
        auto_generate_proposals=False,
        advanced_default_visible=True,
        paid_media_requires_authorization=True,
    )


__all__ = ["DirectorAutonomy", "DirectorAutonomyPolicy", "policy_for"]
