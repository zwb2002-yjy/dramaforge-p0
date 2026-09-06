"""ShotDirectorIntentPatch compiler (CC7).

A structured shot-language pack compiles into a typed, frozen delta over a
``ShotDirectorIntent``.  It only supplies defaults where the intent has no
explicit value; it never builds an Execution Graph and never calls a Provider.
"""

from __future__ import annotations

from app.director.creative_capabilities.shot_language import (
    ShotDirectorIntentPatch,
    ShotLanguagePackSpec,
)


class ShotLanguageCompiler:
    """Compile a shot-language pack into a ShotDirectorIntentPatch."""

    def compile(self, *, pack: ShotLanguagePackSpec) -> ShotDirectorIntentPatch:
        return ShotDirectorIntentPatch(
            pack_key=pack.pack_key,
            pack_version=pack.pack_version,
            shot_size=pack.preferred_shot_sizes[0] if pack.preferred_shot_sizes else None,
            camera_angle=pack.camera_angles[0] if pack.camera_angles else None,
            lens_intent=pack.lens_intent or None,
            camera_motion=pack.camera_motion or None,
            composition=None,
            focus_strategy=None,
            coverage=list(pack.coverage_strategy.split(",")) if pack.coverage_strategy else [],
            reaction_rule=pack.reaction_strategy or None,
            cutting_rule=pack.cutting_rules[0] if pack.cutting_rules else None,
            continuity=list(pack.continuity_rules),
            provenance="shot-language-pack",
        )
