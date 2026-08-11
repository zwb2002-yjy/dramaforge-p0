"""Full-fidelity translation results (V3 spec §28–§29).

An Adapter translates a semantic request into a provider-native request. The
translation is observable and auditable through :class:`TranslationReport` and
:class:`EffectiveRequest`. P0 is strict mode: an unsupported option is an error,
never a silent drop. Best-effort mode (with warnings + report) is a P1 extension.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.providers.capabilities import Capability


class RequestTransformation(BaseModel):
    """One observable field change during translation (spec §29)."""

    field: str
    from_value: Any | None = None
    to_value: Any | None = None
    reason: str


class TranslationReport(BaseModel):
    """Auditable record of what the user requested vs what the model received
    (spec §29). Never contains secrets (spec §2.8)."""

    requested_options: dict[str, Any] = Field(default_factory=dict)
    effective_options: dict[str, Any] = Field(default_factory=dict)
    transformations: list[RequestTransformation] = Field(default_factory=list)
    dropped_options: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EffectiveRequest(BaseModel):
    """The semantic request after capability/constraint processing (spec §28).
    Still not a provider raw payload — that belongs to the wire layer."""

    capability: Capability
    model_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    common_options: dict[str, Any] = Field(default_factory=dict)
    native_options: dict[str, Any] = Field(default_factory=dict)


class TranslationResult(BaseModel):
    """Output of ``ModelAdapter.translate()`` (spec §26.1): the effective
    semantic request, the provider-native wire body, and the audit report."""

    capability: Capability
    effective_request: EffectiveRequest
    native_request: dict[str, Any] = Field(default_factory=dict)
    translation_report: TranslationReport = Field(default_factory=TranslationReport)
