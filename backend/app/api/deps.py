"""Request-scoped FastAPI dependencies (auth session + CSRF)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.service import AccessService
from app.config import Settings, get_settings
from app.shared.db import get_session
from app.shared.errors import ForbiddenError, UnauthorizedError
from app.shared.security import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    parse_session_token,
    verify_csrf_token,
)


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    dramaforge_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User:
    if not dramaforge_session:
        raise UnauthorizedError("authentication required")
    try:
        user_id: UUID = parse_session_token(dramaforge_session, secret=settings.session_secret)
    except ValueError as exc:
        raise UnauthorizedError("invalid session") from exc
    return await AccessService(session).get_user(user_id)


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_csrf(
    settings: SettingsDep,
    request: Request,
    dramaforge_csrf: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
    x_csrf_token: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
) -> None:
    """Reject state-changing requests without a valid double-submit CSRF pair."""
    if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return
    if not verify_csrf_token(
        cookie_token=dramaforge_csrf,
        header_token=x_csrf_token,
        secret=settings.session_secret,
    ):
        raise ForbiddenError("CSRF validation failed")


CsrfDep = Annotated[None, Depends(require_csrf)]


async def access_service(session: SessionDep) -> AsyncGenerator[AccessService, None]:
    yield AccessService(session)
