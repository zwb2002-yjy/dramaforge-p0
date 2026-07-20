"""Auth and access HTTP routes (S1.1)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.access.schemas import (
    CsrfRead,
    LoginRequest,
    MembershipCreate,
    MembershipRead,
    OrganizationCreate,
    OrganizationRead,
    RegisterRequest,
    UserRead,
)
from app.access.service import AccessService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, SettingsDep
from app.shared.enums import MemberRole
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
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=SESSION_MAX_AGE_SECONDS,
        path="/",
    )


def _set_csrf_cookie(response: Response, *, token: str, secure: bool) -> None:
    response.set_cookie(
        key=CSRF_COOKIE,
        value=token,
        httponly=False,
        samesite="lax",
        secure=secure,
        max_age=SESSION_MAX_AGE_SECONDS,
        path="/",
    )


@router.post("/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> UserRead:
    service = AccessService(session)
    user = await service.register(
        email=str(body.email),
        password=body.password,
        display_name=body.display_name,
    )
    secure = settings.app_env == "production"
    _set_session_cookie(
        response,
        token=issue_session_token(user_id=user.id, secret=settings.session_secret),
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
    body: LoginRequest,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> UserRead:
    service = AccessService(session)
    user = await service.authenticate(email=str(body.email), password=body.password)
    secure = settings.app_env == "production"
    _set_session_cookie(
        response,
        token=issue_session_token(user_id=user.id, secret=settings.session_secret),
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
    _set_csrf_cookie(
        response,
        token=token,
        secure=settings.app_env == "production",
    )
    return CsrfRead(csrf_token=token)


@router.post(
    "/organizations",
    response_model=OrganizationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization(
    body: OrganizationCreate,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> OrganizationRead:
    org = await AccessService(session).create_organization(name=body.name, owner=user)
    return OrganizationRead.model_validate(org)


@router.get("/organizations/{organization_id}", response_model=OrganizationRead)
async def get_organization(
    organization_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> OrganizationRead:
    org = await AccessService(session).get_organization_for_member(
        org_id=organization_id, user=user
    )
    return OrganizationRead.model_validate(org)


@router.post(
    "/organizations/{organization_id}/members",
    response_model=MembershipRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    organization_id: UUID,
    body: MembershipCreate,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> MembershipRead:
    member = await AccessService(session).add_member(
        org_id=organization_id,
        actor=user,
        user_id=body.user_id,
        role=body.role,
    )
    return MembershipRead(
        organization_id=member.organization_id,
        user_id=member.user_id,
        role=MemberRole(member.role),
        created_at=member.created_at,
    )


@router.get(
    "/organizations/{organization_id}/members",
    response_model=list[MembershipRead],
)
async def list_members(
    organization_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[MembershipRead]:
    rows = await AccessService(session).list_members(org_id=organization_id, actor=user)
    return [
        MembershipRead(
            organization_id=m.organization_id,
            user_id=m.user_id,
            role=MemberRole(m.role),
            created_at=m.created_at,
        )
        for m in rows
    ]
