"""SSE subscription route with Last-Event-ID resume."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser
from app.events.sse import default_sse_hub, format_sse

router = APIRouter(tags=["events"])


@router.get("/events/stream")
async def event_stream(
    request: Request,
    user: CurrentUser,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    _ = user  # auth required; project filter lands with full RLS context

    async def gen() -> AsyncIterator[str]:
        async for envelope in default_sse_hub.stream(last_event_id=last_event_id):
            if await request.is_disconnected():
                break
            yield format_sse(envelope)

    return StreamingResponse(gen(), media_type="text/event-stream")
