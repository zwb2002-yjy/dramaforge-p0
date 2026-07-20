"""Provider adapter protocol and shared result shapes."""

from __future__ import annotations

from typing import Any, Protocol, TypedDict


class ProviderCreateResult(TypedDict, total=False):
    remote_task_id: str
    status: str


class ProviderPollResult(TypedDict, total=False):
    status: str
    progress: float
    artifact_uri: str
    error: str


class ProviderCancelResult(TypedDict, total=False):
    status: str


class ProviderCostResult(TypedDict, total=False):
    amount: float
    currency: str
    units: float


class ProviderAdapter(Protocol):
    provider: str

    async def create(self, request: dict[str, Any]) -> dict[str, Any]: ...

    async def poll(self, remote_task_id: str) -> dict[str, Any]: ...

    async def cancel(self, remote_task_id: str) -> dict[str, Any]: ...

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]: ...
