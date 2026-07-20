"""Provider adapter protocol shell (full contract lands with S2 adapters)."""

from __future__ import annotations

from typing import Any, Protocol


class ProviderAdapter(Protocol):
    provider: str

    async def create(self, request: dict[str, Any]) -> dict[str, Any]: ...

    async def poll(self, remote_task_id: str) -> dict[str, Any]: ...

    async def cancel(self, remote_task_id: str) -> dict[str, Any]: ...

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]: ...
