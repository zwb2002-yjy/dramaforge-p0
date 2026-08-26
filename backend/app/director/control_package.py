"""P8-04 DirectorControlPackage (03 §75).

Stable semantic controls the director board produces and hands to the
WorkbenchExecutionPlan: composition, camera, pose, gaze, blocking. Each control
is classified exact / approximate / unsupported against the model manifest.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.production.execution_plan import CapabilityGap, ControlTranslation
from app.providers.capabilities import Capability
from app.providers.manifest import ModelManifest


class CameraControl(BaseModel):
    model_config = ConfigDict(frozen=True)

    shot_size: Literal["close", "medium", "wide"] = "medium"
    angle: Literal["high", "low", "eye"] = "eye"
    movement: Literal["static", "dolly", "pan", "tilt", "track"] = "static"
    focal_length_mm: float | None = None
    camera_height_m: float | None = None
    pitch_deg: float | None = None
    yaw_deg: float | None = None
    distance_m: float | None = None


class PoseControl(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: str = "standing"
    expression_type: str = "neutral"
    expression_intensity: float = Field(default=0.0, ge=0.0, le=1.0)


class GazeControl(BaseModel):
    model_config = ConfigDict(frozen=True)

    target: str | None = None
    head_direction: str | None = None
    eye_state: str = "open"
    mouth_state: str = "closed"


class Blocking2D(BaseModel):
    model_config = ConfigDict(frozen=True)

    elements: list[dict[str, object]] = Field(default_factory=list)
    composition_bounds: dict[str, float] = Field(default_factory=dict)


class DirectorControlPackage(BaseModel):
    """Stable semantic output of the director board (03 §75)."""

    model_config = ConfigDict(extra="forbid")

    composition: dict[str, object] = Field(default_factory=dict)
    camera: CameraControl = Field(default_factory=CameraControl)
    pose: PoseControl = Field(default_factory=PoseControl)
    gaze: GazeControl = Field(default_factory=GazeControl)
    blocking: Blocking2D = Field(default_factory=Blocking2D)

    def to_plan_controls(
        self,
        *,
        manifest: ModelManifest,
        capability: Capability,
    ) -> tuple[list[ControlTranslation], list[CapabilityGap]]:
        """Translate the package into plan controls classified against the
        manifest: exact / approximate / unsupported (03 §75)."""
        spec = manifest.capability_specs.get(capability)
        declared = set((spec.mode_spec(None).common_options).keys()) if spec is not None else set()
        translations: list[ControlTranslation] = []
        gaps: list[CapabilityGap] = []

        camera_controls = {
            "camera_shot_size": self.camera.shot_size,
            "camera_angle": self.camera.angle,
            "camera_movement": self.camera.movement,
        }
        for control, value in camera_controls.items():
            if control in declared:
                translations.append(
                    ControlTranslation(
                        control=control, option=control, from_value=None,
                        to_value=value, status="exact",
                        reason="declared by model manifest",
                    )
                )
            else:
                gaps.append(
                    CapabilityGap(
                        capability=capability, controls=[control],
                        severity="warning",
                        reason=(
                            f"model does not declare {control}; delivered "
                            "approximately or unsupported"
                        ),
                    )
                )
        # Blocking / gaze are semantic intents, usually unsupported by the model
        # manifest directly -> surface as approximate/unsupported controls.
        for control in ("blocking", "gaze"):
            if control not in declared:
                translations.append(
                    ControlTranslation(
                        control=control, option=control, from_value=None,
                        to_value={"enabled": True}, status="approximate",
                        reason="semantic intent approximated through the prompt",
                    )
                )
        return translations, gaps
