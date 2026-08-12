"""Authentication and private workspace HTTP routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.access.schemas import (
    BootstrapStatusRead,
    CsrfRead,
    LoginRequest,
    RegisterRequest,
    UserRead,
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceUpdate,
)
from app.access.service import AccessService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, SettingsDep
from app.shared.security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    SESSION_MAX_AGE_SECONDS,
    issue_csrf_token,
    issue_session_token,
)

router = APIRouter(tags=["auth"])


def _set_session_cookie(response: Response, *, token: str, secure: bool) -> None:
    response.set_cookie(
        key=SESSION_COOKIE, value=token, httponly=True, samesite="lax", secure=secure,
        max_age=SESSION_MAX_AGE_SECONDS, path="/",
    )


def _set_csrf_cookie(response: Response, *, token: str, secure: bool) -> None:
    response.set_cookie(
        key=CSRF_COOKIE, value=token, httponly=False, samesite="lax", secure=secure,
        max_age=SESSION_MAX_AGE_SECONDS, path="/",
    )


@router.get("/auth/bootstrap-status", response_model=BootstrapStatusRead)
async def bootstrap_status(session: SessionDep, settings: SettingsDep) -> BootstrapStatusRead:
    owner_initialized, registration_available = await AccessService(
        session
    ).registration_status(public_registration_enabled=settings.public_registration_enabled)
    return BootstrapStatusRead(
        owner_initialized=owner_initialized,
        registration_available=registration_available,
        public_registration_enabled=settings.public_registration_enabled,
    )


@router.post("/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest, response: Response,
    session: SessionDep, settings: SettingsDep,
) -> UserRead:
    user = await AccessService(session).register(
        email=str(body.email),
        password=body.password,
        display_name=body.display_name,
        public_registration_enabled=settings.public_registration_enabled,
    )
    secure = settings.app_env == "production"
    _set_session_cookie(
        response,
        token=issue_session_token(
            user_id=user.id, secret=settings.session_secret,
        ),
        secure=secure,
    )
    _set_csrf_cookie(
        response,
        token=issue_csrf_token(secret=settings.session_secret),
        secure=secure,
    )
    return UserRead.model_validate(user)


@router.post("/auth/login", response_model=UserRead)
async def login(
    body: LoginRequest, response: Response,
    session: SessionDep, settings: SettingsDep,
) -> UserRead:
    user = await AccessService(session).authenticate(
        email=str(body.email), password=body.password,
    )
    secure = settings.app_env == "production"
    _set_session_cookie(
        response,
        token=issue_session_token(
            user_id=user.id, secret=settings.session_secret,
        ),
        secure=secure,
    )
    _set_csrf_cookie(
        response,
        token=issue_csrf_token(secret=settings.session_secret),
        secure=secure,
    )
    return UserRead.model_validate(user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout(response: Response) -> Response:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/auth/me", response_model=UserRead)
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.get("/auth/csrf", response_model=CsrfRead)
async def csrf_token(response: Response, settings: SettingsDep) -> CsrfRead:
    token = issue_csrf_token(secret=settings.session_secret)
    _set_csrf_cookie(response, token=token, secure=settings.app_env == "production")
    return CsrfRead(csrf_token=token)


@router.get("/workspaces", response_model=list[WorkspaceRead])
async def list_workspaces(user: CurrentUser, session: SessionDep) -> list[WorkspaceRead]:
    workspaces = await AccessService(session).list_workspaces(owner=user)
    return [WorkspaceRead.model_validate(workspace) for workspace in workspaces]


@router.post("/workspaces", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceCreate, user: CurrentUser,
    session: SessionDep, _: CsrfDep,
) -> WorkspaceRead:
    workspace = await AccessService(session).create_workspace(name=body.name, owner=user)
    return WorkspaceRead.model_validate(workspace)


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceRead)
async def get_workspace(
    workspace_id: UUID, user: CurrentUser, session: SessionDep,
) -> WorkspaceRead:
    workspace = await AccessService(session).get_workspace_for_owner(
        workspace_id=workspace_id, user=user,
    )
    return WorkspaceRead.model_validate(workspace)


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceRead)
async def rename_workspace(
    workspace_id: UUID, body: WorkspaceUpdate,
    user: CurrentUser, session: SessionDep, _: CsrfDep,
) -> WorkspaceRead:
    workspace = await AccessService(session).rename_workspace(
        workspace_id=workspace_id, name=body.name, actor=user,
    )
    return WorkspaceRead.model_validate(workspace)


@router.delete(
    "/workspaces/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_workspace(
    workspace_id: UUID, user: CurrentUser,
    session: SessionDep, _: CsrfDep,
) -> Response:
    await AccessService(session).delete_workspace(workspace_id=workspace_id, actor=user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
