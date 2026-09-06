"""Production Model Profiles — the "model role configuration layer" above V3.

A profile answers *which model each production stage uses*; the CapabilityRouter
still answers *how to execute a capability*. See
:mod:`app.providers.model_profiles.slots` (ModelSlot) and
:mod:`app.providers.model_profiles.service` (ProductionModelProfileService).
"""

from app.providers.model_profiles.models import (
    ModelBackendBinding,
    ModelProfileSnapshot,
    ModelSlotBinding,
    ResolvedModelBinding,
)
from app.providers.model_profiles.resolver import ModelBindingResolver
from app.providers.model_profiles.service import ProductionModelProfileService
from app.providers.model_profiles.slots import (
    MODEL_SLOT_DEFINITIONS,
    ModelSlot,
    ModelSlotDefinition,
)

__all__ = [
    "ModelBackendBinding",
    "ModelProfileSnapshot",
    "ModelSlot",
    "ModelSlotBinding",
    "ModelSlotDefinition",
    "ResolvedModelBinding",
    "MODEL_SLOT_DEFINITIONS",
    "ModelBindingResolver",
    "ProductionModelProfileService",
]
