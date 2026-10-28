"""P4-01 Workbench execution plan contracts (07 §16 / 03 §31).

Pure Pydantic — no I/O, no ORM, no services.  The plan is the frozen semantic
contract between the workbench, the reference compiler (P4-02) and the
WorkbenchExecutionService (P4-05).

The name ``PlannedReference`` deliberately replaces the planning-era
``ResolvedReference`` so it cannot collide with
``app.providers.runtime.ResolvedReference`` (which carries runtime
bytes/URLs for delivery).

The plan reuses existing typed contracts:

- ``ExecutionModelResolution`` (MS1-C) as the resolved model identity,
- ``TranslationReport`` (V3 §29) as the auditable translation result,
- ``Capability`` as the stable business capability.

The plan never carries secrets or provider wire payloads.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.providers.capabilities import Capability
from app.providers.intents import (
    IMAGE_INTENT_OPTION_FIELDS,
    VIDEO_INTENT_OPTION_FIELDS,
    ArtifactReferenceIntent,
    ImageGenerationIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
    VideoOutputIntent,
)
from app.providers.model_resolution import ExecutionModelResolution
from app.providers.translation import TranslationReport
from app.providers.workbench_contract import workbench_ui_mode
from app.shared.errors import ValidationAppError

PlanDelivery = Literal["exact", "approximate", "unsupported"]
PlanStage = Literal["image_keyframe", "video"]

_FINGERPRINT_PATTERN = r"^[0-9a-fA-F]{64}$"


def fingerprint_plan(payload: Mapping[str, Any]) -> str:
    """Deterministic sha256 of the canonical JSON payload.

    ``sort_keys=True`` + compact separators make the fingerprint stable across
    dict insertion orders so the execution API can re-validate a submitted plan
    against a re-computed plan (P4-07).
    """
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PlannedReference(BaseModel):
    """One shot reference planned for a model execution.

    Distinct from ``app.providers.runtime.ResolvedReference`` (runtime
    byte/URL delivery).  A plan reference carries business purpose, artifact
    identity and the delivery classification only.  ``role`` is the
    ModelManifest input slot assigned by the reference compiler (P4-02).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_id: UUID | None = None
    purpose: str = Field(min_length=1, max_length=80)
    role: str | None = Field(default=None, max_length=80)
    asset_version_id: UUID | None = None
    artifact_id: UUID | None = None
    resolution_mode: str = Field(default="current_formal", max_length=24)
    mime_type: str = Field(default="image/png", max_length=120)
    fingerprint: str | None = Field(default=None, max_length=128)
    delivery: PlanDelivery = "exact"
    reason: str | None = Field(default=None, max_length=240)


class ControlTranslation(BaseModel):
    """One semantic control → ModelManifest option translation.

    ``status`` classifies the delivery as ``exact``, ``approximate`` or
    ``unsupported``.  Unsupported controls must never be silently dropped:
    they surface here and in ``CapabilityGap``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    control: str = Field(min_length=1, max_length=80)
    option: str = Field(min_length=1, max_length=80)
    from_value: JsonValue | None = None
    to_value: JsonValue | None = None
    status: PlanDelivery
    reason: str = Field(min_length=1, max_length=240)


class CapabilityGap(BaseModel):
    """A capability/control the chosen model cannot honor.

    ``severity="fatal"`` means execution must fail closed; ``"warning"`` means
    the plan may proceed only with an explicit user acceptance of the
    approximation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: Capability
    controls: list[str] = Field(default_factory=list)
    severity: Literal["fatal", "warning"]
    reason: str = Field(min_length=1, max_length=240)


class PendingSuggestion(BaseModel):
    """A value that exists in the creative profile but is not in this plan.

    The project records template recommendations; execution only consumes the
    compiled creative snapshot. Reporting the difference keeps a recommendation
    from being read as an applied Provider control.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    source: Literal["template_recommendation"] = "template_recommendation"
    reason: str = Field(min_length=1, max_length=240)


class WorkbenchExecutionPlan(BaseModel):
    """Semantic execution plan for one shot execution (P4-01).

    Carries the resolved model identity (``ExecutionModelResolution``),
    ``mode_id``, connection/credential revision identity, the planned
    references, control translations and the translation report.

    ``plan_fingerprint`` is empty until :meth:`freeze` computes it from the
    canonical JSON payload; the execution API (P4-07) re-validates the frozen
    fingerprint before dispatching.
    """

    model_config = ConfigDict(extra="forbid")

    plan_fingerprint: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=_FINGERPRINT_PATTERN,
    )
    project_id: UUID
    shot_id: UUID
    experiment_branch_id: UUID | None = None
    stage: PlanStage
    prompt: str = Field(min_length=1)
    semantic_intent: dict[str, JsonValue] = Field(default_factory=dict)
    mode_id: str = Field(min_length=1, max_length=120)
    ui_mode_id: str | None = None
    input_contract_id: str | None = None
    resolved_model: ExecutionModelResolution
    capability: Capability
    planned_references: list[PlannedReference] = Field(default_factory=list)
    exact_controls: list[ControlTranslation] = Field(default_factory=list)
    approximate_controls: list[ControlTranslation] = Field(default_factory=list)
    unsupported_controls: list[ControlTranslation] = Field(default_factory=list)
    capability_gaps: list[CapabilityGap] = Field(default_factory=list)
    # Creative-profile values that are NOT in this execution. Shown as
    # suggestions, never as Provider hard parameters.
    pending_suggestions: list[PendingSuggestion] = Field(default_factory=list)
    semantic_request_preview: dict[str, JsonValue] = Field(default_factory=dict)
    connection_revision_id: UUID | None = None
    credential_revision_id: UUID | None = None
    translation_report: TranslationReport | None = None
    accepted_approximations: list[str] = Field(default_factory=list)
    expected_shot_version: int | None = None
    duration_seconds: float | None = None
    prompt_override: str | None = None
    effective_options: dict[str, JsonValue] = Field(default_factory=dict)
    option_sources: dict[str, str] = Field(default_factory=dict)
    requested_options: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    supports_prompt_override: bool = False

    def freeze(self) -> WorkbenchExecutionPlan:
        """Return a copy with a deterministic ``plan_fingerprint``.

        Idempotent: if the fingerprint is already set it is preserved.
        """
        if self.plan_fingerprint is not None:
            return self
        payload = self.model_dump(mode="json", exclude={"plan_fingerprint"})
        return self.model_copy(update={"plan_fingerprint": fingerprint_plan(payload)})

    @property
    def reference_counts(self) -> dict[str, int]:
        """Exact/approximate/unsupported reference counts for preview UIs."""
        counts: dict[str, int] = {"exact": 0, "approximate": 0, "unsupported": 0}
        for reference in self.planned_references:
            counts[reference.delivery] = counts.get(reference.delivery, 0) + 1
        return counts


def generation_intent_from_plan(
    plan: WorkbenchExecutionPlan, *, fallback_aspect_ratio: str
) -> ImageGenerationIntent | VideoGenerationIntentV1:
    """The only conversion of frozen Workbench choices to compiler input.

    The fallback is for historical snapshots lacking a frozen ratio; callers
    pass their saved snapshot value. New plans always freeze aspect_ratio.
    No model/profile/credential is resolved here, and no unknown mode defaults.
    """
    import math

    options = plan.effective_options
    allowed = VIDEO_INTENT_OPTION_FIELDS if plan.stage == "video" else IMAGE_INTENT_OPTION_FIELDS
    unsupported = sorted(set(options) - allowed)
    if unsupported:
        raise ValidationAppError(
            "Frozen options have no implemented compiler intent fields",
            details={"code": "MODEL_OPTION_NOT_IMPLEMENTED", "options": unsupported},
        )
    try:
        mode = plan.ui_mode_id or workbench_ui_mode(
            media_kind="video" if plan.stage == "video" else "image",
            mode_id=plan.mode_id,
        )
        selection = ModelSelectionIntent(
            mode="explicit_binding",
            model_binding_id=plan.resolved_model.provider_model_binding_id,
        )
        references = [
            reference
            for reference in plan.planned_references
            if reference.delivery != "unsupported"
        ]
        ratio = options.get("aspect_ratio", fallback_aspect_ratio)
        if plan.stage == "image_keyframe":
            return ImageGenerationIntent.model_validate(
                {
                    "prompt": plan.prompt,
                    "selection": selection,
                    "mode_id": mode,
                    **options,
                    "aspect_ratio": ratio,
                    "reference_artifact_ids": [ref.artifact_id for ref in references],
                    "reference_fingerprint": references[0].fingerprint if references else None,
                    "reference_mime": references[0].mime_type if references else None,
                },
                strict=True,
            )
        duration = plan.duration_seconds
        if (
            duration is None
            or not math.isfinite(duration)
            or duration <= 0
            or not duration.is_integer()
        ):
            raise ValueError("video duration must be frozen whole seconds")
        if options.get("duration_seconds", duration) != duration:
            raise ValueError("frozen duration conflicts with effective options")
        return VideoGenerationIntentV1(
            prompt=plan.prompt,
            selection=selection,
            mode_id=mode,
            references=[
                ArtifactReferenceIntent.model_validate(
                    {
                        "artifact_id": ref.artifact_id,
                        "role": ref.role,
                    }
                )
                for ref in references
            ],
            output=VideoOutputIntent.model_validate(
                {
                    **options,
                    "aspect_ratio": ratio,
                    "duration_seconds": int(duration),
                },
                strict=True,
            ),
        )
    except ValueError as exc:
        raise ValidationAppError(
            "Frozen execution plan cannot be compiled",
            details={"code": "EXECUTION_PLAN_INVALID"},
        ) from exc
