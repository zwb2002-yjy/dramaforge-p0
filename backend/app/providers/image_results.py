"""Bounded synchronous Images results, normalized to PNG for existing Artifact storage."""

from __future__ import annotations

import base64
import binascii
from io import BytesIO
from typing import Any
from urllib.parse import urlsplit

import httpx
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_RESPONSE_BYTES = 24 * 1024 * 1024
IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}


async def bounded_response(
    client: httpx.AsyncClient, method: str, url: str, **kwargs: Any
) -> httpx.Response:
    kwargs["headers"] = {**kwargs.get("headers", {}), "Accept-Encoding": "identity"}
    async with client.stream(method, url, **kwargs) as response:
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise ValueError("compressed image responses are outside the bounded contract")
        raw_size = response.headers.get("content-length")
        if raw_size and (not raw_size.isdecimal() or int(raw_size) > MAX_RESPONSE_BYTES):
            raise ValueError("image response exceeds the protocol limit")
        body = bytearray()
        async for chunk in response.aiter_bytes(65536):
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("image response exceeds the protocol limit")
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=bytes(body),
            request=response.request,
        )


def normalized_png(data: bytes, content_type: str | None = None) -> bytes:
    mime = (content_type or "").split(";", 1)[0].lower().strip()
    if not data or len(data) > MAX_IMAGE_BYTES or (mime and mime not in IMAGE_MIMES):
        raise ValueError("image size or MIME does not match the protocol")
    try:
        with Image.open(BytesIO(data)) as source:
            expected = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
            if source.format not in expected or (mime and mime != expected[source.format]):
                raise ValueError("image content does not match its MIME")
            if source.size != (1024, 1024) or getattr(source, "n_frames", 1) != 1:
                raise ValueError("image dimensions or frame count do not match the frozen contract")
            source.load()
            output = BytesIO()
            source.convert("RGBA" if source.mode == "RGBA" else "RGB").save(output, format="PNG")
            result = output.getvalue()
            if len(result) > MAX_IMAGE_BYTES:
                raise ValueError("normalized image exceeds the media limit")
            return result
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("image cannot be decoded under the protocol") from exc


async def image_result(
    response: httpx.Response, *, origin: str, client: httpx.AsyncClient, headers: dict[str, str]
) -> bytes:
    mime = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
    if mime in IMAGE_MIMES:
        return normalized_png(response.content, mime)
    if mime != "application/json":
        raise ValueError("Images response MIME is unsupported")
    try:
        body = response.json()
    except ValueError as exc:
        raise ValueError("Images response is not JSON") from exc
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("Images response must contain exactly one result")
    row = rows[0]
    encoded, url = row.get("b64_json"), row.get("url")
    if bool(encoded) == bool(url):
        raise ValueError("Images result needs exactly one bytes or URL representation")
    if encoded:
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
            raise ValueError("encoded image exceeds the protocol limit")
        try:
            return normalized_png(base64.b64decode(encoded, validate=True))
        except (ValueError, binascii.Error) as exc:
            raise ValueError("encoded image does not match the protocol") from exc
    if not isinstance(url, str):
        raise ValueError("image URL is invalid")
    target, base = urlsplit(url), urlsplit(origin)
    try:
        default_ports = {"http": 80, "https": 443}
        same_origin = (
            target.scheme,
            target.hostname,
            target.port or default_ports.get(target.scheme),
        ) == (
            base.scheme,
            base.hostname,
            base.port or default_ports.get(base.scheme),
        )
    except ValueError as exc:
        raise ValueError("image URL port is invalid") from exc
    if not same_origin or target.username or target.password or target.fragment:
        raise ValueError("image URL must stay within the frozen connection origin")
    downloaded = await bounded_response(client, "GET", url, headers=headers)
    if downloaded.status_code != 200:
        raise ValueError("image download was not a direct successful response")
    return normalized_png(downloaded.content, downloaded.headers.get("content-type"))
