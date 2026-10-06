"""Exact historical runtime handler selection without a latest-version fallback."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.providers.execution_identity import FrozenProviderConnection
from app.providers.model_system_models import RuntimeHandlerRevision
from app.providers.runtime import ProviderRuntime

HandlerFactory = Callable[[FrozenProviderConnection], ProviderRuntime]


@dataclass(frozen=True)
class RegisteredHandler:
    runtime_handler_id: UUID
    handler_revision: int
    handler_key: str
    implementation_digest: str
    factory: HandlerFactory
    protocol_profile: str | None = None
    operation_kind: str | None = None


class ExactHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[tuple[UUID, int], RegisteredHandler] = {}

    def register(self, handler: RegisteredHandler) -> None:
        key = (handler.runtime_handler_id, handler.handler_revision)
        if handler.handler_revision <= 0 or key in self._handlers:
            raise ValueError("invalid or duplicate runtime handler revision")
        self._handlers[key] = handler

    def resolve(self, revision: RuntimeHandlerRevision) -> HandlerFactory:
        """Return only the exact deployed implementation named by frozen history."""
        handler = self._handlers.get((revision.runtime_handler_id, revision.handler_revision))
        if (
            handler is None
            or handler.handler_key != revision.handler_key
            or handler.implementation_digest != revision.implementation_digest
        ):
            raise LookupError("exact runtime handler revision is unavailable")
        return handler.factory

    def resolve_for_operation(
        self,
        revision: RuntimeHandlerRevision,
        *,
        protocol_profile: str,
        operation_kind: str,
    ) -> HandlerFactory:
        """Require the exact implementation to declare this wire operation."""
        factory = self.resolve(revision)
        handler = self._handlers[(revision.runtime_handler_id, revision.handler_revision)]
        if handler.protocol_profile != protocol_profile or handler.operation_kind != operation_kind:
            raise LookupError("exact runtime handler does not support the frozen operation")
        return factory
