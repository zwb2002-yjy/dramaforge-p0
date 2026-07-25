"""Resolve organization BYOK credentials for live Provider adapters.

Credentials stay encrypted at rest and are decrypted only to construct an
in-memory request-scoped Settings copy. Missing organization credentials keep
the documented environment-key fallback for local development.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.security.byok_keyring import ByokKeyring, KeyringConfigurationError, parse_keyring
from app.security.credentials import has_credential, read_credential
from app.shared.errors import AppError


class OrganizationCredentialConfigurationError(AppError):
    """Raised without secret material when persisted BYOK cannot be read."""

    def __init__(self) -> None:
        super().__init__(
            code="ORGANIZATION_BYOK_UNAVAILABLE",
            message=(
                "organization BYOK credential is stored but its keyring is unavailable; "
                "restore retained key versions before retrying"
            ),
            status_code=422,
        )


def configured_byok_keyring(settings: Settings | None = None) -> ByokKeyring:
    """Return the configured keyring or raise a secret-free configuration error."""
    cfg = settings or get_settings()
    try:
        return parse_keyring(
            primary_version=cfg.byok_primary_key_version,
            encoded=cfg.byok_keyring,
            legacy_key=cfg.byok_fernet_key,
        )
    except KeyringConfigurationError as exc:
        raise OrganizationCredentialConfigurationError() from exc


async def settings_for_organization_provider(
    session: AsyncSession,
    *,
    organization_id: UUID,
    provider: str,
    settings: Settings | None = None,
) -> Settings:
    """Return a settings copy using stored BYOK when the organization has one."""
    cfg = settings or get_settings()
    if not await has_credential(
        session,
        organization_id=organization_id,
        provider=provider,
    ):
        return cfg

    credential = await read_credential(
        session,
        organization_id=organization_id,
        provider=provider,
        keyring=configured_byok_keyring(cfg),
    )
    if not credential:
        return cfg
    if provider == "text":
        return cfg.model_copy(
            update={"text_llm_enabled": True, "text_llm_api_key": credential}
        )
    if provider == "agnes":
        return cfg.model_copy(update={"agnes_enabled": True, "agnes_api_key": credential})
    raise ValueError(f"unsupported organization credential provider: {provider}")
