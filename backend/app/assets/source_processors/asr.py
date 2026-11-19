"""Local whisper.cpp CLI adapter: bounded windows, real model identity, no fallback.

Weights are verified by SHA-256 before use; a missing binary, model or mismatch is an
explicit ``source_processor_unavailable`` (or ``source_model_identity_mismatch``) and is
never replaced by a cloud ASR call. Word-level alignment is not guaranteed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.assets.source_processors.contracts import ASR_TIMEOUT_SECONDS, SourceParseError

PROCESSOR_REF = "whisper-cli"
DEFAULT_MODEL_PATH = "/opt/whisper/ggml-base.bin"
DEFAULT_MODEL_SHA256 = "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe"
DEFAULT_VERSION = "v1.9.5"
DEFAULT_LANGUAGE = "auto"
_MODEL_HASH_CACHE: dict[str, str] = {}


@dataclass(frozen=True)
class TranscriptSegment:
    text: str
    start_ms: int
    end_ms: int


def executable() -> str | None:
    return os.environ.get("DRAMAFORGE_WHISPER_CLI") or shutil.which("whisper-cli")


def model_path() -> Path | None:
    candidate = Path(os.environ.get("DRAMAFORGE_WHISPER_MODEL", DEFAULT_MODEL_PATH))
    return candidate if candidate.is_file() else None


def version() -> str:
    return os.environ.get("DRAMAFORGE_WHISPER_VERSION", DEFAULT_VERSION)


def model_sha256(path: Path) -> str:
    key = str(path)
    if key not in _MODEL_HASH_CACHE:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        _MODEL_HASH_CACHE[key] = digest.hexdigest()
    return _MODEL_HASH_CACHE[key]


def expected_model_sha256() -> str:
    return os.environ.get("DRAMAFORGE_WHISPER_MODEL_SHA256", DEFAULT_MODEL_SHA256)


def require_model() -> tuple[Path, str]:
    """Return the verified model path and its digest; never a fabricated hash."""
    path = model_path()
    if path is None:
        raise SourceParseError("source_processor_unavailable")
    digest = model_sha256(path)
    expected = expected_model_sha256()
    if expected and digest != expected:
        raise SourceParseError("source_model_identity_mismatch")
    return path, digest


def transcribe(wav_path: Path, *, language: str | None = None) -> list[TranscriptSegment]:
    binary = executable()
    if binary is None:
        raise SourceParseError("source_processor_unavailable")
    model, _digest = require_model()
    threads = os.environ.get("DRAMAFORGE_WHISPER_THREADS", "4")
    with tempfile.TemporaryDirectory(prefix="df-asr-") as work:
        out_base = Path(work) / "out"
        try:
            completed = subprocess.run(
                [
                    binary,
                    "-m", str(model),
                    "-f", str(wav_path),
                    "-l", language or DEFAULT_LANGUAGE,
                    "-t", threads,
                    "-np",
                    "-oj",
                    "-of", str(out_base),
                ],
                capture_output=True,
                timeout=ASR_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError:
            raise SourceParseError("source_processor_unavailable") from None
        except (OSError, subprocess.SubprocessError):
            raise SourceParseError("source_processor_unavailable") from None
        payload_path = Path(f"{out_base}.json")
        if completed.returncode != 0 or not payload_path.exists():
            raise SourceParseError("source_asr_failed")
        payload = json.loads(payload_path.read_text(encoding="utf-8", errors="replace"))
    segments: list[TranscriptSegment] = []
    for item in payload.get("transcription") or []:
        text = str(item.get("text") or "").strip()
        offsets = item.get("offsets") or {}
        if not text:
            continue
        start = int(offsets.get("from") or 0)
        end = int(offsets.get("to") or start)
        segments.append(TranscriptSegment(text=text, start_ms=start, end_ms=max(end, start)))
    return segments


__all__ = [
    "DEFAULT_MODEL_SHA256",
    "PROCESSOR_REF",
    "TranscriptSegment",
    "executable",
    "expected_model_sha256",
    "model_path",
    "model_sha256",
    "require_model",
    "transcribe",
    "version",
]
