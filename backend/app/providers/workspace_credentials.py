"""Resolve workspace BYOK credentials for live provider adapters."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.providers.models import ProviderConnection
from app.security.byok_keyring import ByokKeyring, KeyringConfigurationError, parse_keyring
from app.security.credentials import (
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


async def runtime_connection_settings(
    session: AsyncSession,
    *,
    connection: ProviderConnection,
    settings: Settings | None = None,
) -> Settings:
    """Resolve only the immutable credential revision named by a connection."""
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


async def runtime_text_gateway_settings(
    session: AsyncSession,
    *,
    connection: ProviderConnection,
    settings: Settings | None = None,
) -> Settings:
    """Resolve a workspace text gateway without exposing its stored key."""
    if (
        connection.provider_type != "litellm"
        or connection.protocol_profile != "openai_chat_v1"
    ):
        raise WorkspaceCredentialConfigurationError()
    cfg = settings or get_settings()
    credential = await read_credential_by_id(
        session,
        workspace_id=connection.workspace_id,
        credential_id=connection.credential_id,
        keyring=configured_byok_keyring(cfg),
    )
    if credential is None:
        raise WorkspaceCredentialConfigurationError()
    return cfg.model_copy(
        update={
            "litellm_gateway_url": connection.base_url,
            "litellm_api_key": credential,
        }
    )
