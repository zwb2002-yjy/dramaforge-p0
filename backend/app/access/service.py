"""Access use cases for private workspaces."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User, Workspace
from app.access.repository import AccessRepository
from app.shared.db import set_rls_context
from app.shared.errors import ForbiddenError, NotFoundError, UnauthorizedError, ValidationAppError
from app.shared.security import hash_password, verify_password

DEFAULT_WORKSPACE_NAME = "我的创作空间"


class AccessService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = AccessRepository(session)

    async def register(self, *, email: str, password: str, display_name: str) -> User:
        if await self._repo.get_user_by_email(email.lower()):
            raise ValidationAppError("email already registered")
        user = await self._repo.add_user(
            User(
                email=email.lower(),
                display_name=display_name,
                password_hash=hash_password(password),
                is_active=True,
            )
        )
        await set_rls_context(self._session, user_id=user.id)
        await self._repo.add_workspace(
            Workspace(owner_user_id=user.id, name=DEFAULT_WORKSPACE_NAME)
        )
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def authenticate(self, *, email: str, password: str) -> User:
        user = await self._repo.get_user_by_email(email.lower())
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise UnauthorizedError("invalid credentials")
        return user

    async def get_user(self, user_id: UUID) -> User:
        user = await self._repo.get_user_by_id(user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("session user not found")
        return user

    async def create_workspace(self, *, name: str, owner: User) -> Workspace:
        workspace = await self._repo.add_workspace(
            Workspace(owner_user_id=owner.id, name=name)
        )
        await self._session.commit()
        await self._session.refresh(workspace)
        return workspace

    async def list_workspaces(self, *, owner: User) -> list[Workspace]:
        return await self._repo.list_workspaces(owner_user_id=owner.id)

    async def get_workspace_for_owner(
        self, *, workspace_id: UUID, user: User
    ) -> Workspace:
        workspace = await self._repo.get_workspace(workspace_id)
        if workspace is None:
            raise NotFoundError("workspace not found")
        if workspace.owner_user_id != user.id:
            raise ForbiddenError("workspace belongs to another user")
        return workspace

    async def rename_workspace(
        self, *, workspace_id: UUID, name: str, actor: User
    ) -> Workspace:
        workspace = await self.get_workspace_for_owner(
            workspace_id=workspace_id, user=actor
        )
        workspace.name = name
        await self._session.commit()
        await self._session.refresh(workspace)
        return workspace

    async def delete_workspace(self, *, workspace_id: UUID, actor: User) -> None:
        workspace = await self.get_workspace_for_owner(
            workspace_id=workspace_id, user=actor
        )
        if await self._repo.count_projects(workspace_id=workspace_id):
            raise ValidationAppError("workspace must be empty before deletion")
        await self._repo.delete_workspace(workspace)
        await self._session.commit()
