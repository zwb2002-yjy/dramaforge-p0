"""Explicit, network-only Edge Neural speech; never falls back to local TTS."""

from __future__ import annotations

import asyncio
import io
import wave
from contextlib import aclosing, suppress
from typing import Any
from uuid import uuid4

from edge_tts import Communicate
from edge_tts.exceptions import NoAudioReceived

from app.config import Settings

MAX_TEXT_CHARACTERS = 5_000
MAX_MP3_BYTES = 8 * 1024 * 1024
MAX_PCM_BYTES = 64 * 1024 * 1024
TOTAL_TIMEOUT_SECONDS = 90.0
PCM_SAMPLE_RATE = 24_000


class _EdgeTTSFailure(Exception):
    """An allowlisted, non-sensitive failure safe to return to callers."""


class EdgeNeuralAdapter:
    """Implement the local adapter's task/blob contract using an online service."""

    provider = "edge_tts"
    local = False
    execution_path_version = "edge-voice-v1"

    def __init__(self, settings: Settings, *, voice: str, rate_percent: int = 0) -> None:
        self._settings = settings
        self.model = voice
        self._rate_percent = rate_percent
        self._tasks: dict[str, dict[str, Any]] = {}
        self._inflight: dict[str, asyncio.Task[bytes]] = {}
        self.blobs: dict[str, bytes] = {}

    def _fail(self, task_id: str, message: str) -> dict[str, Any]:
        self.blobs.pop(task_id, None)
        if self._tasks.get(task_id, {}).get("status") == "cancelled":
            return {"remote_task_id": task_id, "status": "cancelled"}
        self._tasks[task_id] = {"status": "failed", "error": message}
        return {"remote_task_id": task_id, **self._tasks[task_id]}

    async def create(self, request: dict[str, Any]) -> dict[str, Any]:
        task_id = f"edge-tts-{uuid4()}"
        text = request.get("prompt")
        if text is None or (isinstance(text, str) and not text.strip()):
            return self._fail(task_id, "voice prompt is empty")
        if not isinstance(text, str):
            return self._fail(task_id, "voice prompt must be text")
        if len(text) > MAX_TEXT_CHARACTERS:
            return self._fail(task_id, "voice prompt exceeds 5000 characters")
        if not isinstance(self.model, str) or not self.model.strip():
            return self._fail(task_id, "Edge TTS voice is required")
        if isinstance(self._rate_percent, bool) or not isinstance(self._rate_percent, int):
            return self._fail(task_id, "Edge TTS rate must be an integer percentage")

        self._tasks[task_id] = {"status": "running"}
        work = asyncio.create_task(self._synthesize(text.strip()))
        self._inflight[task_id] = work
        try:
            wav = await asyncio.wait_for(work, timeout=TOTAL_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            explicitly_cancelled = self._tasks[task_id]["status"] == "cancelled"
            self.blobs.pop(task_id, None)
            self._tasks[task_id] = {"status": "cancelled"}
            caller = asyncio.current_task()
            if not explicitly_cancelled or (caller is not None and caller.cancelling()):
                raise
            return {"remote_task_id": task_id, "status": "cancelled"}
        except TimeoutError:
            return self._fail(task_id, "Edge TTS timed out")
        except NoAudioReceived:
            return self._fail(task_id, "Edge TTS returned no audio")
        except _EdgeTTSFailure as exc:
            return self._fail(task_id, str(exc))
        except Exception:
            # Provider exceptions can embed request text, proxy credentials or headers.
            return self._fail(task_id, "Edge TTS synthesis failed")
        finally:
            self._inflight.pop(task_id, None)

        if self._tasks[task_id]["status"] == "cancelled":
            return {"remote_task_id": task_id, "status": "cancelled"}
        self.blobs[task_id] = wav
        self._tasks[task_id] = {"status": "succeeded"}
        return {"remote_task_id": task_id, "status": "succeeded"}

    async def _synthesize(self, text: str) -> bytes:
        communicator = Communicate(
            text=text,
            voice=self.model,
            rate=f"{self._rate_percent:+d}%",
            proxy=self._settings.tts_proxy or None,
            connect_timeout=10,
            receive_timeout=30,
        )
        mp3 = bytearray()
        async with aclosing(communicator.stream()) as stream:
            async for chunk in stream:
                if chunk.get("type") != "audio":
                    continue
                data = chunk.get("data")
                if not isinstance(data, bytes):
                    raise _EdgeTTSFailure("Edge TTS returned invalid audio")
                if len(mp3) + len(data) > MAX_MP3_BYTES:
                    raise _EdgeTTSFailure("Edge TTS audio exceeds size limit")
                mp3.extend(data)
        if not mp3:
            raise _EdgeTTSFailure("Edge TTS returned no audio")
        return await self._transcode(bytes(mp3))

    async def _transcode(self, mp3: bytes) -> bytes:
        # Decode and encode with one thread each; emit PCM, not a pipe WAV header
        # with an unknown RIFF length. No text or proxy is passed to the process.
        spawn = asyncio.create_task(
            asyncio.create_subprocess_exec(
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-nostdin",
                "-threads", "1",
                "-filter_threads", "1",
                "-f", "mp3",
                "-i", "pipe:0",
                "-map", "0:a:0",
                "-vn",
                "-ac", "1",
                "-ar", str(PCM_SAMPLE_RATE),
                "-c:a", "pcm_s16le",
                "-threads", "1",
                "-f", "s16le",
                "pipe:1",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        )
        writer: asyncio.Task[None] | None = None
        try:
            # Keep the spawn alive until we can reap its process, even if cancelled
            # while the operating system is still creating it.
            process = await asyncio.shield(spawn)
            if process.stdin is None or process.stdout is None:
                raise _EdgeTTSFailure("Edge TTS audio conversion failed")
            writer = asyncio.create_task(self._write_mp3(process.stdin, mp3))
            pcm = bytearray()
            while chunk := await process.stdout.read(64 * 1024):
                if len(pcm) + len(chunk) > MAX_PCM_BYTES:
                    raise _EdgeTTSFailure("Edge TTS decoded audio exceeds size limit")
                pcm.extend(chunk)
            await writer
            returncode = await process.wait()
            if returncode != 0:
                raise _EdgeTTSFailure("Edge TTS audio conversion failed")
            if not pcm or len(pcm) % 2:
                raise _EdgeTTSFailure("Edge TTS returned invalid PCM audio")
            with io.BytesIO() as output:
                with wave.open(output, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(PCM_SAMPLE_RATE)
                    wav.writeframes(pcm)
                return output.getvalue()
        except FileNotFoundError:
            raise _EdgeTTSFailure("Edge TTS audio converter is unavailable") from None
        except (_EdgeTTSFailure, TimeoutError):
            raise
        except Exception:
            raise _EdgeTTSFailure("Edge TTS audio conversion failed") from None
        finally:
            cleanup = asyncio.create_task(self._reap_transcoder(spawn, writer))
            interrupted = False
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    # Repeated cancellation must not strand an ffmpeg process.
                    interrupted = True
            cleanup.result()
            if interrupted:
                raise asyncio.CancelledError

    @staticmethod
    async def _write_mp3(stdin: asyncio.StreamWriter, mp3: bytes) -> None:
        try:
            stdin.write(mp3)
            await stdin.drain()
        finally:
            stdin.close()

    @staticmethod
    async def _reap_transcoder(
        spawn: asyncio.Task[asyncio.subprocess.Process], writer: asyncio.Task[None] | None
    ) -> None:
        try:
            process = await spawn
        except Exception:
            return  # Spawn failed; there is no child to reap.
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        if writer is not None:
            if not writer.done():
                writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
        try:
            if process.stdin is not None:
                process.stdin.close()
            # A killed child can still have a full stdout pipe. Drain without
            # retaining bytes so Process.wait() cannot deadlock on that pipe.
            if process.stdout is not None:
                while await process.stdout.read(64 * 1024):
                    pass
        finally:
            await process.wait()

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        task = self._tasks.get(remote_task_id)
        if task is None:
            return {"status": "failed", "error": "unknown Edge TTS task"}
        return {"status": str(task["status"]), "error": task.get("error")}

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        if remote_task_id in self._tasks:
            self._tasks[remote_task_id] = {"status": "cancelled"}
        self.blobs.pop(remote_task_id, None)
        work = self._inflight.get(remote_task_id)
        if work is not None:
            if not work.done() and not work.cancelling():
                work.cancel()
            await asyncio.gather(work, return_exceptions=True)
        return {"status": "cancelled"}

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        _ = remote_task_id
        return {"amount": 0.0, "currency": "USD", "units": 0.0}
