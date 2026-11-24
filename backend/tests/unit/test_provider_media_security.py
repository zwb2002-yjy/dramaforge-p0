"""Security and media validation tests for provider result downloads."""

from __future__ import annotations

import asyncio
import base64
from uuid import uuid4

import httpx
import pytest
from app.execution import media_io
from app.execution.media_io import (
    _download_provider_media,
    _resolve_media_file,
    _validate_public_media_url,
)
from app.shared.errors import ValidationAppError


@pytest.mark.parametrize("failure", [None, "oversize", "disconnect", "cancel", "encoded"])
async def test_chunked_download_is_bounded_closed_and_never_keeps_partial_files(
    tmp_path,
    monkeypatch,
    failure,
):
    monkeypatch.setattr(media_io, "_MAX_PROVIDER_MEDIA_BYTES", 100000)
    monkeypatch.setattr(media_io, "_MEDIA_DOWNLOAD_ATTEMPTS", 1)
    reached, closed = asyncio.Event(), asyncio.Event()
    reads = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            reads.append(1)
            yield b"\x00\x00\x00\x18ftypmp42" + b"a" * (65536 - 12)
            reached.set()
            if failure == "cancel":
                await asyncio.Event().wait()
            if failure == "disconnect":
                raise httpx.ReadError("controlled disconnect")
            if failure == "oversize":
                for _ in range(100):
                    reads.append(1)
                    yield b"a" * 65536

        async def aclose(self):
            closed.set()

    async def handler(request):
        assert request.headers["Accept-Encoding"] == "identity"
        headers = {"Content-Type": "video/mp4"}
        if failure == "encoded":
            headers["Content-Encoding"] = "gzip"
        return httpx.Response(200, headers=headers, stream=Stream())

    target = tmp_path / "result.mp4"
    operation = _download_provider_media(
        kind="video",
        artifact_uri="https://93.184.216.34/result",
        destination=target,
        transport=httpx.MockTransport(handler),
    )
    if failure == "cancel":
        task = asyncio.create_task(operation)
        await asyncio.wait_for(reached.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif failure:
        with pytest.raises((ValidationAppError, httpx.TransportError)):
            await operation
    else:
        result = await operation
        assert result.byte_size == 65536 and target.stat().st_size == 65536
    assert closed.is_set()
    assert len(reads) <= 2, "oversize transfer must stop immediately"
    assert target.exists() == (failure is None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://93.184.216.34/result.png",
        "https://user:password@93.184.216.34/result.png",
        "https://93.184.216.34/result.png#fragment",
        "https://93.184.216.34:bad/result.png",
        "https://127.0.0.1/result.png",
        "https://10.0.0.1/result.png",
        "https://169.254.169.254/latest/result.png",
        "https://192.0.2.1/result.png",
        "https://[::1]/result.png",
    ],
)
async def test_provider_media_url_rejects_non_public_or_ambiguous_urls(url: str) -> None:
    with pytest.raises(ValidationAppError, match="PROVIDER_MEDIA_URL_INVALID"):
        await _validate_public_media_url(url)


@pytest.mark.asyncio
async def test_provider_media_url_rejects_dns_that_resolves_to_private_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def private_resolution(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [(0, 0, 0, "", ("10.0.0.4", 443))]

    monkeypatch.setattr(media_io.socket, "getaddrinfo", private_resolution)
    with pytest.raises(ValidationAppError, match="not public"):
        await _validate_public_media_url("https://provider.example/result.png")


@pytest.mark.asyncio
async def test_provider_media_url_pins_all_public_dns_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def public_resolution(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [
            (0, 0, 0, "", ("93.184.216.34", 443)),
            (0, 0, 0, "", ("151.101.1.69", 443)),
        ]

    monkeypatch.setattr(media_io.socket, "getaddrinfo", public_resolution)
    value, addresses = await _validate_public_media_url("https://provider.example/result.png")
    assert value == "https://provider.example/result.png"
    assert addresses == {"93.184.216.34", "151.101.1.69"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "content_type", "body"),
    [
        ("image", "image/png", b"not-a-png"),
        ("image", "text/plain", b"\x89PNG\r\n\x1a\nbytes"),
        ("video", "video/mp4", b"not-an-mp4"),
        ("image", "video/mp4", b"\x89PNG\r\n\x1a\nbytes"),
        ("image", "image/jpeg", b"\x89PNG\r\n\x1a\nbytes"),
        ("voice", "audio/wav", b"RIFF1234WEBPbytes"),
    ],
)
async def test_provider_media_download_rejects_bad_mime_or_magic(
    tmp_path,
    kind: str,
    content_type: str,
    body: bytes,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": content_type}, content=body)

    with pytest.raises(ValidationAppError, match="PROVIDER_MEDIA_INVALID"):
        await _download_provider_media(
            kind=kind,
            artifact_uri="https://93.184.216.34/result",
            transport=httpx.MockTransport(handler),
            destination=tmp_path / f"media-{uuid4().hex}",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {"Location": "https://93.184.216.34/other"},
        {"Content-Length": str(512 * 1024 * 1024 + 1)},
        {"Content-Length": "not-a-number"},
    ],
)
async def test_provider_media_download_rejects_redirect_and_invalid_lengths(
    tmp_path,
    headers: dict[str, str],
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        status = 302 if "Location" in headers else 200
        return httpx.Response(status, headers=headers, content=b"\x89PNG\r\n\x1a\nbytes")

    with pytest.raises(ValidationAppError, match="PROVIDER_MEDIA_INVALID"):
        await _download_provider_media(
            kind="image",
            artifact_uri="https://93.184.216.34/result",
            transport=httpx.MockTransport(handler),
            destination=tmp_path / f"media-{uuid4().hex}",
        )


@pytest.mark.asyncio
async def test_provider_media_download_accepts_valid_png_and_mp4(
    tmp_path,
) -> None:
    async def image_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "image/png"},
            content=b"\x89PNG\r\n\x1a\nvalid-image",
        )

    async def video_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "video/mp4"},
            content=b"\x00\x00\x00\x18ftypmp42valid-video",
        )

    image = await _download_provider_media(
        kind="image",
        artifact_uri="https://93.184.216.34/image",
        transport=httpx.MockTransport(image_handler),
        destination=tmp_path / f"media-{uuid4().hex}",
    )
    video = await _download_provider_media(
        kind="video",
        artifact_uri="https://93.184.216.34/video",
        transport=httpx.MockTransport(video_handler),
        destination=tmp_path / f"media-{uuid4().hex}",
    )
    assert image.path.read_bytes().startswith(b"\x89PNG")
    assert video.path.read_bytes()[4:8] == b"ftyp"


@pytest.mark.asyncio
async def test_resolve_media_file_accepts_valid_data_uri_and_rejects_malformed_base64(
    tmp_path,
) -> None:
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\nvalid-image").decode("ascii")
    valid = await _resolve_media_file(
        kind="image",
        remote="remote-image",
        prompt="ignored",
        artifact_uri=f"data:image/png;base64,{encoded}",
        destination=tmp_path / f"media-{uuid4().hex}",
    )
    assert valid.path.read_bytes().startswith(b"\x89PNG")

    with pytest.raises(ValidationAppError, match="malformed data URI"):
        await _resolve_media_file(
            kind="image",
            remote="remote-image",
            prompt="ignored",
            artifact_uri="data:image/png;base64,not-valid!!!",
            destination=tmp_path / f"media-{uuid4().hex}",
        )


@pytest.mark.asyncio
async def test_resolve_media_file_bounds_encoded_data_before_decode(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(media_io, "_MAX_PROVIDER_MEDIA_BYTES", 6)
    oversized = base64.b64encode(b"0123456789").decode("ascii")
    with pytest.raises(ValidationAppError, match="data URI is too large"):
        await _resolve_media_file(
            kind="image",
            remote="remote-image",
            prompt="ignored",
            artifact_uri=f"data:image/png;base64,{oversized}",
            destination=tmp_path / f"media-{uuid4().hex}",
        )


@pytest.mark.asyncio
async def test_download_rejects_truncated_content_length(
    tmp_path,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "image/png", "Content-Length": "100"},
            content=b"\x89PNG\r\n\x1a\n",
        )

    with pytest.raises(ValidationAppError, match="Content-Length"):
        await _download_provider_media(
            kind="keyframe",
            artifact_uri="https://93.184.216.34/result.png",
            transport=httpx.MockTransport(handler),
            destination=tmp_path / f"media-{uuid4().hex}",
        )


@pytest.mark.asyncio
async def test_download_recovers_from_a_transient_transport_failure(
    tmp_path,
) -> None:
    """One dropped connection must not destroy an already-paid generation.

    The remote task has already succeeded by the time its bytes are fetched, so
    a transient transport error here is recoverable by fetching again.
    """
    calls = {"count": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.RemoteProtocolError("connection dropped mid-response")
        return httpx.Response(
            200,
            headers={"Content-Type": "video/mp4"},
            content=b"\x00\x00\x00\x18ftypmp42recovered-video",
        )

    video = await _download_provider_media(
        kind="video",
        artifact_uri="https://93.184.216.34/result.mp4",
        transport=httpx.MockTransport(handler),
        destination=tmp_path / f"media-{uuid4().hex}",
    )
    assert calls["count"] == 2
    assert video.path.read_bytes()[4:8] == b"ftyp"


@pytest.mark.asyncio
async def test_download_gives_up_after_bounded_attempts(
    tmp_path,
) -> None:
    calls = {"count": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.RemoteProtocolError("connection dropped mid-response")

    with pytest.raises(httpx.TransportError):
        await _download_provider_media(
            kind="video",
            artifact_uri="https://93.184.216.34/result.mp4",
            transport=httpx.MockTransport(handler),
            destination=tmp_path / f"media-{uuid4().hex}",
        )
    assert calls["count"] == 3, "retries stay bounded"
