"""Workspace-scoped BYOK management without credential readback."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field, SecretStr

from app.api.deps import CsrfDep, SelectedWorkspace, SessionDep
from app.config import get_settings
from app.security.byok_keyring import ByokKeyring, KeyringConfigurationError, parse_keyring
from app.security.credentials import has_credential, store_credential
from app.shared.errors import NotFoundError, ValidationAppError

router = APIRouter(tags=["workspace-credentials"])

_PROVIDERS = frozenset({"text", "agnes"})

class WorkspaceCredentialWrite(BaseModel):
    provider: str = Field(pattern="^(text|agnes)$")
    api_key: SecretStr = Field(min_length=1, max_length=4096)


class WorkspaceCredentialRead(BaseModel):
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
            "workspace BYOK storage is not configured",
            details={"code": "BYOK_KEYRING_NOT_CONFIGURED"},
        ) from exc


@router.put(
    "/workspaces/{workspace_id}/provider-credentials",
    response_model=WorkspaceCredentialRead,
)
async def put_workspace_provider_credential(
    workspace_id: UUID,
    body: WorkspaceCredentialWrite,
    workspace: SelectedWorkspace,
    session: SessionDep,
    _: CsrfDep,
) -> WorkspaceCredentialRead:
    provider = body.provider.strip()
    if provider not in _PROVIDERS:
        raise ValidationAppError("unsupported workspace credential provider")
    if workspace_id != workspace.id:
        raise NotFoundError("workspace not found")
    record = await store_credential(
        session,
        workspace_id=workspace_id,
        provider=provider,
        plaintext=body.api_key.get_secret_value().strip(),
        keyring=_keyring(),
    )
    await session.commit()
    return WorkspaceCredentialRead(
        provider=provider,
        configured=True,
        key_version=record.key_version,
    )


@router.get(
    "/workspaces/{workspace_id}/provider-credentials/{provider}",
    response_model=WorkspaceCredentialRead,
)
async def get_workspace_provider_credential_status(
    workspace_id: UUID,
    provider: str,
    workspace: SelectedWorkspace,
    session: SessionDep,
) -> WorkspaceCredentialRead:
    provider = provider.strip()
    if provider not in _PROVIDERS:
        raise ValidationAppError("unsupported workspace credential provider")
    if workspace_id != workspace.id:
        raise NotFoundError("workspace not found")
    return WorkspaceCredentialRead(
        provider=provider,
        configured=await has_credential(
            session,
            workspace_id=workspace_id,
            provider=provider,
        ),
    )
