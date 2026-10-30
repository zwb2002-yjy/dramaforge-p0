"""Provider media ingestion: pinned HTTPS, bounded validation and decoded metadata."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import httpcore
import httpx
from httpcore._backends.base import (
    SOCKET_OPTION,
    AsyncNetworkBackend,
    AsyncNetworkStream,
)
from PIL import Image, UnidentifiedImageError

from app.config import get_settings
from app.execution.models import Artifact
from app.shared.errors import (
    ValidationAppError,
)
from app.storage.materialized import MaterializedFile, MediaTransferError, materialize_stream

logger = logging.getLogger(__name__)

_MAX_PROVIDER_MEDIA_BYTES = 512 * 1024 * 1024

# One dropped connection must not discard an already-paid generation, so a
# failed fetch is retried a bounded number of times before it becomes terminal.
_MEDIA_DOWNLOAD_ATTEMPTS = 3
_MEDIA_DOWNLOAD_RETRY_DELAYS: tuple[float, ...] = (1.0, 3.0)


_MAX_PROVIDER_IMAGE_BYTES = 20 * 1024 * 1024


def _is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global


async def _validate_public_media_url(value: str) -> tuple[str, set[str]]:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValidationAppError("PROVIDER_MEDIA_URL_INVALID: media URL must be HTTPS")
    host = parsed.hostname.rstrip(".")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise ValidationAppError("PROVIDER_MEDIA_URL_INVALID: media URL port is invalid") from exc
    try:
        addresses = {str(ipaddress.ip_address(host))}
    except ValueError:
        try:
            resolved = await asyncio.to_thread(
                socket.getaddrinfo,
                host,
                port,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise ValidationAppError(
                "PROVIDER_MEDIA_URL_INVALID: media host cannot be resolved"
            ) from exc
        addresses = {str(item[4][0]) for item in resolved}
    if not addresses or not all(_is_public_ip(address) for address in addresses):
        raise ValidationAppError("PROVIDER_MEDIA_URL_INVALID: media host is not public")
    return value, addresses


class _PinnedNetworkBackend(AsyncNetworkBackend):
    """Resolve a provider result once, then connect only to that IP."""

    def __init__(self, *, hostname: str, addresses: set[str]) -> None:
        from httpcore._backends.auto import AutoBackend

        self._hostname = hostname.lower().rstrip(".")
        self._address = sorted(addresses)[0]
        self._backend = AutoBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> AsyncNetworkStream:
        target = self._address if host.lower().rstrip(".") == self._hostname else host
        return await self._backend.connect_tcp(
            target,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> AsyncNetworkStream:
        return await self._backend.connect_unix_socket(
            path,
            timeout=timeout,
            socket_options=socket_options,
        )

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


async def _download_provider_media(
    *,
    kind: str,
    artifact_uri: str,
    destination: Path,
    transport: httpx.AsyncBaseTransport | None = None,
) -> MaterializedFile:
    """Download one provider result with pinned DNS, bounded streaming and retries.

    The remote task has already succeeded by the time its bytes are fetched, so a
    transient transport error (a dropped connection mid-response, a momentary
    resolver/route failure) must not destroy an already-paid generation.  Only
    transport failures are retried: a redirect, an oversized body or invalid
    media is a policy answer and fails immediately.
    """
    value, addresses = await _validate_public_media_url(artifact_uri)
    last_transport_error: Exception | None = None
    for attempt in range(1, _MEDIA_DOWNLOAD_ATTEMPTS + 1):
        try:
            return await _download_provider_media_once(
                kind=kind,
                value=value,
                addresses=addresses,
                transport=transport,
                destination=destination,
            )
        except (httpx.TransportError, OSError) as exc:
            last_transport_error = exc
            if attempt == _MEDIA_DOWNLOAD_ATTEMPTS:
                break
            delay = _MEDIA_DOWNLOAD_RETRY_DELAYS[attempt - 1]
            logger.warning(
                "Provider media download attempt %s/%s failed (%s); retrying in %ss",
                attempt,
                _MEDIA_DOWNLOAD_ATTEMPTS,
                type(exc).__name__,
                delay,
            )
            await asyncio.sleep(delay)
    assert last_transport_error is not None
    raise last_transport_error


async def _download_provider_media_once(
    *,
    kind: str,
    value: str,
    addresses: set[str],
    transport: httpx.AsyncBaseTransport | None,
    destination: Path,
) -> MaterializedFile:
    """One existing result, with pinned DNS and bounded disk transfer."""
    if transport is None:
        host = (urlsplit(value).hostname or "").rstrip(".")
        base_transport = httpx.AsyncHTTPTransport(
            trust_env=False,
            limits=httpx.Limits(max_connections=1),
        )
        ssl_context = base_transport._pool._ssl_context
        base_transport._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context,
            max_connections=1,
            max_keepalive_connections=0,
            network_backend=_PinnedNetworkBackend(hostname=host, addresses=addresses),
        )
        transport = base_transport
    async with (
        httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=20.0),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client,
        client.stream("GET", value, headers={"Accept-Encoding": "identity"}) as response,
    ):
        if response.is_redirect:
            raise ValidationAppError(
                "PROVIDER_MEDIA_INVALID: provider media redirects are not allowed"
            )
        response.raise_for_status()
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise ValidationAppError(
                "PROVIDER_MEDIA_INVALID: encoded media response is not allowed"
            )
        length = response.headers.get("Content-Length")
        try:
            expected = int(length) if length is not None else None
        except ValueError as exc:
            raise ValidationAppError(
                "PROVIDER_MEDIA_INVALID: response Content-Length is invalid"
            ) from exc
        return await _materialize_provider_media(
            kind=kind,
            chunks=response.aiter_bytes(64 * 1024),
            destination=destination,
            content_type=response.headers.get("Content-Type"),
            expected_size=expected,
        )


async def _materialize_provider_media(
    *,
    kind: str,
    chunks: AsyncIterator[bytes],
    destination: Path,
    content_type: str | None,
    expected_size: int | None = None,
) -> MaterializedFile:
    try:
        media = await materialize_stream(
            chunks,
            destination=destination,
            max_bytes=min(_MAX_PROVIDER_MEDIA_BYTES, _MAX_PROVIDER_IMAGE_BYTES)
            if kind in {"keyframe", "image"}
            else _MAX_PROVIDER_MEDIA_BYTES,
            expected_size=expected_size,
        )
    except MediaTransferError as exc:
        raise ValidationAppError(
            f"PROVIDER_MEDIA_INVALID: Content-Length/response size: {exc}"
        ) from exc
    try:
        with media.path.open("rb") as source:
            _validate_provider_media(kind=kind, data=source.read(64), content_type=content_type)
    except BaseException:
        media.path.unlink(missing_ok=True)
        raise
    return media


def _detected_media_format(*, kind: str, header: bytes) -> tuple[str, str] | None:
    if kind in {"keyframe", "image"}:
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png", "png"
        if header.startswith(b"\xff\xd8\xff"):
            return "image/jpeg", "jpg"
        if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
            return "image/webp", "webp"
    if kind in {"video", "video_review", "composite"}:
        if len(header) >= 12 and header[4:8] == b"ftyp":
            return ("video/quicktime", "mov") if header[8:12] == b"qt  " else ("video/mp4", "mp4")
        if header.startswith(b"\x1a\x45\xdf\xa3") and b"webm" in header:
            return "video/webm", "webm"
    if kind in {"voice", "audio"}:
        if header[:4] == b"RIFF" and header[8:12] == b"WAVE":
            return "audio/wav", "wav"
        if header.startswith((b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
            return "audio/mpeg", "mp3"
        if len(header) >= 12 and header[4:8] == b"ftyp":
            return "audio/mp4", "m4a"
    return None


def _validate_provider_media(*, kind: str, data: bytes, content_type: str | None) -> bytes:
    detected = _detected_media_format(kind=kind, header=data)
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized_type == "audio/x-wav":
        normalized_type = "audio/wav"
    if not detected or (normalized_type and normalized_type != detected[0]):
        raise ValidationAppError(
            "PROVIDER_MEDIA_INVALID: response MIME/bytes do not match media kind"
        )
    return data


@dataclass(frozen=True)
class _MediaMetadata:
    width: int | None = None
    height: int | None = None
    duration_seconds: Decimal | None = None


def _inspect_media_metadata(*, kind: str, path: Path) -> _MediaMetadata:
    """Decode deterministic media metadata before bytes enter object storage."""
    if kind in {"keyframe", "image"}:
        try:
            with Image.open(path) as image:
                image.load()
                return _MediaMetadata(width=image.width, height=image.height)
        except (UnidentifiedImageError, OSError) as exc:
            if get_settings().app_env != "test":
                raise ValidationAppError("PROVIDER_MEDIA_INVALID: image cannot be decoded") from exc
            return _MediaMetadata()
    if kind not in {"video", "video_review", "composite"}:
        return _MediaMetadata()
    import cv2

    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            if get_settings().app_env == "test":
                return _MediaMetadata()
            raise ValidationAppError("PROVIDER_MEDIA_INVALID: video cannot be decoded")
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_rate = float(capture.get(cv2.CAP_PROP_FPS))
        if width <= 0 or height <= 0 or frame_count <= 0 or frame_rate <= 0:
            if get_settings().app_env == "test":
                return _MediaMetadata()
            raise ValidationAppError("PROVIDER_MEDIA_INVALID: video metadata is invalid")
        return _MediaMetadata(
            width=width,
            height=height,
            duration_seconds=Decimal(str(round(frame_count / frame_rate, 3))),
        )
    finally:
        capture.release()


def _apply_media_metadata(artifact: Artifact, metadata: _MediaMetadata) -> None:
    artifact.width = metadata.width
    artifact.height = metadata.height
    artifact.duration_seconds = metadata.duration_seconds


async def _resolve_media_file(
    *,
    kind: str,
    remote: str,
    prompt: str,
    artifact_uri: object,
    destination: Path,
) -> MaterializedFile:
    """Materialize one existing result without copying its full media body."""
    from app.config import get_settings

    content_type = None
    synthetic = False
    if isinstance(artifact_uri, str) and artifact_uri.startswith(("https://", "http://")):
        try:
            return await _download_provider_media(
                kind=kind, artifact_uri=artifact_uri, destination=destination
            )
        except (httpx.HTTPError, OSError) as exc:
            raise ValidationAppError(
                f"PROVIDER_MEDIA_DOWNLOAD_FAILED: {type(exc).__name__}"
            ) from exc
    if isinstance(artifact_uri, bytes):

        async def chunks() -> AsyncIterator[bytes]:
            for start in range(0, len(artifact_uri), 64 * 1024):
                yield artifact_uri[start : start + 64 * 1024]
    elif isinstance(artifact_uri, str) and artifact_uri.startswith("data:") and "," in artifact_uri:
        import base64

        separator = artifact_uri.index(",")
        header = artifact_uri[:separator]
        encoded_start = separator + 1
        encoded_length = len(artifact_uri) - encoded_start
        if not header.endswith(";base64"):
            raise ValidationAppError("PROVIDER_MEDIA_INVALID: malformed data URI")
        content_type = header[5:].split(";", 1)[0].strip().lower()
        limit = (
            min(_MAX_PROVIDER_MEDIA_BYTES, _MAX_PROVIDER_IMAGE_BYTES)
            if kind in {"keyframe", "image"}
            else _MAX_PROVIDER_MEDIA_BYTES
        )
        if encoded_length > ((limit + 2) // 3) * 4:
            raise ValidationAppError("PROVIDER_MEDIA_INVALID: data URI is too large")

        async def chunks() -> AsyncIterator[bytes]:
            try:
                for start in range(encoded_start, len(artifact_uri), 64 * 1024):
                    part = artifact_uri[start : start + 64 * 1024]
                    if "=" in part and start + len(part) != len(artifact_uri):
                        raise ValueError("nonfinal padding")
                    yield base64.b64decode(part, validate=True)
            except (ValueError, TypeError) as exc:
                raise ValidationAppError("PROVIDER_MEDIA_INVALID: malformed data URI") from exc
    elif get_settings().app_env == "test" and (
        not artifact_uri or (isinstance(artifact_uri, str) and artifact_uri.startswith("fake://"))
    ):
        synthetic = True

        async def chunks() -> AsyncIterator[bytes]:
            yield f"{kind}-TESTFAKE:{remote}:{prompt}".encode()
    else:
        code = (
            "PROVIDER_MEDIA_INVALID"
            if isinstance(artifact_uri, str) and artifact_uri
            else "PROVIDER_MEDIA_MISSING"
        )
        raise ValidationAppError(f"{code}: expected HTTPS or validated data; refusing STUB media")
    if synthetic:
        return await materialize_stream(
            chunks(), destination=destination, max_bytes=_MAX_PROVIDER_MEDIA_BYTES
        )
    return await _materialize_provider_media(
        kind=kind, chunks=chunks(), destination=destination, content_type=content_type
    )


def _mime_for_node(node_type: str) -> tuple[str, str, str]:
    if node_type in {"keyframe", "identity_review", "prompt_compose", "prompt"}:
        return "image/png", "png", "image"
    if node_type in {"video", "video_review", "composite"}:
        return "video/mp4", "mp4", "video"
    if node_type in {"voice"}:
        return "audio/wav", "wav", "audio"
    if node_type in {"subtitle"}:
        return "application/x-subrip", "srt", "subtitle"
    if node_type in {"continuity_review"}:
        return "application/json", "json", "document"
    return "application/octet-stream", "bin", "document"
