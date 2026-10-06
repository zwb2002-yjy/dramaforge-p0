"""Recovery resolves the historical handler, even when a newer one exists."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from app.providers.execution_identity import FrozenProviderConnection
from app.providers.handler_registry import ExactHandlerRegistry, RegisteredHandler
from app.providers.model_system_models import RuntimeHandlerRevision
from app.providers.runtime import ProviderRuntime


def test_exact_handler_registry_never_substitutes_the_latest_revision() -> None:
    family = uuid4()
    registry = ExactHandlerRegistry()

    def first(_: FrozenProviderConnection) -> ProviderRuntime:
        return cast(ProviderRuntime, object())

    def second(_: FrozenProviderConnection) -> ProviderRuntime:
        return cast(ProviderRuntime, object())

    registry.register(
        RegisteredHandler(
            family,
            1,
            "video",
            "a" * 64,
            first,
            protocol_profile="minimax_cn_v1",
            operation_kind="video.generate",
        )
    )
    registry.register(RegisteredHandler(family, 2, "video", "b" * 64, second))
    historical = RuntimeHandlerRevision(
        runtime_handler_id=family,
        handler_revision=1,
        handler_key="video",
        implementation_digest="a" * 64,
    )
    assert registry.resolve(historical) is first
    assert (
        registry.resolve_for_operation(
            historical,
            protocol_profile="minimax_cn_v1",
            operation_kind="video.generate",
        )
        is first
    )
    with pytest.raises(LookupError, match="does not support"):
        registry.resolve_for_operation(
            historical,
            protocol_profile="minimax_cn_v1",
            operation_kind="image.generate",
        )
    historical.handler_revision = 3
    with pytest.raises(LookupError, match="exact runtime handler"):
        registry.resolve(historical)
    historical.handler_revision = 1
    historical.implementation_digest = "c" * 64
    with pytest.raises(LookupError, match="exact runtime handler"):
        registry.resolve(historical)
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(RegisteredHandler(family, 2, "video", "b" * 64, second))
