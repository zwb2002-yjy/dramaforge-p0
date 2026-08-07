"""Resolve workspace BYOK credentials for live provider adapters."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.security.byok_keyring import ByokKeyring, KeyringConfigurationError, parse_keyring
from app.security.credentials import has_credential, read_credential
from app.shared.errors import AppError


class WorkspaceCredentialConfigurationError(AppError):
    """Raised without secret material when persisted BYOK cannot be read."""

    def __init__(self) -> None:
        super().__init__(
            code="WORKSPACE_BYOK_UNAVAILABLE",
            message=(
                "workspace BYOK credential is stored but its keyring is unavailable; "
                "restore retained key versions before retrying"
            ),
            status_code=422,
        )


def configured_byok_keyring(settings: Settings | None = None) -> ByokKeyring:
    cfg = settings or get_settings()
    try:
        return parse_keyring(
            primary_version=cfg.byok_primary_key_version,
            encoded=cfg.byok_keyring,
            legacy_key=cfg.byok_fernet_key,
        )
    except KeyringConfigurationError as exc:
        raise WorkspaceCredentialConfigurationError() from exc


async def settings_for_workspace_provider(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider: str,
    settings: Settings | None = None,
) -> Settings:
    cfg = settings or get_settings()
    if not await has_credential(session, workspace_id=workspace_id, provider=provider):
        return cfg
    credential = await read_credential(
        session,
        workspace_id=workspace_id,
        provider=provider,
        keyring=configured_byok_keyring(cfg),
    )
    if credential is None:
        return cfg
    if provider == "text":
        return cfg.model_copy(update={"text_llm_enabled": True, "text_llm_api_key": credential})
    if provider == "agnes":
        return cfg.model_copy(update={"agnes_enabled": True, "agnes_api_key": credential})
    if provider == "volcengine":
        return cfg.model_copy(
            update={"volcengine_enabled": True, "volcengine_api_key": credential}
        )
    raise ValueError(f"unsupported workspace credential provider: {provider}")
