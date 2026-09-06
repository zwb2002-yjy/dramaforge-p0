"""Unauthenticated, opaque-token media delivery for Provider HEAD/GET."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.api.deps import SessionDep
from app.providers.reference_delivery import (
    read_public_reference_bytes,
    resolve_public_reference,
)

router = APIRouter(tags=["provider-references"])


async def _provider_reference_response(
    token: str, request: Request, session: SessionDep
) -> Response:
    reference = await resolve_public_reference(session, token=token)
    data = await read_public_reference_bytes(reference)
    return Response(
        content=b"" if request.method == "HEAD" else data,
        media_type=reference.mime_type,
        headers={
            "Content-Length": str(len(data)),
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "X-Content-SHA256": reference.content_hash,
        },
    )


@router.get(
    "/provider-references/{token}",
    operation_id="provider_reference_get",
)
async def provider_reference_get(
    token: str, request: Request, session: SessionDep
) -> Response:
    return await _provider_reference_response(token, request, session)


@router.head(
    "/provider-references/{token}",
    operation_id="provider_reference_head",
)
async def provider_reference_head(
    token: str, request: Request, session: SessionDep
) -> Response:
    return await _provider_reference_response(token, request, session)
