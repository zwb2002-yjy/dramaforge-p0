"""CapabilityRouter (spec §33).

The single business-facing gateway for model execution: resolve → select →
validate → dispatch. Business code depends on :class:`Capability` + a semantic
request + :class:`ExecutionContext`; it never branches on a provider name or
model family. The router owns no provider mapping — provider differences stop
at the Adapter. P0 does no fallback (spec §37): a failed dispatch is surfaced,
never silently re-routed to another model.
"""

from __future__ import annotations

from typing import Any

from app.providers.adapter import ModelAdapter
from app.providers.capabilities import Capability
from app.providers.contracts.common import (
    ExecutionContext,
    ProviderCancelResult,
    ProviderCreateResult,
    ProviderPollResult,
)
from app.providers.errors import UnsupportedCapabilityError
from app.providers.registry import ModelRegistry
from app.providers.selector import DefaultModelSelector
from app.providers.validator import CapabilityValidator


class CapabilityRouter:
    def __init__(
        self,
        *,
        registry: ModelRegistry,
        selector: DefaultModelSelector | None = None,
        validator: CapabilityValidator | None = None,
    ) -> None:
        self.registry = registry
        self.selector = selector or DefaultModelSelector()
        self.validator = validator or CapabilityValidator()

    def _resolve(self, *, capability: Capability, model_id: str | None) -> ModelAdapter:
        model = self.selector.select(
            capability=capability,
            requested_model=model_id,
            registry=self.registry,
        )
        spec = model.manifest.capability_specs.get(capability)
        if spec is None:
            raise UnsupportedCapabilityError(capability)
        return model.adapter

    async def create(
        self,
        *,
        capability: Capability,
        request: Any,
        context: ExecutionContext,
        model_id: str | None = None,
        policy: object | None = None,
    ) -> ProviderCreateResult:
        model = self.selector.select(
            capability=capability,
            requested_model=model_id,
            registry=self.registry,
            policy=policy,
        )
        spec = model.manifest.capability_specs.get(capability)
        if spec is None:
            raise UnsupportedCapabilityError(capability)
        self.validator.validate(request, spec)
        return await model.adapter.create(capability, request, context)

    async def poll(
        self,
        *,
        capability: Capability,
        remote_task_id: str,
        context: ExecutionContext,
        model_id: str | None = None,
    ) -> ProviderPollResult:
        adapter = self._resolve(capability=capability, model_id=model_id)
        return await adapter.poll(remote_task_id, context)

    async def cancel(
        self,
        *,
        capability: Capability,
        remote_task_id: str,
        context: ExecutionContext,
        model_id: str | None = None,
    ) -> ProviderCancelResult:
        adapter = self._resolve(capability=capability, model_id=model_id)
        return await adapter.cancel(remote_task_id, context)
