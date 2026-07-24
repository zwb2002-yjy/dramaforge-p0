"""Organization-scoped BYOK management without credential readback."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field, SecretStr

from app.access.service import AccessService
from app.api.deps import CsrfDep, CurrentUser, SessionDep
from app.config import get_settings
from app.security.byok_keyring import ByokKeyring, KeyringConfigurationError, parse_keyring
from app.security.credentials import has_credential, store_credential
from app.shared.enums import MemberRole
from app.shared.errors import ValidationAppError

router = APIRouter(tags=["organization-credentials"])

_PROVIDERS = frozenset({"text", "agnes"})
_CREDENTIAL_MANAGERS = frozenset({MemberRole.OWNER, MemberRole.ADMIN})


class OrganizationCredentialWrite(BaseModel):
    provider: str = Field(pattern="^(text|agnes)$")
    api_key: SecretStr = Field(min_length=1, max_length=4096)


class OrganizationCredentialRead(BaseModel):
    provider: str
    configured: bool
    key_version: str | None = None


def _keyring() -> ByokKeyring:
    settings = get_settings()
    try:
        return parse_keyring(
            primary_version=settings.byok_primary_key_version,
            encoded=settings.byok_keyring,
            legacy_key=settings.byok_fernet_key,
        )
    except KeyringConfigurationError as exc:
        raise ValidationAppError(
            "organization BYOK storage is not configured",
            details={"code": "BYOK_KEYRING_NOT_CONFIGURED"},
        ) from exc


@router.put(
    "/organizations/{organization_id}/provider-credentials",
    response_model=OrganizationCredentialRead,
)
async def put_organization_provider_credential(
    organization_id: UUID,
    body: OrganizationCredentialWrite,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> OrganizationCredentialRead:
    provider = body.provider.strip()
    if provider not in _PROVIDERS:
        raise ValidationAppError("unsupported organization credential provider")
    await AccessService(session).require_organization_role(
        org_id=organization_id,
        actor=user,
        allowed=_CREDENTIAL_MANAGERS,
        action="manage organization provider credentials",
    )
    record = await store_credential(
        session,
        organization_id=organization_id,
        provider=provider,
        plaintext=body.api_key.get_secret_value().strip(),
        keyring=_keyring(),
    )
    await session.commit()
    return OrganizationCredentialRead(
        provider=provider,
        configured=True,
        key_version=record.key_version,
    )


@router.get(
    "/organizations/{organization_id}/provider-credentials/{provider}",
    response_model=OrganizationCredentialRead,
)
async def get_organization_provider_credential_status(
    organization_id: UUID,
    provider: str,
    user: CurrentUser,
    session: SessionDep,
) -> OrganizationCredentialRead:
    provider = provider.strip()
    if provider not in _PROVIDERS:
        raise ValidationAppError("unsupported organization credential provider")
    await AccessService(session).require_organization_role(
        org_id=organization_id,
        actor=user,
        allowed=_CREDENTIAL_MANAGERS,
        action="view organization provider credential status",
    )
    return OrganizationCredentialRead(
        provider=provider,
        configured=await has_credential(
            session,
            organization_id=organization_id,
            provider=provider,
        ),
    )
