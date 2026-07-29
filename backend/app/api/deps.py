"""Request-scoped FastAPI dependencies (auth session + CSRF)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User, Workspace
from app.access.service import AccessService
from app.config import Settings, get_settings
from app.shared.db import get_session, set_rls_context
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
    # Establish user RLS context early (workspace/project refined by route services).
    await set_rls_context(session, user_id=user_id)
    return await AccessService(session).get_user(user_id)


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_selected_workspace(
    user: CurrentUser,
    session: SessionDep,
    x_workspace_id: Annotated[UUID | None, Header(alias="X-Workspace-Id")] = None,
    query_workspace_id: Annotated[UUID | None, Query(alias="workspace_id")] = None,
) -> Workspace:
    """Apply the owned workspace selected for a project-scoped request.

    Browser fetches use ``X-Workspace-Id``. The query fallback exists only so
    native image/download navigations can carry the same explicit scope.
    """
    if (
        x_workspace_id is not None
        and query_workspace_id is not None
        and x_workspace_id != query_workspace_id
    ):
        raise ForbiddenError("workspace context mismatch")
    workspace_id = x_workspace_id or query_workspace_id
    if workspace_id is None:
        raise ForbiddenError("workspace context required")

    workspace = await AccessService(session).get_workspace_for_owner(
        workspace_id=workspace_id,
        user=user,
    )
    session.info["selected_workspace_id"] = workspace.id
    await set_rls_context(session, user_id=user.id, workspace_id=workspace.id)
    return workspace


SelectedWorkspace = Annotated[Workspace, Depends(require_selected_workspace)]


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
