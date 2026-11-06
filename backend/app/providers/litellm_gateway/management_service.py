"""Manage Proxy models through existing Connection/Revision identities.

Persist the submission marker before the external configuration write. A
timeout or a failed local write can only be reconciled by exact deployment ID,
never by repeating a possibly successful create. Upstream secrets are not stored.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User, Workspace
from app.config import Settings, get_settings
from app.providers.connection_service import ProviderConnectionService
from app.providers.litellm_gateway.management import (
    GatewayConfigurationRead,
    GatewayKeyWrite,
    GatewayManagementClient,
    GatewayManagementError,
    GatewayModelWrite,
    GatewayReference,
    checked_upstream_url,
    physical_hash,
)
from app.providers.models import ProviderConnection, ProviderConnectionRevision
from app.providers.workspace_credentials import configured_byok_keyring
from app.security.credentials import read_credential_by_id, store_credential
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError


class GatewayModelService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        client: GatewayManagementClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self._client_override = client
        self.connections = ProviderConnectionService(session)

    @property
    def client(self) -> GatewayManagementClient:
        return self._client_override or GatewayManagementClient(self.settings)

    async def _authorize(self, workspace_id: UUID, actor: User) -> None:
        owner = await self.session.scalar(
            select(Workspace.id).where(
                Workspace.id == workspace_id, Workspace.owner_user_id == actor.id
            )
        )
        if owner is None:
            raise NotFoundError("workspace not found")

    async def _advisory(self, identifier: UUID) -> None:
        if self.session.get_bind().dialect.name == "postgresql":
            await self.session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": int.from_bytes(identifier.bytes[:8], signed=True)},
            )

    async def _connection(self, identifier: UUID, workspace_id: UUID) -> ProviderConnection | None:
        await self._advisory(identifier)
        connection: ProviderConnection | None = await self.session.scalar(
            select(ProviderConnection)
            .where(
                ProviderConnection.id == identifier, ProviderConnection.workspace_id == workspace_id
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return connection

    async def _commit(self, actor: User, workspace_id: UUID) -> None:
        await self.session.commit()
        await set_rls_context(self.session, user_id=actor.id, workspace_id=workspace_id)

    async def _reject_historical_request(self, connection_id: UUID, request_id: UUID) -> None:
        references = await self.session.scalars(
            select(ProviderConnectionRevision.gateway_ref).where(
                ProviderConnectionRevision.connection_id == connection_id
            )
        )
        if any(ref and ref.get("request_id") == str(request_id) for ref in references):
            raise ConflictError(
                "request ID belongs to a superseded configuration",
                details={"code": "GATEWAY_REQUEST_SUPERSEDED"},
            )

    def _fingerprint(self, values: dict[str, object]) -> str:
        body = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(self.settings.session_secret.encode(), body, hashlib.sha256).hexdigest()

    async def _require_gateway_identity(self, connection: ProviderConnection) -> None:
        if connection.credential_id is None:
            raise ConflictError("managed text connection has no data credential")
        reference = GatewayReference.model_validate(connection.gateway_ref)

        def root(value: str) -> str:
            value = value.rstrip("/")
            return value[:-3] if value.endswith("/v1") else value

        revision = await self.connections.current_connection_revision(connection=connection)
        credential = await read_credential_by_id(
            self.session,
            workspace_id=connection.workspace_id,
            credential_id=connection.credential_id,
            keyring=configured_byok_keyring(self.settings),
        )
        if (
            reference.connection_id != connection.id
            or reference.workspace_id != connection.workspace_id
            or root(connection.base_url) != root(self.settings.litellm_gateway_url)
            or revision.base_url != connection.base_url
            or revision.credential_revision_id != connection.credential_id
            or credential is None
            or not hmac.compare_digest(credential.encode(), self.settings.litellm_api_key.encode())
        ):
            raise ConflictError(
                "Proxy data-plane identity changed; an explicit connection migration is required",
                details={"code": "GATEWAY_DATA_PLANE_CHANGED"},
            )

    async def register(
        self,
        *,
        workspace_id: UUID,
        actor: User,
        body: GatewayModelWrite,
        connection_id: UUID | None = None,
    ) -> ProviderConnection:
        await self._authorize(workspace_id, actor)
        if not self.settings.litellm_api_key:
            raise ValidationAppError(
                "Proxy data credential is not configured",
                details={"code": "GATEWAY_DATA_KEY_NOT_CONFIGURED"},
            )
        # Validate configuration now, before reserving a durable row. It does
        # not send a discovery or generation request to the supplied origin.
        _ = self.client
        body = body.model_copy(
            update={
                "base_url": checked_upstream_url(body.base_url),
                "display_name": body.display_name.strip(),
                "model_id": body.model_id.strip(),
            }
        )
        if (
            not body.display_name
            or not body.model_id
            or not body.api_key.get_secret_value().strip()
        ):
            raise ValidationAppError("model name, remote ID and credential must not be blank")
        fingerprint = self._fingerprint(
            {
                **body.model_dump(mode="json", exclude={"api_key"}),
                "api_key": body.api_key.get_secret_value(),
            }
        )
        identifier = connection_id or uuid5(workspace_id, str(body.request_id))
        # Credential heads are workspace/provider-scoped, including the initial
        # empty head; serialize reservation so two new connections cannot race it.
        await self._advisory(workspace_id)
        if connection_id is None:
            pending = await self.session.scalar(
                select(ProviderConnection).where(
                    ProviderConnection.workspace_id == workspace_id,
                    ProviderConnection.provider_type == "litellm",
                    ProviderConnection.gateway_ref.is_not(None),
                    ProviderConnection.display_name == body.display_name,
                    ProviderConnection.verification_status == "gateway_pending",
                    ProviderConnection.enabled.is_(True),
                    ProviderConnection.id != identifier,
                )
            )
            if pending is not None:
                raise ConflictError("verify the existing pending model configuration first")
        connection = await self._connection(identifier, workspace_id)
        if connection is None and connection_id is not None:
            raise NotFoundError("provider connection not found")
        if connection is not None:
            if connection.gateway_ref is None:
                raise ValidationAppError("connection is not a managed Proxy reference")
            await self._require_gateway_identity(connection)
            current = GatewayReference.model_validate(connection.gateway_ref)
            if current.request_id == body.request_id:
                if current.request_fingerprint != fingerprint:
                    raise ConflictError("request ID was already used for different model settings")
                return await self._perform(connection, actor=actor, body=body)
            await self._reject_historical_request(connection.id, body.request_id)
            if connection_id is None or current.state != "ready":
                raise ConflictError("verify the pending Proxy configuration before replacing it")
        deployment_id = uuid5(identifier, str(body.request_id))
        reference = GatewayReference(
            deployment_id=deployment_id,
            workspace_id=workspace_id,
            connection_id=identifier,
            alias=f"df-{deployment_id.hex}",
            remote_model_id=body.model_id,
            config_hash=physical_hash(body.base_url, f"openai/{body.model_id}"),
            request_id=body.request_id,
            request_fingerprint=fingerprint,
            state="reserved",
        )
        if connection is None:
            credential = await store_credential(
                self.session,
                workspace_id=workspace_id,
                provider="litellm",
                plaintext=self.settings.litellm_api_key,
                keyring=configured_byok_keyring(self.settings),
            )
            connection = ProviderConnection(
                id=identifier,
                workspace_id=workspace_id,
                provider_type="litellm",
                protocol_profile="openai_chat_v1",
                display_name=body.display_name,
                base_url=self.settings.litellm_gateway_url.rstrip("/"),
                credential_id=credential.id,
                credential_revision=credential.revision_no,
                enabled=True,
                verification_status="gateway_pending",
                gateway_ref=reference.model_dump(mode="json"),
                created_by=actor.id,
                updated_by=actor.id,
            )
            self.session.add(connection)
            await self.session.flush()
            await self.connections.create_connection_revision(connection=connection)
        else:
            connection.gateway_ref = reference.model_dump(mode="json")
            connection.display_name = body.display_name
            connection.verification_status = "gateway_pending"
            connection.updated_by = actor.id
        await self._commit(actor, workspace_id)
        return await self._perform(connection, actor=actor, body=body)

    async def rotate_key(
        self, *, workspace_id: UUID, actor: User, connection_id: UUID, body: GatewayKeyWrite
    ) -> ProviderConnection:
        await self._authorize(workspace_id, actor)
        connection = await self._connection(connection_id, workspace_id)
        if connection is None or connection.gateway_ref is None:
            raise NotFoundError("managed Proxy connection not found")
        await self._require_gateway_identity(connection)
        reference = GatewayReference.model_validate(connection.gateway_ref)
        fingerprint = self._fingerprint(
            {
                "operation": "rotate_key",
                "request_id": str(body.request_id),
                "api_key": body.api_key.get_secret_value(),
            }
        )
        if reference.request_id == body.request_id:
            if reference.request_fingerprint != fingerprint:
                raise ConflictError("request ID was already used for another credential")
            return await self._perform(connection, actor=actor, body=body)
        await self._reject_historical_request(connection.id, body.request_id)
        if reference.state != "ready":
            raise ConflictError("verify the pending Proxy configuration first")
        connection.gateway_ref = reference.model_copy(
            update={
                "request_id": body.request_id,
                "request_fingerprint": fingerprint,
                "key_revision": reference.key_revision + 1,
                "state": "reserved",
                "operation": "rotate_key",
                "error_code": None,
            }
        ).model_dump(mode="json")
        connection.verification_status = "gateway_pending"
        connection.updated_by = actor.id
        await self._commit(actor, workspace_id)
        return await self._perform(connection, actor=actor, body=body)

    @staticmethod
    def _matches(
        row: dict[str, object],
        reference: GatewayReference,
        connection: ProviderConnection,
        *,
        previous_key: bool = False,
    ) -> bool:
        info, params = row.get("model_info"), row.get("litellm_params")
        if not isinstance(info, dict) or not isinstance(params, dict):
            return False
        expected_revision = reference.key_revision - int(previous_key)
        return bool(
            row.get("model_name") == reference.alias
            and info.get("id") == str(reference.deployment_id)
            and info.get("df_managed") is True
            and info.get("df_workspace_id") == str(connection.workspace_id)
            and info.get("df_connection_id") == str(connection.id)
            and info.get("df_config_hash") == reference.config_hash
            and info.get("df_contract_profile") == reference.contract_profile
            and params.get("model") == f"openai/{reference.remote_model_id}"
            and isinstance(params.get("api_base"), str)
            and physical_hash(params["api_base"], params["model"]) == reference.config_hash
            and info.get("df_key_revision") == expected_revision
            and (previous_key or info.get("df_request_id") == str(reference.request_id))
        )

    async def _state(
        self,
        connection: ProviderConnection,
        actor: User,
        reference: GatewayReference,
        state: str,
        error: str | None = None,
    ) -> ProviderConnection:
        current = await self._connection(connection.id, connection.workspace_id)
        assert current is not None
        saved = GatewayReference.model_validate(current.gateway_ref)
        if saved.request_id != reference.request_id:
            raise ConflictError("Proxy reference advanced during this request")
        if saved.state == "ready" and reference.state != "ready" and state != "ready":
            return current  # A stale read cannot revoke another request's confirmed write.
        current.gateway_ref = saved.model_copy(
            update={"state": state, "error_code": error}
        ).model_dump(mode="json")
        if state == "ready":
            current.verification_status = "gateway_registered"
            current.verified_at = datetime.now(UTC)
            if saved.state != "ready":
                await self.connections.create_connection_revision(connection=current)
        else:
            current.verification_status = "gateway_pending"
        await self._commit(actor, connection.workspace_id)
        return current

    async def _perform(
        self,
        connection: ProviderConnection,
        *,
        actor: User,
        body: GatewayModelWrite | GatewayKeyWrite | None = None,
    ) -> ProviderConnection:
        await self._require_gateway_identity(connection)
        reference = GatewayReference.model_validate(connection.gateway_ref)
        try:
            remote = await self.client.get(reference.deployment_id)
        except GatewayManagementError:
            return await self._state(
                connection, actor, reference, reference.state, "GATEWAY_READ_UNAVAILABLE"
            )
        if remote is not None and self._matches(remote, reference, connection):
            return await self._state(connection, actor, reference, "ready")
        can_write = (
            remote is None
            if reference.operation == "create"
            else bool(
                remote is not None
                and self._matches(remote, reference, connection, previous_key=True)
            )
        )
        if not can_write:
            return await self._state(
                connection, actor, reference, "unknown", "GATEWAY_DEPLOYMENT_DRIFT"
            )
        if body is None and reference.state == "reserved":
            return await self._state(
                connection, actor, reference, "reserved", "GATEWAY_NOT_SUBMITTED"
            )
        if body is None or reference.state != "reserved":
            return await self._state(
                connection, actor, reference, "unknown", "GATEWAY_SUBMISSION_UNCONFIRMED"
            )
        current = await self._connection(connection.id, connection.workspace_id)
        assert current is not None
        latest = GatewayReference.model_validate(current.gateway_ref)
        if latest.request_id != reference.request_id or latest.state != "reserved":
            return current
        # This marker commits before the only POST. Retrying a request after a
        # crash/read timeout can query but can never repeat this submission.
        current.gateway_ref = latest.model_copy(update={"state": "submission_started"}).model_dump(
            mode="json"
        )
        await self._commit(actor, connection.workspace_id)
        failure: GatewayManagementError | None = None
        try:
            if isinstance(body, GatewayModelWrite):
                await self.client.create(
                    reference,
                    workspace_id=connection.workspace_id,
                    connection_id=connection.id,
                    body=body,
                )
            else:
                await self.client.rotate_key(reference, body)
        except GatewayManagementError as exc:
            failure = exc
        try:
            remote = await self.client.get(reference.deployment_id)
        except GatewayManagementError:
            remote = None
        if remote is not None and self._matches(remote, reference, connection):
            return await self._state(connection, actor, reference, "ready")
        state = "rejected" if failure is not None and not failure.unknown else "unknown"
        return await self._state(
            connection, actor, reference, state, "GATEWAY_SUBMISSION_UNCONFIRMED"
        )

    async def reconcile(
        self, *, workspace_id: UUID, actor: User, connection_id: UUID
    ) -> ProviderConnection:
        await self._authorize(workspace_id, actor)
        connection = await self._connection(connection_id, workspace_id)
        if connection is None or connection.gateway_ref is None:
            raise NotFoundError("managed Proxy connection not found")
        return await self._perform(connection, actor=actor)

    async def configuration(
        self, *, workspace_id: UUID, actor: User, connection_id: UUID
    ) -> GatewayConfigurationRead:
        await self._authorize(workspace_id, actor)
        connection = await self._connection(connection_id, workspace_id)
        if connection is None or connection.gateway_ref is None:
            raise NotFoundError("managed Proxy connection not found")
        await self._require_gateway_identity(connection)
        reference = GatewayReference.model_validate(connection.gateway_ref)
        remote = await self.client.get(reference.deployment_id)
        if remote is None or not self._matches(remote, reference, connection):
            raise ConflictError("Proxy deployment requires verification")
        params = remote["litellm_params"]
        return GatewayConfigurationRead(
            base_url=str(params["api_base"]),
            model_id=reference.remote_model_id,
            deployment_id=reference.deployment_id,
            key_revision=reference.key_revision,
            contract_profile=reference.contract_profile,
        )
