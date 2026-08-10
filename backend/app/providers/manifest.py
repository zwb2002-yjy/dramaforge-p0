"""Model capability manifest types (pure Pydantic, no ORM / Settings deps).

A :class:`ModelCapabilityManifest` is the versioned capability contract for one
concrete model (``provider_type + protocol_profile + model_id + model_revision``).
It is the "model ability layer" of the three-layer split: creative intent ->
model capability -> wire compilation. Manifests are immutable; a model contract
change adds a new revision row instead of mutating an existing one.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

ManifestVersion = str
MediaKind = Literal["image", "video", "text", "voice"]
Lifecycle = Literal["preview", "active", "deprecated", "retired"]
CatalogSource = Literal["official_static", "account_discovery", "admin_approved"]
OperationKind = Literal["image.generate", "video.generate"]


class OptionSpec(BaseModel):
    """One validated native option in a model's option schema."""

    type: Literal["enum", "boolean", "integer", "number", "string"]
    values: list[JsonValue] | None = None
    default: JsonValue | None = None
    minimum: float | None = None
    maximum: float | None = None


class ModelOptionSchema(BaseModel):
    """Namespaced whitelist of native advanced options a compiler accepts."""

    namespace: str
    options: dict[str, OptionSpec] = Field(default_factory=dict)


class ReferenceConstraint(BaseModel):
    """Per-role artifact reference cardinality. Absent roles are forbidden."""

    min: int = 0
    max: int = 0


class ExclusiveGroup(BaseModel):
    """Mutually exclusive reference-role groups, e.g. frame endpoints vs
    multimodal references. ``members`` is a list of role-name lists; at most one
    member list may be non-empty in a single request."""

    name: str
    members: list[list[str]]


class OperationManifest(BaseModel):
    """Capability contract for one operation (image.generate / video.generate)."""

    operation: OperationKind
    capabilities: list[str]
    output_constraints: dict[str, JsonValue] = Field(default_factory=dict)
    reference_constraints: dict[str, ReferenceConstraint] = Field(default_factory=dict)
    exclusive_groups: list[ExclusiveGroup] = Field(default_factory=list)

    def reference_role_capability(self, role: str) -> str | None:
        """Map an artifact reference role to its capability name, if any."""
        return {
            "first_frame": "video.i2v.first_frame",
            "last_frame": "video.i2v.last_frame",
            "reference_image": "video.reference.image",
            "reference_video": "video.reference.video",
            "reference_audio": "video.reference.audio",
        }.get(role)


class ModelCapabilityManifest(BaseModel):
    """Versioned capability manifest for one concrete model."""

    manifest_version: str
    provider_type: str
    protocol_profile: str
    model_id: str
    model_revision: str
    media_kind: MediaKind
    display_name: str
    lifecycle: Lifecycle = "active"
    catalog_source: CatalogSource = "official_static"
    documented_at: date
    operations: dict[OperationKind, OperationManifest]
    option_schema: ModelOptionSchema = Field(
        default_factory=lambda: ModelOptionSchema(namespace="")
    )
