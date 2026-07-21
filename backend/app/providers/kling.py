"""Kling video adapter edge.

When AGNES_ENABLED + AGNES_API_KEY are set, uses Agnes hub as BYOK transport.
Otherwise falls back to a no-op shell (S4 real path still needs freeze Gate).
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.providers.agnes import AgnesVideoAdapter
from app.providers.fake import FakeFluxAdapter


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


def get_kling_adapter(*, allow_live: bool = False) -> Any:
    settings = get_settings()
    if settings.app_env == "test" and not allow_live:
        from app.providers.fake import FakeFluxAdapter

        return FakeFluxAdapter()
    if settings.agnes_configured():
        return AgnesVideoAdapter(settings)
    return FakeKlingAdapter()


KlingAdapter = FakeKlingAdapter
