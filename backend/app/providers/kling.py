"""Kling video adapter edge.

When AGNES_ENABLED + AGNES_API_KEY are set, uses Agnes hub as BYOK transport.
Otherwise falls back to a no-op shell (S4 real path still needs freeze Gate).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.providers.agnes import AgnesVideoAdapter
from app.providers.fake import FakeFluxAdapter
from app.providers.organization_credentials import settings_for_organization_provider


class FakeKlingAdapter:
    provider = "kling"

    async def create(self, request: dict[str, Any]) -> dict[str, Any]:
        # Reuse fake image bookkeeping shape for local-only video stubs
        fake = FakeFluxAdapter()
        result = await fake.create({**request, "kind": "video"})
        result["remote_task_id"] = str(result["remote_task_id"]).replace("flux", "kling")
        return result

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        return {"status": "succeeded", "progress": 1.0, "artifact_uri": f"fake://{remote_task_id}"}

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        _ = remote_task_id
        return {"status": "cancelled"}

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        _ = remote_task_id
        return {"amount": 0.0, "currency": "USD", "units": 0.0}


def get_kling_adapter(
    *,
    allow_live: bool = False,
    allow_fake: bool = False,
    settings: Settings | None = None,
) -> Any:
    """Video adapter. Formal path fails closed without Agnes; Fake only in test/allow_fake."""
    from app.providers.flux import ProviderNotConfiguredError

    settings = settings or get_settings()
    if settings.app_env == "test" and not allow_live:
        return FakeKlingAdapter()
    if settings.agnes_configured():
        return AgnesVideoAdapter(settings)
    if allow_fake or settings.app_env == "test":
        return FakeKlingAdapter()
    raise ProviderNotConfiguredError(
        "provider_not_configured: video Provider (Agnes/Kling) not configured. "
        "Set AGNES_ENABLED + AGNES_API_KEY, or use audited manual media upload."
    )


async def get_kling_adapter_for_organization(
    session: AsyncSession,
    *,
    organization_id: UUID,
    allow_live: bool = False,
    allow_fake: bool = False,
) -> Any:
    """Resolve the project organization credential before creating a video adapter."""
    if get_settings().app_env == "test":
        return get_kling_adapter(allow_fake=allow_fake)
    settings = await settings_for_organization_provider(
        session,
        organization_id=organization_id,
        provider="agnes",
    )
    return get_kling_adapter(
        allow_live=allow_live,
        allow_fake=allow_fake,
        settings=settings,
    )


KlingAdapter = FakeKlingAdapter
