"""One Range-capable byte response for private media downloads.

Public asset content and per-episode delivery both stream a private object with
the same semantics: full 200, a single repaired ``bytes=`` range as 206, and 416
for an unsatisfiable range. Keeping that in one place means the delivery path
cannot drift from the already-verified public path.
"""

from __future__ import annotations

from fastapi import Request, Response


def parse_range(header: str, size: int) -> tuple[int, int] | None:
    """Parse one ``bytes=`` range; ``None`` means it cannot be satisfied."""
    value = header.strip().lower()
    if not value.startswith("bytes=") or "," in value:
        return None
    spec = value[len("bytes=") :].strip()
    if "-" not in spec:
        return None
    raw_start, raw_end = spec.split("-", 1)
    try:
        if raw_start == "":
            length = int(raw_end)
            if length <= 0:
                return None
            start, end = max(size - length, 0), size - 1
        else:
            start = int(raw_start)
            end = int(raw_end) if raw_end else size - 1
    except ValueError:
        return None
    if start < 0 or start >= size or end < start:
        return None
    return start, min(end, size - 1)


async def content_response(
    request: Request,
    *,
    object_key: str,
    mime_type: str,
    byte_size: int,
    extra_headers: dict[str, str] | None = None,
) -> Response:
    from app.storage.minio_store import get_object_store

    store = get_object_store()
    headers = {
        "Accept-Ranges": "bytes",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
        **(extra_headers or {}),
    }
    range_header = request.headers.get("range")
    if range_header:
        parsed = parse_range(range_header, byte_size)
        if parsed is None:
            return Response(
                status_code=416,
                headers={**headers, "Content-Range": f"bytes */{byte_size}"},
            )
        start, end = parsed
        data = await store.get_range(object_key=object_key, offset=start, length=end - start + 1)
        return Response(
            content=data,
            status_code=206,
            media_type=mime_type,
            headers={
                **headers,
                "Content-Range": f"bytes {start}-{end}/{byte_size}",
                "Content-Length": str(len(data)),
            },
        )
    data = await store.get_bytes(object_key=object_key)
    return Response(
        content=data,
        media_type=mime_type,
        headers={**headers, "Content-Length": str(len(data))},
    )


__all__ = ["content_response", "parse_range"]
