"""VisualBible patch compiler (CC6).

A structured style pack compiles into a *patch* over existing project values.
The priority gate is respected: ``explicit project values > style default``.
A style pack never replaces an explicit project value and never binds a Provider.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.director.creative_capabilities.packs import StylePackSpec, VisualBiblePatch


def _value_at_path(data: Mapping[str, object], path: str) -> object | None:
    """Return the value at a dotted path (``"palette.accent"``) or None."""
    node: object = data
    for part in path.split("."):
        if isinstance(node, Mapping):
            node = node.get(part)
        else:
            return None
    return node


class VisualBibleCompiler:
    """Compile a StylePack into a patch, respecting explicit project values.

    A patch only supplies a default: if the project already has an explicit value
    for a field, the style default is NOT applied (CC9 priority
    ``explicit > accepted proposal > project override > pack default``).
    """

    def compile(
        self,
        *,
        style: StylePackSpec,
        project_values: Mapping[str, object] | None = None,
    ) -> VisualBiblePatch:
        project = dict(project_values or {})
        patches: dict[str, object] = {}

        for field in (
            "lighting",
            "contrast",
            "texture",
            "lens_language",
            "composition",
            "camera_behavior",
            "motion_feel",
            "production_design",
            "post_processing",
        ):
            value = getattr(style, field)
            if value is None:
                continue
            # Only patch a field the project does not already explicitly set.
            if _value_at_path(project, field) is None:
                patches[field] = value.value if hasattr(value, "value") else value

        # Palette: patch per-role only where the project has no explicit role.
        palette: dict[str, str] = {}
        for role, color in style.palette.items():
            if _value_at_path(project, f"palette.{role}") is None:
                palette[role] = color
        if palette:
            patches["palette"] = palette

        return VisualBiblePatch(
            style_key=style.style_key,
            style_version=style.style_version,
            patches=patches,
            suggestions=list(style.reference_guidance),
            provenance="style-pack",
        )
