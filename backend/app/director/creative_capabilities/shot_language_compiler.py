"""ShotDirectorIntentPatch compiler (CC7).

A structured shot-language pack compiles into a typed, frozen delta over a
``ShotDirectorIntent``.  It only supplies defaults where the intent has no
explicit value; it never builds an Execution Graph and never calls a Provider.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.director.creative_capabilities.shot_language import (
    ShotDirectorIntentPatch,
    ShotLanguagePackSpec,
)


class ShotLanguageCompiler:
    """Compile a shot-language pack into a ShotDirectorIntentPatch."""

    @staticmethod
    def _explicit(
        values: Mapping[str, object],
        *paths: str,
    ) -> bool:
        for path in paths:
            current: object = values
            found = True
            for part in path.split("."):
                if not isinstance(current, Mapping) or part not in current:
                    found = False
                    break
                current = current[part]
            if not found or current is None:
                continue
            if isinstance(current, (str, list, tuple, set, Mapping)) and len(current) == 0:
                continue
            return True
        return False

    def compile(
        self,
        *,
        pack: ShotLanguagePackSpec,
        explicit_values: Mapping[str, object] | None = None,
    ) -> ShotDirectorIntentPatch:
        explicit = explicit_values or {}
        return ShotDirectorIntentPatch(
            pack_key=pack.pack_key,
            pack_version=pack.pack_version,
            shot_size=(
                pack.preferred_shot_sizes[0]
                if pack.preferred_shot_sizes
                and not self._explicit(explicit, "shot_size", "framing.shot_size")
                else None
            ),
            camera_angle=(
                pack.camera_angles[0]
                if pack.camera_angles
                and not self._explicit(explicit, "camera_angle", "framing.angle")
                else None
            ),
            lens_intent=(
                pack.lens_intent or None
                if not self._explicit(
                    explicit,
                    "lens_intent",
                    "camera.lens_intent",
                    "camera.focal_length_mm",
                )
                else None
            ),
            camera_motion=(
                pack.camera_motion or None
                if not self._explicit(explicit, "camera_motion", "camera.movement")
                else None
            ),
            composition=None,
            focus_strategy=None,
            coverage=(
                list(pack.coverage_strategy.split(","))
                if pack.coverage_strategy and not self._explicit(explicit, "coverage")
                else []
            ),
            reaction_rule=(
                pack.reaction_strategy or None
                if not self._explicit(explicit, "reaction_rule")
                else None
            ),
            cutting_rule=(
                pack.cutting_rules[0]
                if pack.cutting_rules and not self._explicit(explicit, "cutting_rule")
                else None
            ),
            continuity=(
                list(pack.continuity_rules)
                if not self._explicit(explicit, "continuity", "continuity_constraints")
                else []
            ),
            provenance="shot-language-pack",
        )
