"""Restricted Proxy management HTTP and immutable, non-secret deployment references."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.config import Settings
from app.shared.errors import AppError, ValidationAppError


def is_managed_alias(value: str) -> bool:
    """Reserved deployment-reference namespace, not a model capability inference."""
    return re.fullmatch(r"df-[0-9a-f]{32}", value) is not None


class GatewayModelWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    display_name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=240)
    model_id: str = Field(min_length=1, max_length=160)
    api_key: SecretStr = Field(min_length=1, max_length=4096)
    contract_profile: Literal["chat_text_v1"] = "chat_text_v1"


class GatewayKeyWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    api_key: SecretStr = Field(min_length=1, max_length=4096)


class GatewayConfigurationRead(BaseModel):
    base_url: str
    model_id: str
    deployment_id: UUID
    key_revision: int
    contract_profile: Literal["chat_text_v1"]


class GatewayReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    deployment_id: UUID
    workspace_id: UUID
    connection_id: UUID
    alias: str
    remote_model_id: str
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    key_revision: int = Field(default=1, ge=1)
    request_id: UUID
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["reserved", "submission_started", "ready", "unknown", "rejected"]
    operation: Literal["create", "rotate_key"] = "create"
    contract_profile: Literal["chat_text_v1"] = "chat_text_v1"
    error_code: str | None = None

    def execution_reference(self) -> dict[str, object]:
        return {
            "deployment_id": str(self.deployment_id),
            "workspace_id": str(self.workspace_id),
            "connection_id": str(self.connection_id),
            "config_hash": self.config_hash,
            "key_revision": self.key_revision,
        }


def physical_hash(base_url: str, model: str) -> str:
    body = {"api_base": base_url.rstrip("/"), "model": model}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def checked_upstream_url(value: str) -> str:
    from app.providers.host_guard import classify_ip_address

    value = value.strip().rstrip("/")
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError as exc:
        raise ValidationAppError("upstream URL or port is invalid") from exc
    if (
        url.scheme not in {"https", "http"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.hostname.lower().rstrip(".")
        in {"localhost", "metadata.google.internal", "metadata.goog"}
    ):
        raise ValidationAppError("upstream must be an HTTP(S) URL without embedded credentials")
    try:
        address = ipaddress.ip_address(url.hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_loopback
        or classify_ip_address(str(address)) != "public"
        and classify_ip_address(str(address)) != "private_deployment"
    ):
        raise ValidationAppError("upstream destination is forbidden")
    if port is not None and not 1 <= port <= 65535:
        raise ValidationAppError("upstream port is invalid")
    return value


class GatewayManagementError(AppError):
    def __init__(self, *, unknown: bool, http_status: int | None = None) -> None:
        self.unknown = unknown
        super().__init__(
            code="GATEWAY_MANAGEMENT_UNKNOWN" if unknown else "GATEWAY_MANAGEMENT_REJECTED",
            message="Proxy model operation requires verification"
            if unknown
            else "Proxy rejected model management operation",
            status_code=503 if unknown else 422,
            details={"http_status": http_status},
        )


class GatewayManagementClient:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        if not settings.litellm_gateway_url or not settings.litellm_model_admin_key:
            raise ValidationAppError(
                "Proxy model management is not configured",
                details={"code": "GATEWAY_MANAGEMENT_NOT_CONFIGURED"},
            )
        root = settings.litellm_gateway_url.rstrip("/")
        self.root = root[:-3] if root.endswith("/v1") else root
        self.key = settings.litellm_model_admin_key
        self.transport = transport

    async def _call(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=15, trust_env=False, follow_redirects=False
            ) as client:
                return await client.request(
                    method,
                    self.root + path,
                    params=params,
                    json=body,
                    headers={"Authorization": f"Bearer {self.key}"},
                )
        except httpx.HTTPError as exc:
            # No blind replay, even though this is configuration rather than generation.
            raise GatewayManagementError(unknown=True) from exc

    async def get(self, identifier: UUID) -> dict[str, Any] | None:
        response = await self._call(
            "GET", "/model/info", params={"litellm_model_id": str(identifier)}
        )
        if response.status_code == 400:
            # Exact not-found contract observed on the locked image; no other
            # HTTP 400 means absence or authorizes a create.
            expected = f"Model id = {identifier} not found on litellm proxy"
            try:
                if response.json() == {"detail": {"error": expected}}:
                    return None
            except ValueError:
                pass
        if response.status_code >= 300:
            raise GatewayManagementError(unknown=True, http_status=response.status_code)
        try:
            rows = response.json()["data"]
            matching = [
                row for row in rows if row.get("model_info", {}).get("id") == str(identifier)
            ]
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise GatewayManagementError(unknown=True) from exc
        if len(matching) != 1:
            raise GatewayManagementError(unknown=True)
        return dict(matching[0])

    async def create(
        self,
        reference: GatewayReference,
        *,
        workspace_id: UUID,
        connection_id: UUID,
        body: GatewayModelWrite,
    ) -> None:
        payload = {
            "model_name": reference.alias,
            "litellm_params": {
                "model": f"openai/{body.model_id}",
                "api_base": body.base_url,
                "api_key": body.api_key.get_secret_value(),
                "max_retries": 0,
            },
            "model_info": {
                "id": str(reference.deployment_id),
                "df_managed": True,
                "df_workspace_id": str(workspace_id),
                "df_connection_id": str(connection_id),
                "df_config_hash": reference.config_hash,
                "df_key_revision": 1,
                "df_request_id": str(reference.request_id),
                "df_contract_profile": reference.contract_profile,
            },
        }
        response = await self._call("POST", "/model/new", body=payload)
        if response.status_code >= 300:
            raise GatewayManagementError(
                unknown=response.status_code >= 500, http_status=response.status_code
            )

    async def rotate_key(self, reference: GatewayReference, body: GatewayKeyWrite) -> None:
        response = await self._call(
            "PATCH",
            f"/model/{reference.deployment_id}/update",
            body={
                "litellm_params": {"api_key": body.api_key.get_secret_value()},
                "model_info": {
                    "id": str(reference.deployment_id),
                    "df_key_revision": reference.key_revision,
                    "df_request_id": str(reference.request_id),
                },
            },
        )
        if response.status_code >= 300:
            raise GatewayManagementError(
                unknown=response.status_code >= 500, http_status=response.status_code
            )
