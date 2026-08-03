"""Provider Connection, capability evidence, and binding use cases."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import httpx
from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.config import Settings, get_settings
from app.consistency.face_policy import (
    approved_face_policy_snapshot,
    approved_face_threshold,
)
from app.execution.models import Artifact, GraphNode, NodeRun
from app.providers.agnes import AGNES_CN_HOST, AGNES_CN_PROFILE, AgnesHubClient
from app.providers.models import (
    ProjectProviderBinding,
    ProviderCapabilityEvidence,
    ProviderConnection,
    ProviderModelBinding,
    ProviderQualityEvidence,
)
from app.providers.reference_delivery import issue_artifact_reference
from app.providers.workspace_credentials import configured_byok_keyring
from app.security.credentials import read_credential, store_credential
from app.security.models import EncryptedProviderCredential
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError
from app.storage.minio_store import get_object_store

_CAPABILITIES = frozenset(
    {
        "auth_models",
        "image_t2i",
        "image_i2i",
        "video_i2v",
        "video_poll_download",
    }
)
_MODEL_CONTRACTS = {
    ("image", "keyframe"): "agnes-image-2.1-flash",
    ("video", "video"): "agnes-video-v2.0",
}
_PAID_PROBES = frozenset({"image_t2i", "image_i2i", "video_i2v"})


class ProviderConnectionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_connection(
        self,
        *,
        workspace_id: UUID,
        actor: User,
        display_name: str,
        api_key: str,
        enabled: bool,
    ) -> ProviderConnection:
        secret = api_key.strip()
        if not secret:
            raise ValidationAppError("api_key must not be empty")
        existing = await self._session.scalar(
            select(ProviderConnection.id).where(
                ProviderConnection.workspace_id == workspace_id,
                ProviderConnection.provider_type == "agnes",
                ProviderConnection.protocol_profile == AGNES_CN_PROFILE,
            )
        )
        if existing is not None:
            raise ConflictError(
                "Agnes China connection already exists for this Workspace",
                details={"code": "PROVIDER_CONNECTION_EXISTS"},
            )
        credential = await store_credential(
            self._session,
            workspace_id=workspace_id,
            provider="agnes",
            plaintext=secret,
            keyring=configured_byok_keyring(),
        )
        connection = ProviderConnection(
            workspace_id=workspace_id,
            provider_type="agnes",
            display_name=display_name.strip() or "Agnes 中国站",
            base_url=AGNES_CN_HOST,
            protocol_profile=AGNES_CN_PROFILE,
            credential_id=credential.id,
            enabled=enabled,
            verification_status="unverified",
            created_by=actor.id,
            updated_by=actor.id,
        )
        self._session.add(connection)
        await self._session.flush()
        return connection

    async def list_connections(self, *, workspace_id: UUID) -> list[ProviderConnection]:
        return list(
            (
                await self._session.execute(
                    select(ProviderConnection)
                    .where(ProviderConnection.workspace_id == workspace_id)
                    .order_by(ProviderConnection.created_at, ProviderConnection.id)
                )
            )
            .scalars()
            .all()
        )

    async def get_connection(
        self, *, workspace_id: UUID, connection_id: UUID
    ) -> ProviderConnection:
        connection = await self._session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.id == connection_id,
                ProviderConnection.workspace_id == workspace_id,
            )
        )
        if connection is None:
            raise NotFoundError("provider connection not found")
        return connection

    async def credential_version(self, connection: ProviderConnection) -> str | None:
        key_version = await self._session.scalar(
            select(EncryptedProviderCredential.key_version).where(
                EncryptedProviderCredential.id == connection.credential_id,
                EncryptedProviderCredential.workspace_id == connection.workspace_id,
            )
        )
        if not isinstance(key_version, str):
            return None
        return f"{connection.credential_revision}:{key_version}"

    async def update_connection(
        self,
        *,
        workspace_id: UUID,
        connection_id: UUID,
        actor: User,
        display_name: str | None,
        enabled: bool | None,
    ) -> ProviderConnection:
        connection = await self.get_connection(
            workspace_id=workspace_id, connection_id=connection_id
        )
        if display_name is not None:
            connection.display_name = display_name.strip() or connection.display_name
        if enabled is not None:
            connection.enabled = enabled
        connection.updated_by = actor.id
        await self._session.flush()
        return connection

    async def update_credential(
        self,
        *,
        workspace_id: UUID,
        connection_id: UUID,
        actor: User,
        api_key: str,
    ) -> ProviderConnection:
        connection = await self.get_connection(
            workspace_id=workspace_id, connection_id=connection_id
        )
        secret = api_key.strip()
        if not secret:
            raise ValidationAppError("api_key must not be empty")
        credential = await store_credential(
            self._session,
            workspace_id=workspace_id,
            provider="agnes",
            plaintext=secret,
            keyring=configured_byok_keyring(),
        )
        connection.credential_id = credential.id
        connection.credential_revision += 1
        connection.verification_status = "unverified"
        connection.verified_at = None
        connection.updated_by = actor.id
        await self._session.execute(
            delete(ProviderCapabilityEvidence).where(
                ProviderCapabilityEvidence.connection_id == connection.id
            )
        )
        await self._session.execute(
            delete(ProviderQualityEvidence).where(
                ProviderQualityEvidence.model_binding_id.in_(
                    select(ProviderModelBinding.id).where(
                        ProviderModelBinding.connection_id == connection.id
                    )
                )
            )
        )
        bindings = list(
            (
                await self._session.execute(
                    select(ProviderModelBinding).where(
                        ProviderModelBinding.connection_id == connection.id
                    )
                )
            )
            .scalars()
            .all()
        )
        for binding in bindings:
            binding.account_verified = False
            binding.quality_gated = False
            binding.updated_by = actor.id
        await self._session.flush()
        return connection

    async def _connection_settings(self, connection: ProviderConnection) -> Settings:
        secret = await read_credential(
            self._session,
            workspace_id=connection.workspace_id,
            provider="agnes",
            keyring=configured_byok_keyring(),
        )
        if not secret:
            raise ValidationAppError(
                "provider credential is missing",
                details={"code": "PROVIDER_NOT_CONFIGURED"},
            )
        return get_settings().model_copy(
            update={
                "agnes_enabled": connection.enabled,
                "agnes_api_key": secret,
                "agnes_base_url": connection.base_url,
            }
        )

    async def probe(
        self,
        *,
        workspace_id: UUID,
        connection_id: UUID,
        actor: User,
        capability: str,
        reference_artifact_id: UUID | None = None,
        remote_task_id: str | None = None,
        remote_query_kind: str | None = None,
        budget_authorized: Decimal = Decimal("0"),
    ) -> ProviderCapabilityEvidence:
        if capability not in _CAPABILITIES:
            raise ValidationAppError("unsupported Provider capability")
        connection = await self.get_connection(
            workspace_id=workspace_id, connection_id=connection_id
        )
        if not connection.enabled:
            raise ValidationAppError(
                "provider connection is disabled",
                details={"code": "PROVIDER_CONNECTION_DISABLED"},
            )
        if budget_authorized < 0:
            raise ValidationAppError("budget_authorized must be >= 0")
        if capability in _PAID_PROBES and budget_authorized <= 0:
            raise ValidationAppError(
                "paid Probe requires an explicit budget authorization",
                details={"code": "PROBE_BUDGET_REQUIRED"},
            )
        recent = await self._session.scalar(
            select(ProviderCapabilityEvidence)
            .where(
                ProviderCapabilityEvidence.connection_id == connection.id,
                ProviderCapabilityEvidence.capability == capability,
                ProviderCapabilityEvidence.tested_at > datetime.now(UTC) - timedelta(seconds=30),
            )
            .order_by(ProviderCapabilityEvidence.tested_at.desc())
        )
        if recent is not None:
            raise ValidationAppError(
                "probe rate limited; wait before retrying",
                details={"code": "PROBE_RATE_LIMITED"},
            )
        cfg = await self._connection_settings(connection)
        client = AgnesHubClient(cfg, host=connection.base_url)
        reference_artifact: Artifact | None = None
        reference_bytes: bytes | None = None
        reference_mime = "image/png"
        reference_url: str | None = None
        if reference_artifact_id is not None:
            reference_artifact, reference_bytes = await self._validated_reference_artifact(
                workspace_id=workspace_id,
                artifact_id=reference_artifact_id,
            )
            reference_mime = reference_artifact.mime_type
            if capability == "video_i2v":
                grant = await issue_artifact_reference(
                    self._session,
                    artifact=reference_artifact,
                    workspace_id=workspace_id,
                    created_by_user_id=actor.id,
                )
                reference_url = grant.url
                # Provider requests run outside this transaction. Commit the
                # grant first so a separate public delivery request can see it,
                # then restore the authenticated Workspace RLS context.
                await self._session.commit()
                from app.shared.db import set_rls_context

                await set_rls_context(
                    self._session,
                    user_id=actor.id,
                    workspace_id=workspace_id,
                )
        request_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "capability": capability,
                    "connection_id": str(connection.id),
                    "credential_revision": connection.credential_revision,
                    "reference_artifact_id": (
                        str(reference_artifact_id) if reference_artifact_id else None
                    ),
                    "remote_task_id": remote_task_id,
                    "remote_query_kind": remote_query_kind,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        status = "failed"
        http_status: int | None = None
        provider_request_id: str | None = None
        error_code: str | None = None
        model_id: str | None = None
        if capability == "auth_models":
            try:
                async with httpx.AsyncClient(timeout=30.0) as http:
                    response = await http.get(
                        f"{connection.base_url}/v1/models",
                        headers={"Authorization": f"Bearer {cfg.agnes_api_key}"},
                    )
                http_status = response.status_code
                status = "passed" if response.status_code < 400 else "failed"
                if response.status_code == 401:
                    error_code = "PROVIDER_AUTH_FAILED"
                elif response.status_code == 403:
                    error_code = "PROVIDER_FORBIDDEN"
                elif response.status_code >= 400:
                    error_code = "PROVIDER_REQUEST_FAILED"
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                error_code = "PROVIDER_UNAVAILABLE"
        elif capability == "image_t2i":
            model_id = cfg.agnes_image_model
            result = await client.create_image(
                prompt="Cinematic portrait contract probe",
                size="1024x768",
            )
            result_status = str(result.get("status") or "failed")
            status = "passed" if result_status == "succeeded" else result_status
            provider_request_id = str(result.get("remote_task_id") or "") or None
            http_status = int(result["http_status"]) if result.get("http_status") else None
            error_code = str(result.get("error_code") or "") or None
        elif capability == "image_i2i":
            model_id = cfg.agnes_image_model
            if reference_bytes is None:
                error_code = "PROBE_REFERENCE_REQUIRED"
            else:
                result = await client.create_image(
                    prompt="Preserve the supplied character identity",
                    size="1024x768",
                    canonical_image_bytes=reference_bytes,
                    canonical_image_mime=reference_mime,
                )
                result_status = str(result.get("status") or "failed")
                status = "passed" if result_status == "succeeded" else result_status
                provider_request_id = str(result.get("remote_task_id") or "") or None
                http_status = int(result["http_status"]) if result.get("http_status") else None
                error_code = str(result.get("error_code") or "") or None
        elif capability == "video_i2v":
            model_id = cfg.agnes_video_model
            if reference_url is None:
                error_code = "PROBE_REFERENCE_REQUIRED"
            else:
                result = await client.create_video(
                    prompt="Controlled camera motion with stable facial appearance",
                    image_url=reference_url,
                )
                result_status = str(result.get("status") or "failed")
                status = (
                    "passed"
                    if result_status in {"succeeded", "queued", "running"}
                    and result.get("remote_task_id")
                    else result_status
                )
                provider_request_id = str(result.get("remote_task_id") or "") or None
                http_status = int(result["http_status"]) if result.get("http_status") else None
                error_code = str(result.get("error_code") or "") or None
        else:
            model_id = cfg.agnes_video_model
            if remote_task_id is None or remote_query_kind not in {"video_id", "task_id"}:
                error_code = "PROBE_REMOTE_TASK_REQUIRED"
            else:
                poll = await client.poll_video(
                    remote_task_id,
                    query_kind=remote_query_kind,  # type: ignore[arg-type]
                )
                poll_status = str(poll.get("status") or "failed")
                status = "passed" if poll_status == "succeeded" else poll_status
                provider_request_id = remote_task_id
                http_status = int(poll["http_status"]) if poll.get("http_status") else None
                error_code = str(poll.get("error_code") or "") or None

        evidence = ProviderCapabilityEvidence(
            workspace_id=workspace_id,
            connection_id=connection.id,
            capability=capability,
            model_id=model_id,
            status=status,
            evidence_level="account_verified",
            http_status=http_status,
            provider_request_id=provider_request_id,
            reference_artifact_id=reference_artifact_id,
            remote_query_kind=remote_query_kind,
            request_fingerprint=request_fingerprint,
            budget_authorized=budget_authorized,
            provider_cost=None,
            currency="USD",
            cost_status="not_reported",
            error_code=error_code,
            created_by=actor.id,
        )
        self._session.add(evidence)
        if capability == "auth_models" and status == "passed":
            connection.verification_status = "verified"
            connection.verified_at = datetime.now(UTC)
        if status in {"passed", "succeeded"}:
            await self._mark_capability_verified(
                connection_id=connection.id,
                capability=capability,
                actor=actor,
            )
        await self._session.flush()
        return evidence

    async def _validated_reference_artifact(
        self,
        *,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> tuple[Artifact, bytes]:
        artifact = await self._session.get(Artifact, artifact_id)
        project = await self._session.get(Project, artifact.project_id) if artifact else None
        if (
            artifact is None
            or project is None
            or project.workspace_id != workspace_id
            or artifact.storage_state != "available"
            or artifact.deleted_at is not None
            or artifact.artifact_type != "image"
            or artifact.mime_type not in {"image/png", "image/jpeg", "image/webp"}
        ):
            raise NotFoundError("reference Artifact not found")
        try:
            data = await get_object_store().get_bytes(object_key=artifact.object_key)
        except Exception as exc:
            raise NotFoundError("reference Artifact not found") from exc
        if not data or hashlib.sha256(data).hexdigest() != artifact.content_hash:
            raise ValidationAppError(
                "reference Artifact content hash mismatch",
                details={"code": "REFERENCE_ARTIFACT_HASH_MISMATCH"},
            )
        try:
            from io import BytesIO

            with Image.open(BytesIO(data)) as image:
                image.verify()
                detected = Image.MIME.get(image.format or "")
        except (UnidentifiedImageError, OSError) as exc:
            raise ValidationAppError(
                "reference Artifact is not a valid image",
                details={"code": "REFERENCE_ARTIFACT_INVALID"},
            ) from exc
        if detected != artifact.mime_type:
            raise ValidationAppError(
                "reference Artifact MIME does not match its bytes",
                details={"code": "REFERENCE_ARTIFACT_MIME_MISMATCH"},
            )
        return artifact, data

    async def _mark_capability_verified(
        self,
        *,
        connection_id: UUID,
        capability: str,
        actor: User,
    ) -> None:
        purpose = {
            "image_i2i": "keyframe",
            "video_i2v": "video",
        }.get(capability)
        if purpose is None:
            return
        bindings = list(
            (
                await self._session.execute(
                    select(ProviderModelBinding).where(
                        ProviderModelBinding.connection_id == connection_id,
                        ProviderModelBinding.purpose == purpose,
                    )
                )
            )
            .scalars()
            .all()
        )
        for binding in bindings:
            binding.account_verified = True
            binding.updated_by = actor.id

    async def create_model_binding(
        self,
        *,
        workspace_id: UUID,
        connection_id: UUID,
        actor: User,
        media_type: str,
        model_id: str,
        purpose: str,
        enabled: bool,
    ) -> ProviderModelBinding:
        connection = await self.get_connection(
            workspace_id=workspace_id, connection_id=connection_id
        )
        expected_model = _MODEL_CONTRACTS.get((media_type, purpose))
        if expected_model is None or model_id != expected_model:
            raise ValidationAppError("model binding does not match agnes_cn_v1 contract")
        duplicate = await self._session.scalar(
            select(ProviderModelBinding.id).where(
                ProviderModelBinding.connection_id == connection.id,
                ProviderModelBinding.media_type == media_type,
                ProviderModelBinding.model_id == model_id,
                ProviderModelBinding.purpose == purpose,
            )
        )
        if duplicate is not None:
            raise ConflictError(
                "Provider model binding already exists",
                details={"code": "PROVIDER_MODEL_BINDING_EXISTS"},
            )
        capability = "image_i2i" if media_type == "image" else "video_i2v"
        verified = (
            await self._session.scalar(
                select(ProviderCapabilityEvidence.id)
                .where(
                    ProviderCapabilityEvidence.connection_id == connection.id,
                    ProviderCapabilityEvidence.capability == capability,
                    ProviderCapabilityEvidence.status.in_({"passed", "succeeded"}),
                )
                .limit(1)
            )
        ) is not None
        binding = ProviderModelBinding(
            workspace_id=workspace_id,
            connection_id=connection.id,
            media_type=media_type,
            model_id=model_id,
            purpose=purpose,
            enabled=enabled,
            documented=True,
            contract_tested=True,
            account_verified=verified,
            quality_gated=False,
            created_by=actor.id,
            updated_by=actor.id,
        )
        self._session.add(binding)
        await self._session.flush()
        return binding

    async def list_capability_evidence(
        self,
        *,
        workspace_id: UUID,
        connection_id: UUID,
    ) -> list[ProviderCapabilityEvidence]:
        await self.get_connection(
            workspace_id=workspace_id,
            connection_id=connection_id,
        )
        return list(
            (
                await self._session.execute(
                    select(ProviderCapabilityEvidence)
                    .where(
                        ProviderCapabilityEvidence.workspace_id == workspace_id,
                        ProviderCapabilityEvidence.connection_id == connection_id,
                    )
                    .order_by(
                        ProviderCapabilityEvidence.tested_at.desc(),
                        ProviderCapabilityEvidence.id,
                    )
                )
            )
            .scalars()
            .all()
        )

    async def record_quality_evidence(
        self,
        *,
        workspace_id: UUID,
        connection_id: UUID,
        model_binding_id: UUID,
        node_run_id: UUID,
        artifact_id: UUID,
        actor: User,
    ) -> ProviderQualityEvidence:
        await self.get_connection(
            workspace_id=workspace_id,
            connection_id=connection_id,
        )
        binding = await self._session.scalar(
            select(ProviderModelBinding).where(
                ProviderModelBinding.id == model_binding_id,
                ProviderModelBinding.workspace_id == workspace_id,
                ProviderModelBinding.connection_id == connection_id,
            )
        )
        if binding is None:
            raise NotFoundError("model binding not found")
        if not binding.enabled or not binding.account_verified:
            raise ValidationAppError(
                "model binding has no account-verified capability",
                details={"code": "MODEL_BINDING_NOT_ACCOUNT_VERIFIED"},
            )
        run = await self._session.get(NodeRun, node_run_id)
        artifact = await self._session.get(Artifact, artifact_id)
        node = await self._session.get(GraphNode, run.graph_node_id) if run else None
        project = await self._session.get(Project, run.project_id) if run else None
        if (
            run is None
            or artifact is None
            or node is None
            or project is None
            or project.workspace_id != workspace_id
            or run.status not in {"completed", "cached"}
            or run.result_artifact_id != artifact.id
            or artifact.project_id != run.project_id
            or artifact.storage_state != "available"
            or artifact.deleted_at is not None
        ):
            raise NotFoundError("quality evidence not found")
        summary = run.output_summary or {}
        score: Decimal | None = None
        if binding.purpose == "keyframe":
            if node.node_key != "face_review":
                raise ValidationAppError("keyframe quality proof must be a Face Review")
            try:
                score = Decimal(str(summary.get("face_score")))
            except Exception as exc:
                raise ValidationAppError("Face Review score is missing") from exc
            if (
                summary.get("status") != "passed"
                or score < Decimal(str(approved_face_threshold()))
                or (run.input_snapshot or {}).get("face_policy") != approved_face_policy_snapshot()
            ):
                raise ValidationAppError(
                    "Face Review does not satisfy the approved quality Gate",
                    details={"code": "QUALITY_GATE_NOT_SATISFIED"},
                )
            evidence_kind = "face_review"
            policy_id = str(approved_face_policy_snapshot()["policy_id"])
        else:
            policy = summary.get("video_drift_policy")
            if (
                node.node_key != "video_drift_review"
                or summary.get("status") != "passed"
                or not isinstance(policy, dict)
                or not policy.get("approval_id")
            ):
                raise ValidationAppError(
                    "Video Drift policy is not approved",
                    details={"code": "VIDEO_DRIFT_POLICY_UNAPPROVED"},
                )
            evidence_kind = "video_drift_review"
            policy_id = str(policy.get("policy_id") or policy["approval_id"])
        existing = await self._session.scalar(
            select(ProviderQualityEvidence).where(
                ProviderQualityEvidence.model_binding_id == binding.id,
                ProviderQualityEvidence.node_run_id == run.id,
            )
        )
        if existing is not None:
            return existing
        evidence = ProviderQualityEvidence(
            workspace_id=workspace_id,
            model_binding_id=binding.id,
            node_run_id=run.id,
            artifact_id=artifact.id,
            evidence_kind=evidence_kind,
            policy_id=policy_id,
            score=score,
            approved_by=actor.id,
        )
        self._session.add(evidence)
        binding.quality_gated = True
        binding.updated_by = actor.id
        await self._session.flush()
        return evidence

    async def list_model_bindings(
        self, *, workspace_id: UUID, connection_id: UUID
    ) -> list[ProviderModelBinding]:
        await self.get_connection(workspace_id=workspace_id, connection_id=connection_id)
        return list(
            (
                await self._session.execute(
                    select(ProviderModelBinding)
                    .where(
                        ProviderModelBinding.workspace_id == workspace_id,
                        ProviderModelBinding.connection_id == connection_id,
                    )
                    .order_by(ProviderModelBinding.media_type, ProviderModelBinding.model_id)
                )
            )
            .scalars()
            .all()
        )

    async def bind_project(
        self,
        *,
        project: Project,
        purpose: str,
        model_binding_id: UUID,
        fallback_policy: str,
        actor: User,
    ) -> ProjectProviderBinding:
        if purpose not in {"keyframe", "video"} or fallback_policy != "none":
            raise ValidationAppError("unsupported project Provider binding")
        model = await self._session.scalar(
            select(ProviderModelBinding).where(
                ProviderModelBinding.id == model_binding_id,
                ProviderModelBinding.workspace_id == project.workspace_id,
                ProviderModelBinding.purpose == purpose,
            )
        )
        if model is None:
            raise NotFoundError("model binding not found")
        if not (
            model.enabled
            and model.documented
            and model.contract_tested
            and model.account_verified
            and model.quality_gated
        ):
            raise ValidationAppError(
                "model binding is not fully verified",
                details={"code": "MODEL_BINDING_NOT_VERIFIED"},
            )
        binding = await self._session.scalar(
            select(ProjectProviderBinding).where(
                ProjectProviderBinding.project_id == project.id,
                ProjectProviderBinding.purpose == purpose,
            )
        )
        if binding is None:
            binding = ProjectProviderBinding(
                project_id=project.id,
                workspace_id=project.workspace_id,
                purpose=purpose,
                model_binding_id=model.id,
                fallback_policy="none",
                updated_by=actor.id,
            )
            self._session.add(binding)
        else:
            binding.model_binding_id = model.id
            binding.fallback_policy = "none"
            binding.updated_by = actor.id
        await self._session.flush()
        return binding
