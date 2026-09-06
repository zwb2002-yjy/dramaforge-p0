"""Resolve workspace BYOK credentials for live provider adapters."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.providers.models import ProviderConnection
from app.security.byok_keyring import ByokKeyring, KeyringConfigurationError, parse_keyring
from app.security.credentials import (
    has_credential,
    read_credential,
    read_credential_by_id,
)
from app.shared.errors import AppError


class WorkspaceCredentialConfigurationError(AppError):
    """Raised without secret material when persisted BYOK cannot be read."""

    def __init__(self) -> None:
        super().__init__(
            code="WORKSPACE_BYOK_UNAVAILABLE",
            message=(
                "workspace BYOK credential revision is unavailable; "
                "restore the referenced credential and retained key versions before retrying"
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
    if provider == "minimax":
        return cfg.model_copy(update={"minimax_enabled": True, "minimax_api_key": credential})
    raise ValueError(f"unsupported workspace credential provider: {provider}")


async def runtime_connection_settings(
    session: AsyncSession,
    *,
    connection: ProviderConnection,
    settings: Settings | None = None,
) -> Settings:
    """Build runtime Settings from a ProviderConnection (BYOK credential slot +
    connection host), used by the unified Provider runtime. Mirrors the legacy
    ``settings_for_workspace_provider`` but keys off the connection's provider
    type + protocol profile instead of a hardcoded provider name."""
    from app.providers.registry import get_plugin

    cfg = settings or get_settings()
    plugin = get_plugin(connection.provider_type, connection.protocol_profile)
    credential = await read_credential_by_id(
        session,
        workspace_id=connection.workspace_id,
        credential_id=connection.credential_id,
        keyring=configured_byok_keyring(cfg),
    )
    if credential is None:
        # Do not fall back to the provider-key default or process environment:
        # a concrete connection must either resolve its named revision or fail
        # closed.
        raise WorkspaceCredentialConfigurationError()
    prefix = plugin.prefix
    return cfg.model_copy(
        update={
            f"{prefix}_enabled": True,
            f"{prefix}_api_key": credential,
            f"{prefix}_base_url": connection.base_url,
        }
    )
