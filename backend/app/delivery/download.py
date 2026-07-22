"""Authorized export download tokens (membership-gated, no permanent public URLs)."""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.config import get_settings
from app.delivery.models import Export
from app.shared.errors import ForbiddenError, NotFoundError, ValidationAppError
from app.storage.minio_store import ObjectStore, get_object_store


@dataclass(frozen=True)
class DownloadGrant:
    export_id: UUID
    project_id: UUID
    object_key: str
    token: str
    expires_at: int


def _sign(payload: str) -> str:
    secret = get_settings().session_secret.encode()
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def mint_download_token(
    *,
    export_id: UUID,
    project_id: UUID,
    object_key: str,
    user_id: UUID,
    ttl_seconds: int = 300,
) -> DownloadGrant:
    expires_at = int(time.time()) + max(30, ttl_seconds)
    payload = f"{export_id}|{project_id}|{object_key}|{user_id}|{expires_at}"
    token = _sign(payload)
    return DownloadGrant(
        export_id=export_id,
        project_id=project_id,
        object_key=object_key,
        token=f"{expires_at}.{token}",
        expires_at=expires_at,
    )


def verify_download_token(
    *,
    token: str,
    export_id: UUID,
    project_id: UUID,
    object_key: str,
    user_id: UUID,
) -> None:
    try:
        exp_s, sig = token.split(".", 1)
        expires_at = int(exp_s)
    except Exception as exc:  # noqa: BLE001
        raise ForbiddenError("invalid download token") from exc
    if expires_at < int(time.time()):
        raise ForbiddenError("download token expired")
    payload = f"{export_id}|{project_id}|{object_key}|{user_id}|{expires_at}"
    expected = _sign(payload)
    if not hmac.compare_digest(expected, sig):
        raise ForbiddenError("invalid download token")


async def authorize_export_download(
    session: AsyncSession,
    *,
    export_id: UUID,
    actor: User,
    object_role: str = "timeline_json",
) -> DownloadGrant:
    """Member-only grant for one export object key."""
    exp = await session.get(Export, export_id)
    if exp is None:
        raise NotFoundError("export not found")
    await ProjectService(session).get_project_for_member(
        project_id=exp.project_id, actor=actor
    )
    manifest = exp.manifest or {}
    key_map = {
        "timeline_json": f"exports/{exp.project_id}/{exp.id}/timeline.json",
        "srt": f"exports/{exp.project_id}/{exp.id}/subtitles.srt",
        # package → zip with real media/; package_json keeps the manifest only
        "package": f"exports/{exp.project_id}/{exp.id}/package.zip",
        "package_json": f"exports/{exp.project_id}/{exp.id}/package.json",
        "package_zip": f"exports/{exp.project_id}/{exp.id}/package.zip",
        "mp4": manifest.get("mp4_object_key")
        or f"exports/{exp.project_id}/{exp.id}/program.mp4",
    }
    object_key = key_map.get(object_role)
    if not object_key or not isinstance(object_key, str):
        raise ValidationAppError(f"unknown object_role: {object_role}")
    return mint_download_token(
        export_id=exp.id,
        project_id=exp.project_id,
        object_key=object_key,
        user_id=actor.id,
    )


async def fetch_export_bytes(
    *,
    grant: DownloadGrant,
    store: ObjectStore | None = None,
) -> bytes:
    obj = store or get_object_store()
    try:
        return await obj.get_bytes(object_key=grant.object_key)
    except KeyError as exc:
        raise NotFoundError("export object missing") from exc
