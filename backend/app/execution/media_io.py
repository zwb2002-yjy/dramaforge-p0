"""Provider media ingestion: pinned HTTPS, bounded validation and decoded metadata."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
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

logger = logging.getLogger(__name__)

_MAX_PROVIDER_MEDIA_BYTES = 512 * 1024 * 1024

# One dropped connection must not discard an already-paid generation, so a
# failed fetch is retried a bounded number of times before it becomes terminal.
_MEDIA_DOWNLOAD_ATTEMPTS = 3
_MEDIA_DOWNLOAD_RETRY_DELAYS: tuple[float, ...] = (1.0, 3.0)


_MAX_PROVIDER_IMAGE_BYTES = 20 * 1024 * 1024


_ALLOWED_PROVIDER_MEDIA_MIMES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "video/mp4",
        "video/quicktime",
        "video/webm",
        "audio/mpeg",
        "audio/wav",
        "audio/x-wav",
        "audio/mp4",
    }
)


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
    transport: httpx.AsyncBaseTransport | None = None,
) -> bytes:
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
) -> bytes:
    """One download attempt over an already validated public URL."""
    if transport is not None:
        async with (
            httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=20.0),
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client,
            client.stream("GET", value) as response,
        ):
            if response.is_redirect:
                raise ValidationAppError(
                    "PROVIDER_MEDIA_INVALID: provider media redirects are not allowed"
                )
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > _MAX_PROVIDER_MEDIA_BYTES:
                        raise ValidationAppError("PROVIDER_MEDIA_INVALID: response is too large")
                except ValueError as exc:
                    raise ValidationAppError(
                        "PROVIDER_MEDIA_INVALID: response Content-Length is invalid"
                    ) from exc
            body = bytearray()
            async for chunk in response.aiter_bytes(1024 * 1024):
                body.extend(chunk)
                if len(body) > _MAX_PROVIDER_MEDIA_BYTES:
                    raise ValidationAppError("PROVIDER_MEDIA_INVALID: response is too large")
            if content_length and int(content_length) != len(body):
                raise ValidationAppError(
                    "PROVIDER_MEDIA_INVALID: Content-Length does not match bytes"
                )
            return _validate_provider_media(
                kind=kind,
                data=bytes(body),
                content_type=response.headers.get("Content-Type"),
            )
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
    try:
        async with (
            httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=20.0),
                follow_redirects=False,
                trust_env=False,
                transport=base_transport,
            ) as client,
            client.stream("GET", value) as response,
        ):
            if response.is_redirect:
                raise ValidationAppError(
                    "PROVIDER_MEDIA_INVALID: provider media redirects are not allowed"
                )
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > _MAX_PROVIDER_MEDIA_BYTES:
                        raise ValidationAppError("PROVIDER_MEDIA_INVALID: response is too large")
                except ValueError as exc:
                    raise ValidationAppError(
                        "PROVIDER_MEDIA_INVALID: response Content-Length is invalid"
                    ) from exc
            body = bytearray()
            async for chunk in response.aiter_bytes(1024 * 1024):
                body.extend(chunk)
                if len(body) > _MAX_PROVIDER_MEDIA_BYTES:
                    raise ValidationAppError("PROVIDER_MEDIA_INVALID: response is too large")
            if content_length and int(content_length) != len(body):
                raise ValidationAppError(
                    "PROVIDER_MEDIA_INVALID: Content-Length does not match bytes"
                )
            return _validate_provider_media(
                kind=kind,
                data=bytes(body),
                content_type=response.headers.get("Content-Type"),
            )
    finally:
        await base_transport.aclose()


def _media_magic_matches(kind: str, data: bytes) -> bool:
    if kind in {"keyframe", "image"}:
        return (
            data.startswith(b"\x89PNG\r\n\x1a\n")
            or data.startswith(b"\xff\xd8\xff")
            or (len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP")
        )
    if kind in {"video", "video_review"}:
        return len(data) >= 12 and data[4:8] == b"ftyp"
    if kind in {"voice", "audio"}:
        return data.startswith((b"ID3", b"RIFF", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"))
    return bool(data)


def _validate_provider_media(*, kind: str, data: bytes, content_type: str | None) -> bytes:
    if not data or len(data) > _MAX_PROVIDER_MEDIA_BYTES:
        raise ValidationAppError(
            "PROVIDER_MEDIA_INVALID: response size is outside the allowed range"
        )
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized_type and normalized_type not in _ALLOWED_PROVIDER_MEDIA_MIMES:
        raise ValidationAppError("PROVIDER_MEDIA_INVALID: response MIME is not allowed")
    if not _media_magic_matches(kind, data):
        raise ValidationAppError("PROVIDER_MEDIA_INVALID: response bytes do not match media kind")
    if kind in {"keyframe", "image"} and len(data) > _MAX_PROVIDER_IMAGE_BYTES:
        raise ValidationAppError("PROVIDER_MEDIA_INVALID: image response is too large")
    return data


@dataclass(frozen=True)
class _MediaMetadata:
    width: int | None = None
    height: int | None = None
    duration_seconds: Decimal | None = None


def _inspect_media_metadata(*, kind: str, data: bytes) -> _MediaMetadata:
    """Decode deterministic media metadata before bytes enter object storage."""
    if kind in {"keyframe", "image"}:
        try:
            with Image.open(BytesIO(data)) as image:
                image.load()
                return _MediaMetadata(width=image.width, height=image.height)
        except (UnidentifiedImageError, OSError) as exc:
            if get_settings().app_env != "test":
                raise ValidationAppError("PROVIDER_MEDIA_INVALID: image cannot be decoded") from exc
            return _MediaMetadata()
    if kind not in {"video", "video_review", "composite"}:
        return _MediaMetadata()
    import cv2

    with tempfile.TemporaryDirectory(prefix="dramaforge-media-meta-") as temp_dir:
        path = Path(temp_dir) / "source.mp4"
        path.write_bytes(data)
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


async def _resolve_media_bytes(
    *,
    kind: str,
    remote: str,
    prompt: str,
    artifact_uri: object,
) -> bytes:
    """Load media bytes from URI. Never invent STUB success media on formal path."""
    from app.config import get_settings

    if isinstance(artifact_uri, bytes):
        return _validate_provider_media(kind=kind, data=artifact_uri, content_type=None)
    if isinstance(artifact_uri, str) and artifact_uri:
        if artifact_uri.startswith("data:") and "," in artifact_uri:
            import base64

            header, b64 = artifact_uri.split(",", 1)
            max_encoded_chars = ((_MAX_PROVIDER_MEDIA_BYTES + 2) // 3) * 4
            if len(b64) > max_encoded_chars:
                raise ValidationAppError("PROVIDER_MEDIA_INVALID: data URI is too large")
            try:
                data = base64.b64decode(b64, validate=True)
            except (ValueError, TypeError) as exc:
                raise ValidationAppError("PROVIDER_MEDIA_INVALID: malformed data URI") from exc
            mime = header[5:].split(";", 1)[0].strip().lower()
            return _validate_provider_media(kind=kind, data=data, content_type=mime)
        if artifact_uri.startswith("http://") or artifact_uri.startswith("https://"):
            try:
                return await _download_provider_media(kind=kind, artifact_uri=artifact_uri)
            except (httpx.HTTPError, OSError) as exc:
                raise ValidationAppError(
                    f"PROVIDER_MEDIA_DOWNLOAD_FAILED: {type(exc).__name__}"
                ) from exc
        if artifact_uri.startswith("fake://") and get_settings().app_env == "test":
            # Explicit test-only fake URI → synthetic bytes for contract tests
            return f"{kind}-TESTFAKE:{remote}:{prompt}".encode()
        raise ValidationAppError(
            "PROVIDER_MEDIA_INVALID: unsupported artifact URI; expected HTTPS or validated data"
        )
    if get_settings().app_env == "test":
        # Test adapters without blobs: deterministic bytes for unit tests only
        return f"{kind}-TESTFAKE:{remote}:{prompt}".encode()
    raise ValidationAppError(
        f"PROVIDER_MEDIA_MISSING: adapter succeeded but no artifact_uri bytes "
        f"(kind={kind} remote={remote}). Refusing STUB media on formal path."
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
