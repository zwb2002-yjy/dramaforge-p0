"""V3 ModelAdapter protocol (spec §26) and translate/submit split (spec §26.1).

An Adapter is the single place where a model's provider-specific differences
stop. Business code calls the Adapter through :class:`CapabilityRouter` with a
capability + semantic request + context; the Adapter owns:
- capability/spec validation (via the manifest),
- pure ``translate()`` (semantic request → native request),
- ``create``/``poll``/``cancel``/``fetch_cost`` I/O against the provider.

``translate()`` is kept pure (no I/O) so translation can be unit-tested without
a real provider. ``submit()``-style I/O is the create path.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.providers.capabilities import Capability
from app.providers.contracts.common import (
    ExecutionContext,
    ProviderCancelResult,
    ProviderCostResult,
    ProviderCreateResult,
    ProviderPollResult,
    ResolvedArtifact,
)
from app.providers.manifest import ModelManifest
from app.providers.translation import TranslationResult


class ModelAdapter(Protocol):
    """Uniform adapter surface. ``request`` is one of the typed capability
    contracts (or a validated dict at the legacy bridge); the concrete Adapter
    narrows it to the type its manifest declares."""

    provider_id: str
    model_id: str

    @property
    def manifest(self) -> ModelManifest: ...

    async def translate(
        self,
        capability: Capability,
        request: Any,
        resolved_artifacts: dict[str, ResolvedArtifact],
    ) -> TranslationResult: ...

    async def create(
        self,
        capability: Capability,
        request: Any,
        context: ExecutionContext,
    ) -> ProviderCreateResult: ...

    async def poll(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderPollResult: ...

    async def cancel(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderCancelResult: ...

    async def fetch_cost(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderCostResult: ...
