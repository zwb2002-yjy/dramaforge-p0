"""Access data access layer."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Organization, OrganizationMember, User
from app.shared.enums import MemberRole


class AccessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        result = await self._session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def add_user(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        return user

    async def add_organization(self, org: Organization) -> Organization:
        self._session.add(org)
        await self._session.flush()
        return org

    async def get_organization(self, org_id: UUID) -> Organization | None:
        result = await self._session.execute(
            select(Organization).where(Organization.id == org_id)
        )
        return result.scalar_one_or_none()

    async def add_membership(self, member: OrganizationMember) -> OrganizationMember:
        self._session.add(member)
        await self._session.flush()
        return member

    async def get_membership(
        self, *, organization_id: UUID, user_id: UUID
    ) -> OrganizationMember | None:
        result = await self._session.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_memberships(self, organization_id: UUID) -> list[OrganizationMember]:
        result = await self._session.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == organization_id
            )
        )
        return list(result.scalars().all())

    async def user_is_member(self, *, organization_id: UUID, user_id: UUID) -> bool:
        row = await self.get_membership(organization_id=organization_id, user_id=user_id)
        return row is not None

    async def create_org_with_owner(
        self, *, name: str, owner: User
    ) -> tuple[Organization, OrganizationMember]:
        org = Organization(name=name)
        await self.add_organization(org)
        member = OrganizationMember(
            organization_id=org.id,
            user_id=owner.id,
            role=MemberRole.OWNER.value,
        )
        await self.add_membership(member)
        return org, member
