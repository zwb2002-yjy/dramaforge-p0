"""Access application service (transactional use cases)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Organization, OrganizationMember, User
from app.access.repository import AccessRepository
from app.shared.enums import MemberRole
from app.shared.errors import ForbiddenError, NotFoundError, UnauthorizedError, ValidationAppError
from app.shared.security import hash_password, verify_password


class AccessService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = AccessRepository(session)

    async def register(
        self, *, email: str, password: str, display_name: str
    ) -> User:
        existing = await self._repo.get_user_by_email(email.lower())
        if existing is not None:
            raise ValidationAppError("email already registered")
        user = User(
            email=email.lower(),
            display_name=display_name,
            password_hash=hash_password(password),
            is_active=True,
        )
        await self._repo.add_user(user)
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def authenticate(self, *, email: str, password: str) -> User:
        user = await self._repo.get_user_by_email(email.lower())
        if user is None or not user.is_active:
            raise UnauthorizedError("invalid credentials")
        if not verify_password(password, user.password_hash):
            raise UnauthorizedError("invalid credentials")
        return user

    async def get_user(self, user_id: UUID) -> User:
        user = await self._repo.get_user_by_id(user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("session user not found")
        return user

    async def create_organization(self, *, name: str, owner: User) -> Organization:
        org, _member = await self._repo.create_org_with_owner(name=name, owner=owner)
        await self._session.commit()
        await self._session.refresh(org)
        return org

    async def get_organization_for_member(
        self, *, org_id: UUID, user: User
    ) -> Organization:
        org = await self._repo.get_organization(org_id)
        if org is None:
            raise NotFoundError("organization not found")
        if not await self._repo.user_is_member(organization_id=org_id, user_id=user.id):
            raise ForbiddenError("not a member of this organization")
        return org

    async def require_organization_role(
        self,
        *,
        org_id: UUID,
        actor: User,
        allowed: set[MemberRole] | frozenset[MemberRole],
        action: str,
    ) -> Organization:
        org = await self.get_organization_for_member(org_id=org_id, user=actor)
        membership = await self._repo.get_membership(
            organization_id=org_id,
            user_id=actor.id,
        )
        assert membership is not None
        role = MemberRole(str(membership.role))
        if role not in allowed:
            raise ForbiddenError(
                f"role '{role.value}' cannot {action}; requires one of "
                f"{sorted(item.value for item in allowed)}"
            )
        return org

    async def add_member(
        self,
        *,
        org_id: UUID,
        actor: User,
        user_id: UUID,
        role: MemberRole,
    ) -> OrganizationMember:
        await self.get_organization_for_member(org_id=org_id, user=actor)
        actor_membership = await self._repo.get_membership(
            organization_id=org_id, user_id=actor.id
        )
        assert actor_membership is not None
        if actor_membership.role not in {
            MemberRole.OWNER.value,
            MemberRole.ADMIN.value,
        }:
            raise ForbiddenError("only owner/admin can add members")
        target = await self._repo.get_user_by_id(user_id)
        if target is None:
            raise NotFoundError("user not found")
        existing = await self._repo.get_membership(
            organization_id=org_id, user_id=user_id
        )
        if existing is not None:
            raise ValidationAppError("user already a member")
        member = OrganizationMember(
            organization_id=org_id,
            user_id=user_id,
            role=role.value,
        )
        await self._repo.add_membership(member)
        await self._session.commit()
        await self._session.refresh(member)
        return member

    async def list_members(
        self, *, org_id: UUID, actor: User
    ) -> list[OrganizationMember]:
        await self.get_organization_for_member(org_id=org_id, user=actor)
        return await self._repo.list_memberships(org_id)
