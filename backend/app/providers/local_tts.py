"""Opt-in local eSpeak NG adapter for real development voice generation."""

from __future__ import annotations

import asyncio
import shutil
from typing import Any
from uuid import uuid4

from app.config import Settings, get_settings
from app.providers.errors import ProviderNotConfiguredError


class LocalEspeakAdapter:
    """Generate actual WAV bytes through a locally installed eSpeak NG binary."""

    provider = "local_tts"
    model = "espeak-ng"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._tasks: dict[str, dict[str, Any]] = {}
        self.blobs: dict[str, bytes] = {}

    async def create(self, request: dict[str, Any]) -> dict[str, Any]:
        text = str(request.get("prompt") or "").strip()
        task_id = f"local-tts-{uuid4()}"
        if not text:
            self._tasks[task_id] = {"status": "failed", "error": "voice prompt is empty"}
            return {"remote_task_id": task_id, "status": "failed"}

        try:
            process = await asyncio.create_subprocess_exec(
                self._settings.tts_engine,
                "--stdout",
                "-v",
                self._settings.tts_voice,
                text,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60.0)
        except FileNotFoundError:
            message = f"TTS executable not found: {self._settings.tts_engine}"
            self._tasks[task_id] = {"status": "failed", "error": message}
            return {"remote_task_id": task_id, "status": "failed"}
        except TimeoutError:
            self._tasks[task_id] = {"status": "failed", "error": "TTS process timed out"}
            return {"remote_task_id": task_id, "status": "failed"}

        if process.returncode != 0 or not stdout.startswith(b"RIFF"):
            detail = stderr.decode("utf-8", errors="replace").strip()[:300]
            message = detail or f"TTS process failed with exit code {process.returncode}"
            self._tasks[task_id] = {"status": "failed", "error": message}
            return {"remote_task_id": task_id, "status": "failed"}

        self.blobs[task_id] = stdout
        self._tasks[task_id] = {"status": "succeeded"}
        return {"remote_task_id": task_id, "status": "succeeded"}

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        task = self._tasks.get(remote_task_id)
        if task is None:
            return {"status": "failed", "error": "unknown local TTS task"}
        return {"status": str(task["status"]), "error": task.get("error")}

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        if remote_task_id in self._tasks:
            self._tasks[remote_task_id]["status"] = "cancelled"
        return {"status": "cancelled"}

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        _ = remote_task_id
        return {"amount": 0.0, "currency": "USD", "units": 0.0}


def get_local_tts_adapter() -> LocalEspeakAdapter:
    """Return local real TTS only when explicitly enabled and installed."""
    settings = get_settings()
    if not settings.tts_enabled:
        raise ProviderNotConfiguredError(
            "provider_not_configured: local TTS disabled (TTS_ENABLED=false). "
            "Enable TTS_ENABLED and install the configured TTS_ENGINE."
        )
    if shutil.which(settings.tts_engine) is None:
        raise ProviderNotConfiguredError(
            f"provider_not_configured: TTS executable unavailable: {settings.tts_engine}"
        )
    return LocalEspeakAdapter(settings)
