"""Offline adapter contracts: no Edge requests, ffmpeg processes or audio files."""

from __future__ import annotations

import asyncio
import io
import wave
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from app.config import Settings
from app.providers import edge_tts as edge_module
from app.providers.edge_tts import EdgeNeuralAdapter
from app.providers.local_tts import LocalEspeakAdapter
from edge_tts.exceptions import NoAudioReceived

PCM = b"\x01\x00\xff\xff" * 8
PRIVATE_TEXT = "private-dialogue-sentinel"
PRIVATE_PROXY = "http://test-user:test-password@proxy.invalid:8080"
PRIVATE_ERROR = f"{PRIVATE_TEXT} {PRIVATE_PROXY} raw-header-sentinel"


class _Transcoder:
    def __init__(self) -> None:
        self.stdin = Mock()
        self.stdin.drain = AsyncMock()
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(PCM)
        self.stdout.feed_eof()
        self.killed = asyncio.Event()
        self.returncode: int | None = None
        self.exit_code = 0
        self.kill = Mock(side_effect=self._kill)
        self.wait = AsyncMock(side_effect=self._wait)

    def _kill(self) -> None:
        self.returncode = -9
        self.killed.set()
        if isinstance(self.stdout, asyncio.StreamReader):
            self.stdout.feed_eof()

    async def _wait(self) -> int:
        if self.returncode is None:
            self.returncode = self.exit_code
        return self.returncode


class _Harness:
    def __init__(self) -> None:
        self.process = _Transcoder()
        self.chunks: list[dict[str, Any]] = [
            {"type": "WordBoundary", "text": PRIVATE_TEXT},
            {"type": "audio", "data": b"mp3-first"},
            {"type": "audio", "data": b"mp3-second"},
        ]
        self.error: Exception | None = None
        self.stream_gate: asyncio.Event | None = None
        self.stream_started = asyncio.Event()
        self.stream_closed = asyncio.Event()
        self.communicate = Mock(return_value=SimpleNamespace(stream=self.stream))
        self.spawn = AsyncMock(return_value=self.process)

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        self.stream_started.set()
        try:
            if self.stream_gate is not None:
                await self.stream_gate.wait()
            for chunk in self.chunks:
                yield chunk
            if self.error is not None:
                raise self.error
        finally:
            self.stream_closed.set()


@pytest.fixture(autouse=True)
async def fake(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[_Harness]:
    harness = _Harness()
    monkeypatch.setattr(edge_module, "Communicate", harness.communicate)
    monkeypatch.setattr(edge_module.asyncio, "create_subprocess_exec", harness.spawn)
    legacy = AsyncMock(side_effect=AssertionError("legacy fallback is forbidden"))
    monkeypatch.setattr(LocalEspeakAdapter, "create", legacy)
    yield harness
    legacy.assert_not_called()


@pytest.fixture
def adapter() -> EdgeNeuralAdapter:
    # model_construct deliberately bypasses environment and .env loading.
    return EdgeNeuralAdapter(
        Settings.model_construct(tts_proxy=None), voice="zh-CN-XiaoxiaoNeural"
    )


@pytest.mark.parametrize(
    ("voice", "rate", "expected_rate"),
    [
        ("zh-CN-XiaoxiaoNeural", 0, "+0%"),
        ("zh-CN-YunxiNeural", 15, "+15%"),
        ("zh-CN-XiaoxiaoNeural", -12, "-12%"),
    ],
)
async def test_success_preserves_voice_rate_and_wav_contract(
    fake: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    voice: str,
    rate: int,
    expected_rate: str,
) -> None:
    adapter = EdgeNeuralAdapter(
        Settings.model_construct(tts_proxy=PRIVATE_PROXY), voice=voice, rate_percent=rate
    )
    wait_for = AsyncMock(wraps=asyncio.wait_for)
    monkeypatch.setattr(edge_module.asyncio, "wait_for", wait_for)

    result = await adapter.create({"prompt": "  你好，欢迎来到剧场。  "})
    task_id = result["remote_task_id"]

    assert result["status"] == "succeeded"
    assert await adapter.poll(task_id) == {"status": "succeeded", "error": None}
    assert adapter.provider == "edge_tts"
    assert adapter.model == voice
    assert adapter.local is False
    assert adapter.execution_path_version == "edge-voice-v1"
    assert await adapter.fetch_cost(task_id) == {
        "amount": 0.0, "currency": "USD", "units": 0.0
    }
    fake.communicate.assert_called_once_with(
        text="你好，欢迎来到剧场。",
        voice=voice,
        rate=expected_rate,
        proxy=PRIVATE_PROXY,
        connect_timeout=10,
        receive_timeout=30,
    )
    assert wait_for.call_args.kwargs["timeout"] == 90.0
    assert fake.stream_closed.is_set()

    fake.spawn.assert_awaited_once_with(
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
        "-ar", "24000",
        "-c:a", "pcm_s16le",
        "-threads", "1",
        "-f", "s16le",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    fake.process.stdin.write.assert_called_once_with(b"mp3-firstmp3-second")
    fake.process.stdin.drain.assert_awaited_once()
    fake.process.stdin.close.assert_called()
    fake.process.wait.assert_awaited()
    fake.process.kill.assert_not_called()
    wav_bytes = adapter.blobs[task_id]
    assert len(adapter.blobs) == 1
    assert wav_bytes[:4] == b"RIFF"
    assert int.from_bytes(wav_bytes[4:8], "little") == len(wav_bytes) - 8
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        assert wav.getframerate() == 24000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getcomptype() == "NONE"
        assert wav.getnframes() == 16
        assert wav.readframes(100) == PCM
        assert wav.readframes(1) == b""


@pytest.mark.parametrize("proxy", [None, ""])
async def test_empty_proxy_is_passed_as_none(fake: _Harness, proxy: str | None) -> None:
    adapter = EdgeNeuralAdapter(
        Settings.model_construct(tts_proxy=proxy), voice="zh-CN-XiaoxiaoNeural"
    )

    result = await adapter.create({"prompt": PRIVATE_TEXT})

    assert result["status"] == "succeeded"
    fake.communicate.assert_called_once_with(
        text=PRIVATE_TEXT,
        voice="zh-CN-XiaoxiaoNeural",
        rate="+0%",
        proxy=None,
        connect_timeout=10,
        receive_timeout=30,
    )


@pytest.mark.parametrize("prompt", [None, "", " \n\t", 123, ["text"]])
async def test_invalid_prompt_fails_before_network_or_process(
    fake: _Harness, adapter: EdgeNeuralAdapter, prompt: Any
) -> None:
    result = await adapter.create({"prompt": prompt})

    assert result["status"] == "failed"
    assert (await adapter.poll(result["remote_task_id"]))["status"] == "failed"
    assert not adapter.blobs
    fake.communicate.assert_not_called()
    fake.spawn.assert_not_awaited()


@pytest.mark.parametrize("prompt", ["中" * 5001, " " * 5000 + "中"])
async def test_input_limit_applies_before_whitespace_trimming(
    fake: _Harness, adapter: EdgeNeuralAdapter, prompt: str
) -> None:
    result = await adapter.create({"prompt": prompt})

    assert result["status"] == "failed"
    assert result["error"] == "voice prompt exceeds 5000 characters"
    assert not adapter.blobs
    fake.communicate.assert_not_called()
    fake.spawn.assert_not_awaited()


async def test_exactly_5000_characters_is_allowed(
    fake: _Harness, adapter: EdgeNeuralAdapter
) -> None:
    result = await adapter.create({"prompt": "中" * 5000})

    assert result["status"] == "succeeded"
    assert fake.communicate.call_args.kwargs["text"] == "中" * 5000


@pytest.mark.parametrize(
    "chunks",
    [[], [{"type": "SentenceBoundary", "text": PRIVATE_TEXT}], [{"type": "audio", "data": b""}]],
)
async def test_empty_audio_is_failed_without_blob_or_transcoding(
    fake: _Harness, adapter: EdgeNeuralAdapter, chunks: list[dict[str, Any]]
) -> None:
    fake.chunks = chunks
    result = await adapter.create({"prompt": PRIVATE_TEXT})

    assert result["status"] == "failed"
    assert result["error"] == "Edge TTS returned no audio"
    assert not adapter.blobs
    assert fake.stream_closed.is_set()
    fake.spawn.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (NoAudioReceived(PRIVATE_ERROR), "Edge TTS returned no audio"),
        (RuntimeError(PRIVATE_ERROR), "Edge TTS synthesis failed"),
        (TimeoutError(PRIVATE_ERROR), "Edge TTS timed out"),
    ],
)
async def test_provider_failure_never_exposes_details_or_falls_back(
    fake: _Harness, adapter: EdgeNeuralAdapter, error: Exception, expected: str
) -> None:
    fake.error = error  # Fail after partial MP3 bytes have already arrived.
    result = await adapter.create({"prompt": PRIVATE_TEXT})
    polled = await adapter.poll(result["remote_task_id"])

    assert result["status"] == "failed"
    assert result["error"] == expected
    assert polled == {"status": "failed", "error": expected}
    assert PRIVATE_TEXT not in repr((result, polled))
    assert PRIVATE_PROXY not in repr((result, polled))
    assert "raw-header-sentinel" not in repr((result, polled))
    assert not adapter.blobs
    assert fake.stream_closed.is_set()
    fake.communicate.assert_called_once()
    fake.spawn.assert_not_awaited()


async def test_constructor_failure_is_also_sanitized(
    fake: _Harness, adapter: EdgeNeuralAdapter
) -> None:
    fake.communicate.side_effect = ValueError(PRIVATE_ERROR)

    result = await adapter.create({"prompt": PRIVATE_TEXT})

    assert result["status"] == "failed"
    assert result["error"] == "Edge TTS synthesis failed"
    assert not adapter.blobs
    fake.spawn.assert_not_awaited()


async def test_mp3_stream_limit_closes_stream_before_transcoding(
    fake: _Harness, adapter: EdgeNeuralAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(edge_module, "MAX_MP3_BYTES", 12)

    result = await adapter.create({"prompt": PRIVATE_TEXT})

    assert result["status"] == "failed"
    assert result["error"] == "Edge TTS audio exceeds size limit"
    assert fake.stream_closed.is_set()
    assert not adapter.blobs
    fake.spawn.assert_not_awaited()


async def test_invalid_stream_data_is_rejected(
    fake: _Harness, adapter: EdgeNeuralAdapter
) -> None:
    fake.chunks = [{"type": "audio", "data": PRIVATE_TEXT}]

    result = await adapter.create({"prompt": PRIVATE_TEXT})

    assert result["status"] == "failed"
    assert result["error"] == "Edge TTS returned invalid audio"
    assert not adapter.blobs
    fake.spawn.assert_not_awaited()


async def test_pcm_limit_kills_and_reaps_converter(
    fake: _Harness, adapter: EdgeNeuralAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(edge_module, "MAX_PCM_BYTES", 8)

    result = await adapter.create({"prompt": PRIVATE_TEXT})

    assert result["status"] == "failed"
    assert result["error"] == "Edge TTS decoded audio exceeds size limit"
    assert not adapter.blobs
    fake.process.kill.assert_called_once()
    fake.process.wait.assert_awaited()
    fake.process.stdin.close.assert_called()


@pytest.mark.parametrize("pcm", [b"", b"\x00"])
async def test_empty_or_unaligned_pcm_is_not_published(
    fake: _Harness, adapter: EdgeNeuralAdapter, pcm: bytes
) -> None:
    fake.process.stdout = asyncio.StreamReader()
    fake.process.stdout.feed_data(pcm)
    fake.process.stdout.feed_eof()

    result = await adapter.create({"prompt": PRIVATE_TEXT})

    assert result["status"] == "failed"
    assert result["error"] == "Edge TTS returned invalid PCM audio"
    assert not adapter.blobs
    fake.process.wait.assert_awaited()


async def test_nonzero_converter_exit_rejects_even_nonempty_output(
    fake: _Harness, adapter: EdgeNeuralAdapter
) -> None:
    fake.process.exit_code = 1

    result = await adapter.create({"prompt": PRIVATE_TEXT})

    assert result["status"] == "failed"
    assert result["error"] == "Edge TTS audio conversion failed"
    assert not adapter.blobs
    fake.process.wait.assert_awaited()


@pytest.mark.parametrize("error", [FileNotFoundError(PRIVATE_ERROR), OSError(PRIVATE_ERROR)])
async def test_converter_spawn_failure_is_safe_and_has_no_fallback(
    fake: _Harness, adapter: EdgeNeuralAdapter, error: Exception
) -> None:
    fake.spawn.side_effect = error

    result = await adapter.create({"prompt": PRIVATE_TEXT})

    assert result["status"] == "failed"
    assert result["error"] in {
        "Edge TTS audio converter is unavailable", "Edge TTS audio conversion failed"
    }
    assert not adapter.blobs
    assert PRIVATE_ERROR not in repr(result)
    fake.spawn.assert_awaited_once()


async def test_download_is_subject_to_total_deadline(
    fake: _Harness, adapter: EdgeNeuralAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(edge_module, "TOTAL_TIMEOUT_SECONDS", 0.02)
    fake.stream_gate = asyncio.Event()

    result = await adapter.create({"prompt": PRIVATE_TEXT})

    assert result["status"] == "failed"
    assert result["error"] == "Edge TTS timed out"
    assert fake.stream_closed.is_set()
    assert not adapter.blobs
    fake.spawn.assert_not_awaited()


async def test_converter_timeout_kills_and_waits_without_partial_blob(
    fake: _Harness, adapter: EdgeNeuralAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(edge_module, "TOTAL_TIMEOUT_SECONDS", 0.02)
    fake.process.stdout = asyncio.StreamReader()
    fake.process.stdout.feed_data(PCM)  # No EOF: the converter then hangs.

    result = await adapter.create({"prompt": PRIVATE_TEXT})

    assert result["status"] == "failed"
    assert result["error"] == "Edge TTS timed out"
    assert not adapter.blobs
    fake.process.kill.assert_called_once()
    fake.process.wait.assert_awaited()
    fake.process.stdin.close.assert_called()


@pytest.mark.parametrize("explicit_cancel", [False, True])
async def test_cancel_during_conversion_reaps_child_and_never_publishes(
    fake: _Harness,
    adapter: EdgeNeuralAdapter,
    monkeypatch: pytest.MonkeyPatch,
    explicit_cancel: bool,
) -> None:
    monkeypatch.setattr(edge_module, "uuid4", lambda: "cancel-test")
    task_id = "edge-tts-cancel-test"
    reading = asyncio.Event()

    async def blocked_read(_size: int) -> bytes:
        reading.set()
        await fake.process.killed.wait()
        return b""

    fake.process.stdout = SimpleNamespace(read=AsyncMock(side_effect=blocked_read))
    creation = asyncio.create_task(adapter.create({"prompt": PRIVATE_TEXT}))
    await asyncio.wait_for(reading.wait(), timeout=1.0)
    assert (await adapter.poll(task_id))["status"] == "running"

    if explicit_cancel:
        assert await adapter.cancel(task_id) == {"status": "cancelled"}
        assert await creation == {"remote_task_id": task_id, "status": "cancelled"}
    else:
        creation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await creation

    assert await adapter.poll(task_id) == {"status": "cancelled", "error": None}
    assert not adapter.blobs
    fake.process.kill.assert_called_once()
    fake.process.wait.assert_awaited()
    fake.process.stdin.close.assert_called()


async def test_cancel_while_spawning_still_reaps_eventual_child(
    fake: _Harness, adapter: EdgeNeuralAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(edge_module, "uuid4", lambda: "spawn-test")
    spawning = asyncio.Event()
    release_spawn = asyncio.Event()

    async def delayed_spawn(*_args: Any, **_kwargs: Any) -> _Transcoder:
        spawning.set()
        await release_spawn.wait()
        return fake.process

    fake.spawn.side_effect = delayed_spawn
    creation = asyncio.create_task(adapter.create({"prompt": PRIVATE_TEXT}))
    await asyncio.wait_for(spawning.wait(), timeout=1.0)
    creation.cancel()
    await asyncio.sleep(0)  # Deliver cancellation while no process handle is available.
    release_spawn.set()
    with pytest.raises(asyncio.CancelledError):
        await creation

    assert (await adapter.poll("edge-tts-spawn-test"))["status"] == "cancelled"
    assert not adapter.blobs
    fake.process.kill.assert_called_once()
    fake.process.wait.assert_awaited()


async def test_cancel_during_download_closes_stream_without_transcoding(
    fake: _Harness, adapter: EdgeNeuralAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(edge_module, "uuid4", lambda: "download-test")
    fake.stream_gate = asyncio.Event()
    creation = asyncio.create_task(adapter.create({"prompt": PRIVATE_TEXT}))
    await asyncio.wait_for(fake.stream_started.wait(), timeout=1.0)

    assert await adapter.cancel("edge-tts-download-test") == {"status": "cancelled"}
    assert (await creation)["status"] == "cancelled"
    assert fake.stream_closed.is_set()
    assert not adapter.blobs
    fake.spawn.assert_not_awaited()


async def test_cancel_removes_an_existing_blob(adapter: EdgeNeuralAdapter) -> None:
    result = await adapter.create({"prompt": PRIVATE_TEXT})
    task_id = result["remote_task_id"]
    assert task_id in adapter.blobs

    assert await adapter.cancel(task_id) == {"status": "cancelled"}
    assert await adapter.poll(task_id) == {"status": "cancelled", "error": None}
    assert not adapter.blobs


async def test_unknown_task_contract(adapter: EdgeNeuralAdapter) -> None:
    assert await adapter.poll("unknown") == {
        "status": "failed", "error": "unknown Edge TTS task"
    }
    assert await adapter.cancel("unknown") == {"status": "cancelled"}
    assert not adapter.blobs

async def test_broken_converter_input_is_safe_and_reaps_child(
    fake: _Harness, adapter: EdgeNeuralAdapter
) -> None:
    fake.process.stdin.drain.side_effect = BrokenPipeError(PRIVATE_ERROR)

    result = await adapter.create({"prompt": PRIVATE_TEXT})

    assert result["status"] == "failed"
    assert result["error"] == "Edge TTS audio conversion failed"
    assert not adapter.blobs
    fake.process.kill.assert_called_once()
    fake.process.wait.assert_awaited()
    fake.process.stdin.close.assert_called()
