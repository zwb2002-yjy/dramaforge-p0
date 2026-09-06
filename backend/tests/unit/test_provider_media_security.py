"""Security and media validation tests for provider result downloads."""

from __future__ import annotations

import base64

import httpx
import pytest
from app.execution import product_path
from app.execution.product_path import (
    _download_provider_media,
    _resolve_media_bytes,
    _validate_public_media_url,
)
from app.shared.errors import ValidationAppError


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

    monkeypatch.setattr(product_path.socket, "getaddrinfo", private_resolution)
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

    monkeypatch.setattr(product_path.socket, "getaddrinfo", public_resolution)
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
    ],
)
async def test_provider_media_download_rejects_bad_mime_or_magic(
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
        )


@pytest.mark.asyncio
async def test_provider_media_download_accepts_valid_png_and_mp4() -> None:
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
    )
    video = await _download_provider_media(
        kind="video",
        artifact_uri="https://93.184.216.34/video",
        transport=httpx.MockTransport(video_handler),
    )
    assert image.startswith(b"\x89PNG")
    assert video[4:8] == b"ftyp"


@pytest.mark.asyncio
async def test_resolve_media_bytes_accepts_valid_data_uri_and_rejects_malformed_base64() -> None:
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\nvalid-image").decode("ascii")
    valid = await _resolve_media_bytes(
        kind="image",
        remote="remote-image",
        prompt="ignored",
        artifact_uri=f"data:image/png;base64,{encoded}",
    )
    assert valid.startswith(b"\x89PNG")

    with pytest.raises(ValidationAppError, match="malformed data URI"):
        await _resolve_media_bytes(
            kind="image",
            remote="remote-image",
            prompt="ignored",
            artifact_uri="data:image/png;base64,not-valid!!!",
        )


@pytest.mark.asyncio
async def test_resolve_media_bytes_bounds_encoded_data_before_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(product_path, "_MAX_PROVIDER_MEDIA_BYTES", 6)
    oversized = base64.b64encode(b"0123456789").decode("ascii")
    with pytest.raises(ValidationAppError, match="data URI is too large"):
        await _resolve_media_bytes(
            kind="image",
            remote="remote-image",
            prompt="ignored",
            artifact_uri=f"data:image/png;base64,{oversized}",
        )
