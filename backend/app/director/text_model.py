"""Session-free text dispatch using the existing capability adapters."""

from typing import Protocol

from app.providers.capabilities import Capability
from app.providers.contracts.common import ExecutionContext, ProviderCreateResult
from app.providers.contracts.text import TextGenerateRequest
from app.providers.registry import ModelRegistry
from app.providers.router import CapabilityRouter


class TextModelPort(Protocol):
    async def generate(
        self, *, request: TextGenerateRequest, model_id: str, context: ExecutionContext,
    ) -> ProviderCreateResult: ...


class CapabilityTextModel:
    """Dispatch exactly the caller's resolved model; own no business transaction.

    The invocation service owns stable identity, persistence and retry decisions.
    Existing adapters retain protocol normalization, usage and error handling.
    """

    def __init__(self, registry: ModelRegistry) -> None:
        self._router = CapabilityRouter(registry=registry)

    async def generate(
        self, *, request: TextGenerateRequest, model_id: str, context: ExecutionContext,
    ) -> ProviderCreateResult:
        return await self._router.create(
            capability=Capability.TEXT_GENERATE, request=request,
            model_id=model_id, context=context,
        )
