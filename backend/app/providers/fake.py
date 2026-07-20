"""In-process fake Adapters for local S2+ vertical slices (no paid BYOK)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4


class FakeOpenAIAdapter:
    provider = "openai"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._tasks: dict[str, dict[str, Any]] = {}

    async def create(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"op": "create", "request": request})
        task_id = f"fake-openai-{uuid4()}"
        self._tasks[task_id] = {
            "status": "succeeded",
            "text": request.get("prompt", "brief"),
        }
        return {"remote_task_id": task_id, "status": "succeeded"}

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        task = self._tasks.get(remote_task_id)
        if task is None:
            return {"status": "failed", "error": "unknown task"}
        return {"status": task["status"], "progress": 1.0, "text": task.get("text")}

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        if remote_task_id in self._tasks:
            self._tasks[remote_task_id]["status"] = "cancelled"
        return {"status": "cancelled"}

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        _ = remote_task_id
        return {"amount": 0.0, "currency": "USD", "units": 0.0}


class FakeFluxAdapter:
    provider = "flux"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._tasks: dict[str, dict[str, Any]] = {}
        self.blobs: dict[str, bytes] = {}

    async def create(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"op": "create", "request": request})
        task_id = f"fake-flux-{uuid4()}"
        # Deterministic non-empty PNG-ish payload for MinIO/hash proof
        blob = b"\x89PNG\r\n\x1a\n" + str(request.get("prompt", "frame")).encode()
        self.blobs[task_id] = blob
        self._tasks[task_id] = {
            "status": "succeeded",
            "artifact_uri": f"minio://fake/{task_id}.png",
            "content_hash": "a" * 64,
        }
        return {"remote_task_id": task_id, "status": "succeeded"}

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        task = self._tasks.get(remote_task_id)
        if task is None:
            return {"status": "failed", "error": "unknown task"}
        return {
            "status": task["status"],
            "progress": 1.0,
            "artifact_uri": task.get("artifact_uri"),
            "content_hash": task.get("content_hash"),
        }

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        if remote_task_id in self._tasks:
            self._tasks[remote_task_id]["status"] = "cancelled"
        return {"status": "cancelled"}

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        _ = remote_task_id
        # Fake path: zero real spend; still records a ledger-shaped result.
        return {"amount": 0.0, "currency": "USD", "units": 1.0}
