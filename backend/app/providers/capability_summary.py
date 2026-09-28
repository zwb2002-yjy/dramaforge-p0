"""Small product-facing summary derived from one immutable provider manifest."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.providers.manifest import ModelCapabilityManifest
from app.providers.workbench_contract import select_workbench_contract

VIDEO_ROLES = (
    "first_frame",
    "last_frame",
    "reference_image",
    "reference_video",
    "reference_audio",
)
IMAGE_ROLES = ("reference_image",)


class ModelCapabilitySummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    media_kind: str
    accepts_text_only: bool
    product_text_only: bool
    accepts: dict[str, bool] = Field(default_factory=dict)
    product_open: dict[str, bool] = Field(default_factory=dict)
    limits: dict[str, int] = Field(default_factory=dict)


def summarize_model_capability(manifest: ModelCapabilityManifest) -> ModelCapabilitySummary:
    """Report Provider truth and the current Workbench subset separately."""
    if manifest.media_kind not in {"image", "video"}:
        return ModelCapabilitySummary(
            media_kind=manifest.media_kind, accepts_text_only=False, product_text_only=False
        )
    operation = (
        manifest.operations.get("video.generate")
        if manifest.media_kind == "video"
        else manifest.operations.get("image.generate")
    )
    if operation is None:
        return ModelCapabilitySummary(
            media_kind=manifest.media_kind, accepts_text_only=False, product_text_only=False
        )
    roles = VIDEO_ROLES if manifest.media_kind == "video" else IMAGE_ROLES
    accepts = {role: False for role in roles}
    limits: dict[str, int] = {}
    if operation.input_contracts:
        accepts_text_only = any(
            contract.minimum_total_references == 0
            and all(
                not slot.required and slot.minimum == 0
                for slot in contract.input_slots.values()
            )
            for contract in operation.input_contracts.values()
        )
        for contract in operation.input_contracts.values():
            for role, slot in contract.input_slots.items():
                if role in accepts and (slot.maximum is None or slot.maximum > 0):
                    accepts[role] = True
                    if slot.maximum is not None:
                        limits[role] = max(limits.get(role, 0), slot.maximum)
    else:
        declared = set(operation.capabilities)
        accepts_text_only = "video.t2v" in declared or "image.t2i" in declared
        for role, constraint in operation.reference_constraints.items():
            if role in accepts and constraint.max > 0:
                accepts[role] = True
                limits[role] = constraint.max
    product_open = {role: False for role in roles}
    if manifest.lifecycle != "active" or manifest.implementation_status != "contract_tested":
        return ModelCapabilitySummary(
            media_kind=manifest.media_kind,
            accepts_text_only=accepts_text_only,
            product_text_only=False,
            accepts=accepts,
            product_open=product_open,
            limits=limits,
        )
    if manifest.media_kind == "video":
        if operation.input_contracts:
            try:
                select_workbench_contract(
                    operation=operation,
                    media_kind="video",
                    references=[("first_frame", None)],
                )
            except ValueError:
                pass
            else:
                product_open["first_frame"] = True
        else:
            product_open["first_frame"] = accepts["first_frame"]
        product_text_only = False  # Formal Keyframe is mandatory in this product path.
    elif manifest.media_kind == "image":
        if operation.input_contracts:
            try:
                select_workbench_contract(
                    operation=operation, media_kind="image", references=[]
                )
            except ValueError:
                product_text_only = False
            else:
                product_text_only = True
            try:
                select_workbench_contract(
                    operation=operation,
                    media_kind="image",
                    references=[("reference_image", None)],
                )
            except ValueError:
                pass
            else:
                product_open["reference_image"] = True
        else:
            product_open["reference_image"] = accepts["reference_image"]
            product_text_only = accepts_text_only
    return ModelCapabilitySummary(
        media_kind=manifest.media_kind,
        accepts_text_only=accepts_text_only,
        product_text_only=product_text_only,
        accepts=accepts,
        product_open=product_open,
        limits=limits,
    )
