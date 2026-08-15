"""Persistence operations for user-owned workspaces."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import InstanceBootstrapState, Project, User, Workspace


class AccessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_email(self, email: str) -> User | None:
        bind = self._session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            # The runtime role cannot enumerate users through FORCE RLS before
            # authentication establishes app.current_user_id.  A narrowly
            # scoped SECURITY DEFINER function exposes exactly one normalized
            # email lookup and only the fields required to verify credentials.
            result = await self._session.execute(
                select(User).from_statement(
                    text("SELECT * FROM app.auth_user_by_email(:email)")
                ),
                {"email": email},
            )
        else:
            result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        result = await self._session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def add_user(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        return user

    async def get_bootstrap_state(self) -> InstanceBootstrapState | None:
        return await self._session.get(InstanceBootstrapState, 1)

    async def set_bootstrap_owner(self, owner_user_id: UUID) -> None:
        self._session.add(
            InstanceBootstrapState(singleton_id=1, owner_user_id=owner_user_id)
        )
        await self._session.flush()

    async def add_workspace(self, workspace: Workspace) -> Workspace:
        self._session.add(workspace)
        await self._session.flush()
        return workspace

    async def get_workspace(self, workspace_id: UUID) -> Workspace | None:
        result = await self._session.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        return result.scalar_one_or_none()

    async def list_workspaces(self, *, owner_user_id: UUID) -> list[Workspace]:
        result = await self._session.execute(
            select(Workspace)
            .where(Workspace.owner_user_id == owner_user_id)
            .order_by(Workspace.created_at, Workspace.id)
        )
        return list(result.scalars().all())

    async def count_projects(self, *, workspace_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Project).where(Project.workspace_id == workspace_id)
        )
        return int(result.scalar_one())

    async def delete_workspace(self, workspace: Workspace) -> None:
        await self._session.delete(workspace)
        await self._session.flush()
