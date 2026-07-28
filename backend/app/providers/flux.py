"""Flux image adapter edge.

When AGNES_ENABLED + AGNES_API_KEY are set, uses Agnes hub as BYOK transport.
Formal product path fails closed when not configured (no silent Fake).
FakeFluxAdapter is only for APP_ENV=test or explicit allow_fake=True.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.providers.agnes import AgnesImageAdapter
from app.providers.fake import FakeFluxAdapter
from app.providers.workspace_credentials import settings_for_workspace_provider
from app.shared.errors import AppError


class ProviderNotConfiguredError(AppError):
    """Raised when product path needs a live image Provider but none is configured."""

    def __init__(self, message: str = "provider_not_configured") -> None:
        super().__init__(
            code="PROVIDER_NOT_CONFIGURED",
            message=message,
            status_code=422,
        )


def get_flux_adapter(
    *,
    allow_live: bool = False,
    allow_fake: bool = False,
    settings: Settings | None = None,
) -> Any:
    """Return image adapter.

    - test env (unless allow_live): Fake for pytest contracts
    - agnes configured: live Agnes
    - otherwise: Fake only if allow_fake; else provider_not_configured
    """
    settings = settings or get_settings()
    if settings.app_env == "test" and not allow_live:
        return FakeFluxAdapter()
    if settings.agnes_configured():
        return AgnesImageAdapter(settings)
    if allow_fake or settings.app_env == "test":
        return FakeFluxAdapter()
    raise ProviderNotConfiguredError(
        "provider_not_configured: image Provider (Agnes/Flux) not configured. "
        "Set AGNES_ENABLED + AGNES_API_KEY, or use audited manual media upload."
    )


async def get_flux_adapter_for_workspace(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    allow_live: bool = False,
    allow_fake: bool = False,
) -> Any:
    """Resolve the project workspace credential before creating an image adapter."""
    # Keep the established Fake adapter injection point intact for unit/integration tests.
    if get_settings().app_env == "test":
        return get_flux_adapter(allow_fake=allow_fake)
    settings = await settings_for_workspace_provider(
        session,
        workspace_id=workspace_id,
        provider="agnes",
    )
    return get_flux_adapter(
        allow_live=allow_live,
        allow_fake=allow_fake,
        settings=settings,
    )


# Default export for import sites that expect a class-like factory
FluxAdapter = FakeFluxAdapter
