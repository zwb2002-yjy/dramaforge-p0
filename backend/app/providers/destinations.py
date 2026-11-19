"""Trusted provider destination declarations derived from real binding config.

A destination is never accepted as a free-form URL. The caller names an already
registered ``ProviderModelBinding`` of the workspace; the server resolves the
connection, derives the route manifest and configuration hash from stored rows,
and appends an immutable revision. ``local`` processing is only recorded when the
resolved origin really is a private or loopback endpoint — selecting "local" in a
request is not evidence by itself.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.egress_models import (
    EGRESS_PURPOSES,
    PROCESSING_LOCATIONS,
    ProviderDestinationRevision,
)
from app.access.models import User, Workspace
from app.providers.models import ProviderConnection, ProviderModelBinding
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

_MAX_ORIGINS = 8


def _canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    )


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValidationAppError(
            "提供方地址不是受支持的 HTTP(S) 端点",
            details={"code": "DESTINATION_CONFIG_INVALID"},
        )
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return f"{parts.scheme}://{parts.hostname}:{port}"


def _host_is_private(origin: str) -> bool:
    host = urlsplit(origin).hostname or ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Service names resolve inside the deployment network; a public DNS name
        # is not private evidence, so only explicit private/loopback literals and
        # single-label internal hosts count.
        return "." not in host
    return address.is_private or address.is_loopback or address.is_link_local


def _registered_origin(value: str) -> str:
    """Extra result origins must be plain scheme://host[:port] without extras."""
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or "*" in value
        or parts.path not in {"", "/"}
    ):
        raise ValidationAppError(
            "额外结果来源必须是显式的 scheme://主机[:端口]",
            details={"code": "DESTINATION_ORIGIN_INVALID"},
        )
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return f"{parts.scheme}://{parts.hostname}:{port}"


class DestinationService:
    """Workspace-scoped destination registry; callers own the transaction."""

    def __init__(self, session: AsyncSession, *, actor: User, workspace: Workspace) -> None:
        self._session = session
        self._actor = actor
        self._workspace = workspace

    async def list_destinations(
        self, *, binding_ref: str | None = None, limit: int = 50, offset: int = 0,
    ) -> list[ProviderDestinationRevision]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValidationAppError("Invalid destination page")
        query = select(ProviderDestinationRevision).where(
            ProviderDestinationRevision.workspace_id == self._workspace.id
        )
        if binding_ref is not None:
            query = query.where(ProviderDestinationRevision.binding_ref == binding_ref)
        return list(
            await self._session.scalars(
                query.order_by(
                    ProviderDestinationRevision.binding_ref,
                    ProviderDestinationRevision.revision,
                ).limit(limit).offset(offset)
            )
        )

    async def get_destination(self, destination_id: UUID) -> ProviderDestinationRevision:
        row = await self._session.scalar(
            select(ProviderDestinationRevision).where(
                ProviderDestinationRevision.id == destination_id,
                ProviderDestinationRevision.workspace_id == self._workspace.id,
            )
        )
        if row is None:
            raise NotFoundError("provider destination not found")
        return row

    async def _binding(self, binding_ref: str) -> tuple[ProviderModelBinding, ProviderConnection]:
        try:
            binding_id = UUID(binding_ref)
        except ValueError as exc:
            raise ValidationAppError(
                "目的地必须引用已登记的模型绑定",
                details={"code": "DESTINATION_BINDING_INVALID"},
            ) from exc
        binding = await self._session.scalar(
            select(ProviderModelBinding).where(ProviderModelBinding.id == binding_id)
        )
        if binding is None:
            raise NotFoundError("provider binding not found")
        connection = await self._session.scalar(
            select(ProviderConnection).where(ProviderConnection.id == binding.connection_id)
        )
        if connection is None or connection.workspace_id != self._workspace.id:
            raise NotFoundError("provider binding not found")
        return binding, connection

    async def declare(
        self,
        *,
        binding_ref: str,
        expected_revision: int,
        expected_configuration_hash: str,
        processing_location: str,
        purposes: list[str],
        additional_result_origins: list[str] | None = None,
    ) -> ProviderDestinationRevision:
        if expected_revision < 0:
            raise ValidationAppError("期望修订号不能为负")
        if processing_location not in PROCESSING_LOCATIONS:
            raise ValidationAppError("不支持的处理位置")
        clean_purposes = sorted({str(purpose) for purpose in purposes})
        if not clean_purposes or any(p not in EGRESS_PURPOSES for p in clean_purposes):
            raise ValidationAppError(
                "目的地必须声明合法的外发用途", details={"code": "DESTINATION_PURPOSE_INVALID"},
            )
        extra = additional_result_origins or []
        if len(extra) > _MAX_ORIGINS:
            raise ValidationAppError("额外结果来源过多")
        origins = sorted({_registered_origin(value) for value in extra})
        binding, connection = await self._binding(binding_ref)
        origin = _origin_of(connection.base_url)
        configuration = {
            "connection_id": str(connection.id),
            "protocol": connection.protocol_profile,
            "origin": origin,
            "model_id": binding.model_id,
            "purpose": binding.purpose,
        }
        configuration_hash = _hash(configuration)
        if expected_configuration_hash != configuration_hash:
            raise ConflictError(
                "提供方配置已变化，请重新读取目的地声明",
                details={
                    "code": "DESTINATION_CONFIGURATION_CHANGED",
                    "configuration_hash": configuration_hash,
                },
            )
        evidence: dict[str, object] = {
            "origin_class": "private" if _host_is_private(origin) else "public",
        }
        if processing_location == "local" and not _host_is_private(origin):
            raise ValidationAppError(
                "该绑定指向公网端点，不能声明为本地处理",
                details={"code": "DESTINATION_LOCAL_UNPROVEN"},
            )
        route_manifest: dict[str, object] = {
            "schema_version": 1,
            "primary_origin": origin,
            "additional_result_origins": origins,
            "model_id": binding.model_id,
            "purpose": binding.purpose,
            "protocol": connection.protocol_profile,
        }
        declaration = {
            "binding_ref": binding_ref,
            "processing_location": processing_location,
            "purposes": clean_purposes,
            "route_manifest": route_manifest,
            "configuration_hash": configuration_hash,
        }
        declaration_hash = _hash(declaration)
        replay = await self._session.scalar(
            select(ProviderDestinationRevision).where(
                ProviderDestinationRevision.workspace_id == self._workspace.id,
                ProviderDestinationRevision.binding_ref == binding_ref,
                ProviderDestinationRevision.origin_expected_revision == expected_revision,
            )
        )
        if replay is not None:
            if replay.declaration_hash != declaration_hash:
                raise ConflictError(
                    "同一期望修订已声明了不同的目的地内容",
                    details={"code": "DESTINATION_DECLARATION_CONFLICT"},
                )
            return replay
        head_revision = int(
            await self._session.scalar(
                select(func.coalesce(func.max(ProviderDestinationRevision.revision), 0)).where(
                    ProviderDestinationRevision.workspace_id == self._workspace.id,
                    ProviderDestinationRevision.binding_ref == binding_ref,
                )
            )
            or 0
        )
        if head_revision != expected_revision:
            raise ConflictError(
                "目的地已由其他声明推进，请刷新后重试",
                details={
                    "code": "DESTINATION_REVISION_CONFLICT",
                    "current_revision": head_revision,
                },
            )
        row = ProviderDestinationRevision(
            workspace_id=self._workspace.id,
            binding_ref=binding_ref,
            revision=head_revision + 1,
            origin_expected_revision=expected_revision,
            upstream_origin=origin,
            processing_location=processing_location,
            purposes=clean_purposes,
            declaration_hash=declaration_hash,
            configuration_hash=configuration_hash,
            route_manifest=route_manifest,
            location_evidence={**evidence, "declared_at": datetime.now(UTC).isoformat()},
            created_by=self._actor.id,
        )
        self._session.add(row)
        await self._session.flush()
        return row


__all__ = ["DestinationService"]
