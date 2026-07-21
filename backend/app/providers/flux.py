"""Flux image adapter edge.

When AGNES_ENABLED + AGNES_API_KEY are set, uses Agnes hub as BYOK transport.
Otherwise falls back to FakeFluxAdapter for local tests.
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.providers.agnes import AgnesImageAdapter
from app.providers.fake import FakeFluxAdapter


def get_flux_adapter(*, allow_live: bool = False) -> Any:
    """Return image adapter. Live Agnes only outside test env (or allow_live=True)."""
    settings = get_settings()
    if settings.app_env == "test" and not allow_live:
        return FakeFluxAdapter()
    if settings.agnes_configured():
        return AgnesImageAdapter(settings)
    return FakeFluxAdapter()


# Default export for import sites that expect a class-like factory
FluxAdapter = FakeFluxAdapter
