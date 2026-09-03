"""Product execution path: enqueue NodeRun for Worker (no Adapter in request thread)."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import socket
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpcore
import httpx
from httpcore._backends.base import (
    SOCKET_OPTION,
    AsyncNetworkBackend,
    AsyncNetworkStream,
)
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.config import get_settings
from app.consistency.identity_policy import (
    identity_evidence_policy_snapshot,
    validate_identity_evidence_policy,
)
from app.consistency.identity_review import identity_review_images
from app.execution.artifact_lineage import get_or_create_artifact
from app.execution.branches import branch_priority
from app.execution.models import Artifact, GraphEdge, GraphNode, NodeRun, ProviderOperation
from app.providers.request_summary import normalize_request_summary
from app.shared.db import set_node_run_rls_context
from app.shared.errors import (
    NodeRunAlreadyClaimedError,
    ProviderTaskPendingError,
    ValidationAppError,
)
from app.storage.minio_store import ObjectStore, get_object_store

if TYPE_CHECKING:
    from app.providers.runtime import ResolvedReference

_MAX_PROVIDER_MEDIA_BYTES = 512 * 1024 * 1024
_MAX_PROVIDER_IMAGE_BYTES = 20 * 1024 * 1024
_ALLOWED_PROVIDER_MEDIA_MIMES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "video/mp4",
        "video/quicktime",
        "video/webm",
        "audio/mpeg",
        "audio/wav",
        "audio/x-wav",
        "audio/mp4",
    }
)


def _unknown_submission_error_summary(transport_error: object = None) -> str:
    summary = "Provider submission outcome is unknown; manual reconciliation required"
    candidate = str(transport_error or "").strip()
    safe = candidate.replace("_", "").replace(".", "")
    if candidate and len(candidate) <= 80 and candidate.isascii() and safe.isalnum():
        return f"{summary} (transport={candidate})"
    return summary


def _is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global


async def _validate_public_media_url(value: str) -> tuple[str, set[str]]:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValidationAppError("PROVIDER_MEDIA_URL_INVALID: media URL must be HTTPS")
    host = parsed.hostname.rstrip(".")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise ValidationAppError("PROVIDER_MEDIA_URL_INVALID: media URL port is invalid") from exc
    try:
        addresses = {str(ipaddress.ip_address(host))}
    except ValueError:
        try:
            resolved = await asyncio.to_thread(
                socket.getaddrinfo,
                host,
                port,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise ValidationAppError(
                "PROVIDER_MEDIA_URL_INVALID: media host cannot be resolved"
            ) from exc
        addresses = {str(item[4][0]) for item in resolved}
    if not addresses or not all(_is_public_ip(address) for address in addresses):
        raise ValidationAppError("PROVIDER_MEDIA_URL_INVALID: media host is not public")
    return value, addresses


class _PinnedNetworkBackend(AsyncNetworkBackend):
    """Resolve a provider result once, then connect only to that IP."""

    def __init__(self, *, hostname: str, addresses: set[str]) -> None:
        from httpcore._backends.auto import AutoBackend

        self._hostname = hostname.lower().rstrip(".")
        self._address = sorted(addresses)[0]
        self._backend = AutoBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> AsyncNetworkStream:
        target = self._address if host.lower().rstrip(".") == self._hostname else host
        return await self._backend.connect_tcp(
            target,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> AsyncNetworkStream:
        return await self._backend.connect_unix_socket(
            path,
            timeout=timeout,
            socket_options=socket_options,
        )

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


async def _download_provider_media(
    *,
    kind: str,
    artifact_uri: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bytes:
    """Download one provider result with pinned DNS and bounded streaming."""
    value, addresses = await _validate_public_media_url(artifact_uri)
    if transport is not None:
        async with (
            httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=20.0),
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client,
            client.stream("GET", value) as response,
        ):
            if response.is_redirect:
                raise ValidationAppError(
                    "PROVIDER_MEDIA_INVALID: provider media redirects are not allowed"
                )
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > _MAX_PROVIDER_MEDIA_BYTES:
                        raise ValidationAppError("PROVIDER_MEDIA_INVALID: response is too large")
                except ValueError as exc:
                    raise ValidationAppError(
                        "PROVIDER_MEDIA_INVALID: response Content-Length is invalid"
                    ) from exc
            body = bytearray()
            async for chunk in response.aiter_bytes(1024 * 1024):
                body.extend(chunk)
                if len(body) > _MAX_PROVIDER_MEDIA_BYTES:
                    raise ValidationAppError("PROVIDER_MEDIA_INVALID: response is too large")
            return _validate_provider_media(
                kind=kind,
                data=bytes(body),
                content_type=response.headers.get("Content-Type"),
            )
    host = (urlsplit(value).hostname or "").rstrip(".")
    base_transport = httpx.AsyncHTTPTransport(
        trust_env=False,
        limits=httpx.Limits(max_connections=1),
    )
    ssl_context = base_transport._pool._ssl_context
    base_transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=ssl_context,
        max_connections=1,
        max_keepalive_connections=0,
        network_backend=_PinnedNetworkBackend(hostname=host, addresses=addresses),
    )
    try:
        async with (
            httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=20.0),
                follow_redirects=False,
                trust_env=False,
                transport=base_transport,
            ) as client,
            client.stream("GET", value) as response,
        ):
            if response.is_redirect:
                raise ValidationAppError(
                    "PROVIDER_MEDIA_INVALID: provider media redirects are not allowed"
                )
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > _MAX_PROVIDER_MEDIA_BYTES:
                        raise ValidationAppError("PROVIDER_MEDIA_INVALID: response is too large")
                except ValueError as exc:
                    raise ValidationAppError(
                        "PROVIDER_MEDIA_INVALID: response Content-Length is invalid"
                    ) from exc
            body = bytearray()
            async for chunk in response.aiter_bytes(1024 * 1024):
                body.extend(chunk)
                if len(body) > _MAX_PROVIDER_MEDIA_BYTES:
                    raise ValidationAppError("PROVIDER_MEDIA_INVALID: response is too large")
            return _validate_provider_media(
                kind=kind,
                data=bytes(body),
                content_type=response.headers.get("Content-Type"),
            )
    finally:
        await base_transport.aclose()


def _media_magic_matches(kind: str, data: bytes) -> bool:
    if kind in {"keyframe", "image"}:
        return (
            data.startswith(b"\x89PNG\r\n\x1a\n")
            or data.startswith(b"\xff\xd8\xff")
            or (len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP")
        )
    if kind in {"video", "video_review"}:
        return len(data) >= 12 and data[4:8] == b"ftyp"
    if kind in {"voice", "audio"}:
        return data.startswith((b"ID3", b"RIFF", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"))
    return bool(data)


def _validate_provider_media(*, kind: str, data: bytes, content_type: str | None) -> bytes:
    if not data or len(data) > _MAX_PROVIDER_MEDIA_BYTES:
        raise ValidationAppError(
            "PROVIDER_MEDIA_INVALID: response size is outside the allowed range"
        )
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized_type and normalized_type not in _ALLOWED_PROVIDER_MEDIA_MIMES:
        raise ValidationAppError("PROVIDER_MEDIA_INVALID: response MIME is not allowed")
    if not _media_magic_matches(kind, data):
        raise ValidationAppError("PROVIDER_MEDIA_INVALID: response bytes do not match media kind")
    if kind in {"keyframe", "image"} and len(data) > _MAX_PROVIDER_IMAGE_BYTES:
        raise ValidationAppError("PROVIDER_MEDIA_INVALID: image response is too large")
    return data


@dataclass(frozen=True)
class _MediaMetadata:
    width: int | None = None
    height: int | None = None
    duration_seconds: Decimal | None = None


def _inspect_media_metadata(*, kind: str, data: bytes) -> _MediaMetadata:
    """Decode deterministic media metadata before bytes enter object storage."""
    if kind in {"keyframe", "image"}:
        try:
            with Image.open(BytesIO(data)) as image:
                image.load()
                return _MediaMetadata(width=image.width, height=image.height)
        except (UnidentifiedImageError, OSError) as exc:
            if get_settings().app_env != "test":
                raise ValidationAppError(
                    "PROVIDER_MEDIA_INVALID: image cannot be decoded"
                ) from exc
            return _MediaMetadata()
    if kind not in {"video", "video_review", "composite"}:
        return _MediaMetadata()
    import cv2

    with tempfile.TemporaryDirectory(prefix="dramaforge-media-meta-") as temp_dir:
        path = Path(temp_dir) / "source.mp4"
        path.write_bytes(data)
        capture = cv2.VideoCapture(str(path))
        try:
            if not capture.isOpened():
                if get_settings().app_env == "test":
                    return _MediaMetadata()
                raise ValidationAppError("PROVIDER_MEDIA_INVALID: video cannot be decoded")
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            frame_rate = float(capture.get(cv2.CAP_PROP_FPS))
            if width <= 0 or height <= 0 or frame_count <= 0 or frame_rate <= 0:
                if get_settings().app_env == "test":
                    return _MediaMetadata()
                raise ValidationAppError(
                    "PROVIDER_MEDIA_INVALID: video metadata is invalid"
                )
            return _MediaMetadata(
                width=width,
                height=height,
                duration_seconds=Decimal(str(round(frame_count / frame_rate, 3))),
            )
        finally:
            capture.release()


def _apply_media_metadata(artifact: Artifact, metadata: _MediaMetadata) -> None:
    artifact.width = metadata.width
    artifact.height = metadata.height
    artifact.duration_seconds = metadata.duration_seconds


def _binding_pricing_currency(binding: object, *, required: bool) -> str | None:
    snapshot = getattr(binding, "pricing_snapshot_json", None)
    raw = snapshot.get("currency") if isinstance(snapshot, dict) else None
    if isinstance(raw, str):
        currency = raw.strip().upper()
        if len(currency) == 3 and currency.isalpha():
            return currency
    if required:
        raise ValidationAppError(
            "frozen model Binding has no valid pricing currency",
            details={"code": "MODEL_BINDING_PRICING_CURRENCY_REQUIRED"},
        )
    return None


@dataclass(frozen=True)
class ExecuteNodeResult:
    node_run_id: UUID
    artifact_id: UUID
    object_key: str
    content_hash: str
    byte_size: int
    identity_status: str | None
    provider_operation_id: UUID | None
    node_type: str


# Back-compat alias
ExecuteKeyframeResult = ExecuteNodeResult


def _input_hash(payload: dict[str, object]) -> str:
    raw = repr(sorted(payload.items())).encode()
    return hashlib.sha256(raw).hexdigest()


def _snapshot_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _artifact_snapshot(artifact: Artifact, *, prefix: str) -> dict[str, object]:
    return {
        f"{prefix}_artifact_id": str(artifact.id),
        f"{prefix}_object_key": artifact.object_key,
        f"{prefix}_content_hash": artifact.content_hash,
        f"{prefix}_mime_type": artifact.mime_type,
    }


async def _bind_review_input_artifacts(
    session: AsyncSession,
    *,
    run: NodeRun,
    node: GraphNode,
) -> dict[str, object]:
    """Freeze the direct same-Shot media input into a Review snapshot.

    A local repair may reuse a successful upstream from an earlier attempt.
    The exact source Run and attempt are frozen below so lineage remains
    reproducible without forcing unrelated nodes to share one attempt number.
    """
    upstream_key = {
        "identity_review": "keyframe",
        "video_drift_review": "video",
    }.get(node.node_key)
    if upstream_key is None:
        return dict(run.input_snapshot or {})
    upstream_node = await session.scalar(
        select(GraphNode)
        .join(GraphEdge, GraphEdge.upstream_node_id == GraphNode.id)
        .where(
            GraphEdge.graph_version_id == run.graph_version_id,
            GraphEdge.downstream_node_id == node.id,
            GraphEdge.required.is_(True),
            GraphNode.node_key == upstream_key,
        )
    )
    if upstream_node is None:
        raise ValidationAppError(
            f"{upstream_key} GraphEdge is missing",
            details={"code": "UPSTREAM_RUN_MISSING"},
        )
    shot_id = str((run.input_snapshot or {}).get("shot_id") or "")
    candidates = list(
        (
            await session.execute(
                select(NodeRun).where(
                    NodeRun.project_id == run.project_id,
                    NodeRun.graph_version_id == run.graph_version_id,
                    NodeRun.graph_node_id == upstream_node.id,
                    NodeRun.status.in_({"completed", "cached"}),
                )
            )
        )
        .scalars()
        .all()
    )
    source = next(
        (
            candidate
            for candidate in sorted(
                candidates,
                key=lambda item: (
                    branch_priority(item.input_snapshot, run.input_snapshot) or 0,
                    item.attempt_no,
                    item.created_at,
                    str(item.id),
                ),
                reverse=True,
            )
            if str((candidate.input_snapshot or {}).get("shot_id") or "") == shot_id
            and branch_priority(candidate.input_snapshot, run.input_snapshot) is not None
        ),
        None,
    )
    if source is None:
        raise ValidationAppError(
            f"successful {upstream_key} Run is missing",
            details={"code": "UPSTREAM_RUN_MISSING"},
        )
    artifact = (
        await session.get(Artifact, source.result_artifact_id)
        if source.result_artifact_id
        else None
    )
    if artifact is None or artifact.project_id != run.project_id:
        raise ValidationAppError(
            f"successful {upstream_key} Artifact is missing",
            details={"code": "UPSTREAM_ARTIFACT_MISSING"},
        )
    snapshot = {
        **(run.input_snapshot or {}),
        "source_run_id": str(source.id),
        "source_attempt_no": source.attempt_no,
    }
    source_snapshot = source.input_snapshot or {}
    for field in (
        "canonical_artifact_id",
        "canonical_object_key",
        "canonical_content_hash",
        "canonical_mime_type",
    ):
        if field in source_snapshot:
            snapshot[field] = source_snapshot[field]
    prefix = "probe" if node.node_key == "identity_review" else "video"
    snapshot.update(_artifact_snapshot(artifact, prefix=prefix))
    run.input_snapshot = snapshot
    await session.flush()
    return snapshot


async def _read_bound_artifact(
    session: AsyncSession,
    *,
    run: NodeRun,
    snapshot: dict[str, object],
    prefix: str,
    store: ObjectStore,
    artifact_type: str,
) -> tuple[Artifact, bytes]:
    raw_id = snapshot.get(f"{prefix}_artifact_id")
    try:
        artifact_id = UUID(str(raw_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationAppError(
            f"{prefix} Artifact binding is missing",
            details={"code": "UPSTREAM_ARTIFACT_MISSING"},
        ) from exc
    artifact = await session.get(Artifact, artifact_id)
    expected = {
        "object_key": snapshot.get(f"{prefix}_object_key"),
        "content_hash": snapshot.get(f"{prefix}_content_hash"),
        "mime_type": snapshot.get(f"{prefix}_mime_type"),
    }
    if (
        artifact is None
        or artifact.project_id != run.project_id
        or artifact.artifact_type != artifact_type
        or artifact.storage_state != "available"
        or artifact.deleted_at is not None
        or artifact.object_key != expected["object_key"]
        or artifact.content_hash != expected["content_hash"]
        or artifact.mime_type != expected["mime_type"]
    ):
        raise ValidationAppError(
            f"{prefix} Artifact binding does not match available storage metadata",
            details={"code": "UPSTREAM_ARTIFACT_MISSING"},
        )
    try:
        data = await store.get_bytes(object_key=artifact.object_key)
    except Exception as exc:
        raise ValidationAppError(
            f"{prefix} Artifact bytes are unavailable",
            details={"code": "UPSTREAM_ARTIFACT_MISSING"},
        ) from exc
    if not data or hashlib.sha256(data).hexdigest() != artifact.content_hash:
        raise ValidationAppError(
            f"{prefix} Artifact hash mismatch",
            details={"code": "ARTIFACT_HASH_MISMATCH"},
        )
    return artifact, data



def identity_priority_keyframe_prompt(
    prompt: str,
    *,
    canonical_locked_prompt: str,
) -> str:
    """Preserve the planned beat while keeping Canonical evidence reviewable."""
    return (
        f"{prompt}\n"
        f"Canonical lead identity: {canonical_locked_prompt}\n"
        "Identity reference priority: depict exactly one adult lead character. "
        "Keep the requested action, wardrobe, lighting, and setting, but make the "
        "lead's unobscured face clearly visible in a front or three-quarter view. "
        "The face must be in sharp focus and occupy a substantial, recognizable "
        "portion of the vertical frame; no profile-only face, no back-facing pose, "
        "no sunglasses, mask, hands, hair, phone, or shadow obscuring the face."
    )


async def _commit_terminal_failure(
    session: AsyncSession,
    *,
    run: NodeRun,
    error_code: str,
    error_summary: str,
    status: str = "failed",
) -> None:
    """Commit a terminal state before the Worker exception boundary rolls back."""
    from datetime import UTC, datetime

    run.status = status
    run.error_code = error_code
    run.error_summary = error_summary[:500]
    run.finished_at = datetime.now(UTC)
    run.output_summary = {
        "status": "failed",
        "error_code": error_code,
    }
    await session.flush()
    await session.commit()
    await set_node_run_rls_context(session, node_run_id=run.id)


async def claim_media_node_run(
    session: AsyncSession,
    *,
    node_run_id: UUID,
) -> NodeRun:
    """Durably claim a queued NodeRun before any Provider side effect."""
    from datetime import UTC, datetime

    run = await session.get(NodeRun, node_run_id)
    if run is None:
        raise ValidationAppError("node_run not found")
    if run.status in {"completed", "cached", "completed_after_cancel"}:
        return run

    claimed = await session.execute(
        update(NodeRun)
        .where(NodeRun.id == node_run_id, NodeRun.status == "queued")
        .values(status="running", started_at=datetime.now(UTC))
        .returning(NodeRun.id)
    )
    if claimed.scalar_one_or_none() is None:
        await session.refresh(run)
        if run.status in {"completed", "cached", "completed_after_cancel"}:
            return run
        if run.status == "running":
            resumable = await session.scalar(
                select(ProviderOperation.id).where(
                    ProviderOperation.node_run_id == run.id,
                    ProviderOperation.provider_operation_id.is_not(None),
                    ProviderOperation.status.in_({"submitted", "running", "timed_out"}),
                )
            )
            if resumable is not None:
                return run
            raise NodeRunAlreadyClaimedError()
        raise ValidationAppError(f"node_run cannot execute from status={run.status}")

    await session.commit()
    await set_node_run_rls_context(session, node_run_id=run.id)
    await session.refresh(run)
    return run

UNIFIED_PATH_VERSION = "unified-v1"


async def _unified_resolved_reference(
    session: AsyncSession,
    *,
    project: Project,
    run: NodeRun,
    role: str,
    artifact: Artifact | None,
    content_bytes: bytes | None,
    mime_type: str,
    fingerprint: str | None,
    provider_type: str,
) -> ResolvedReference:
    """Resolve one artifact reference through the provider delivery layer."""
    from app.providers.reference_delivery import resolve_reference_for_runtime

    return await resolve_reference_for_runtime(
        session,
        project=project,
        run=run,
        role=role,
        artifact=artifact,
        content_bytes=content_bytes,
        mime_type=mime_type,
        fingerprint=fingerprint,
        provider_type=provider_type,
    )


async def _execute_unified_media_node_run(
    session: AsyncSession,
    *,
    run: NodeRun,
    node: GraphNode,
    node_type: str,
    snap: dict[str, object],
    obj_store: ObjectStore,
    prompt: str,
    canonical_image_bytes: bytes | None,
    lead_identity_required: bool,
    has_canonical_binding: bool,
    canonical_artifact: Artifact | None = None,
) -> ExecuteNodeResult:
    """Stage B4: binding-driven unified execution path.

    Single-path submission: a persisted ``execution_path_version`` wins over any
    flag; resume never re-creates a remote task; ``submission_started`` without a
    remote id (crash between commit and response) is escalated to
    ``unknown_submission`` for manual reconciliation instead of a duplicate POST.
    """
    from collections.abc import Mapping
    from dataclasses import asdict
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from typing import Any, cast

    from pydantic import JsonValue

    from app.production.execution_plan import WorkbenchExecutionPlan
    from app.providers.catalog_models import ModelCatalogEntry
    from app.providers.connection_service import ProviderConnectionService
    from app.providers.execution_identity import (
        ExecutionIdentityReference,
        ExecutionIdentitySnapshot,
    )
    from app.providers.intents import (
        ArtifactReferenceIntent,
        ImageGenerationIntent,
        ModelSelectionIntent,
        VideoGenerationIntentV1,
        VideoOutputIntent,
    )
    from app.providers.manifest import ModelCapabilityManifest
    from app.providers.model_resolution import ExecutionModelResolution
    from app.providers.models import (
        ProviderConnection,
        ProviderConnectionRevision,
        ProviderModelBinding,
    )
    from app.providers.reference_delivery import approved_first_frame_for_video
    from app.providers.registry import get_plugin
    from app.providers.runtime import (
        CompiledImageRequest,
        CompiledVideoRequest,
        PollResult,
        ProviderResumeToken,
        ProviderRuntime,
        ProviderRuntimeResolver,
        SubmissionResult,
    )
    from app.providers.selection import ModelSelectionService, SelectionPlan
    from app.providers.translation import RequestTransformation
    from app.providers.workspace_credentials import runtime_connection_settings
    from app.shared.errors import ProviderRateLimitedError

    now = datetime.now(UTC)
    project = await session.scalar(select(Project).where(Project.id == run.project_id))
    if project is None:
        raise ValidationAppError("project not found for node run")
    if await set_node_run_rls_context(session, node_run_id=run.id) is None:
        raise ValidationAppError("node_run ownership context unavailable")

    op = await session.scalar(
        select(ProviderOperation)
        .where(
            ProviderOperation.node_run_id == run.id,
            ProviderOperation.execution_path_version == UNIFIED_PATH_VERSION,
        )
        .order_by(ProviderOperation.attempt_no.desc(), ProviderOperation.created_at.desc())
        .limit(1)
    )
    frozen_identity: ExecutionIdentitySnapshot | None = None
    plan: Any = None
    connection: Any = None
    connection_revision: ProviderConnectionRevision | None = None
    binding: Any = None
    entry: Any = None
    operation_identity = (
        op.selection_plan.get("execution_identity")
        if op is not None and isinstance(op.selection_plan, dict)
        else None
    )
    request_identity = (
        op.request_summary.get("execution_identity")
        if op is not None and isinstance(op.request_summary, dict)
        else None
    )
    run_identity = snap.get("execution_identity")
    persisted_identities = [
        value
        for value in (operation_identity, request_identity, run_identity)
        if value is not None
    ]
    if persisted_identities and any(
        value != persisted_identities[0] for value in persisted_identities[1:]
    ):
        raise ValidationAppError(
            "persisted execution identity evidence differs across run records",
            details={"code": "EXECUTION_IDENTITY_MISMATCH"},
        )
    raw_identity = operation_identity if operation_identity is not None else run_identity
    if op is not None and operation_identity is not None and request_identity is None:
        raise ValidationAppError(
            "ProviderOperation execution identity evidence is incomplete",
            details={"code": "EXECUTION_IDENTITY_INVALID"},
        )
    if raw_identity is not None:
        if not isinstance(raw_identity, dict):
            raise ValidationAppError(
                "persisted execution identity is malformed",
                details={"code": "EXECUTION_IDENTITY_INVALID"},
            )
        try:
            frozen_identity = ExecutionIdentitySnapshot.model_validate(raw_identity)
        except ValueError as exc:
            raise ValidationAppError(
                "persisted execution identity is invalid",
                details={"code": "EXECUTION_IDENTITY_INVALID"},
            ) from exc

    # Workbench NodeRuns persist a frozen P4 plan before a ProviderOperation is
    # created.  Parse it once at the worker boundary so execution can consume
    # that exact ExecutionModelResolution rather than asking the selection
    # service to choose from mutable profile state again.
    raw_workbench_plan = snap.get("workbench_plan")
    workbench_plan: WorkbenchExecutionPlan | None = None
    if raw_workbench_plan is not None:
        if not isinstance(raw_workbench_plan, dict):
            raise ValidationAppError(
                "professional workbench plan is malformed",
                details={"code": "EXECUTION_PLAN_INVALID"},
            )
        try:
            workbench_plan = WorkbenchExecutionPlan.model_validate(raw_workbench_plan)
        except ValueError as exc:
            raise ValidationAppError(
                "professional workbench plan is invalid",
                details={"code": "EXECUTION_PLAN_INVALID"},
            ) from exc

    create_status = "created"
    remote = ""
    runtime: ProviderRuntime | None = None
    resume: ProviderResumeToken | None = None
    initial_status = "queued"
    synchronous_image = False
    result: SubmissionResult | None = None
    workbench_planned_references = (
        list(workbench_plan.planned_references) if workbench_plan is not None else []
    )

    resubmit = bool(op is not None and op.status == "rejected" and not op.provider_operation_id)
    if op is not None and not resubmit:
        # A crash between the submission_started commit and the remote-id write
        # leaves an op with no remote id. Its outcome is unknown; escalate to
        # manual reconciliation instead of risking a duplicate POST.
        if op.status == "submission_started" and not op.provider_operation_id:
            op.status = "unknown_submission"
            op.error_code = "PROVIDER_SUBMISSION_UNKNOWN"
            op.error_summary = (
                "submission_started with no remote id: outcome unknown; "
                "manual reconciliation required"
            )
            op.completed_at = now
            await _commit_terminal_failure(
                session,
                run=run,
                error_code="PROVIDER_SUBMISSION_UNKNOWN",
                error_summary=op.error_summary,
            )
            raise ValidationAppError("PROVIDER_SUBMISSION_UNKNOWN")
        # Resume only. Never create a second remote task. Rebuild the runtime
        # exclusively from the persisted execution identity.
        if frozen_identity is not None:
            runtime = await ProviderRuntimeResolver(
                session
            ).resume_runtime_for_identity(
                identity=frozen_identity,
                workspace_id=project.workspace_id,
                operation=op,
            )
        else:
            connection = (
                await session.get(ProviderConnection, op.connection_id)
                if op.connection_id is not None
                else None
            )
            if connection is None:
                raise ValidationAppError("unified operation connection is missing")
            plugin = get_plugin(connection.provider_type, connection.protocol_profile)
            cfg = await runtime_connection_settings(session, connection=connection)
            runtime = await ProviderRuntimeResolver(session).resume_runtime(
                plugin=plugin, connection=connection, settings=cfg
            )
        if op.resume_token is not None:
            resume = ProviderResumeToken.model_validate(op.resume_token)
        remote = str(op.provider_operation_id or "")
        create_status = "resumed"
        initial_status = "running"

    if op is None or resubmit:
        # New submission. Resolve via the shared selection engine.
        frozen_binding_id = (
            frozen_identity.provider_model_binding_id
            if frozen_identity is not None
            else None
        )
        if frozen_binding_id is None and snap.get("model_binding_id") is not None:
            try:
                frozen_binding_id = UUID(str(snap["model_binding_id"]))
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValidationAppError(
                    "frozen model binding is invalid",
                    details={"code": "MODEL_BINDING_INVALID"},
                ) from exc
        first_frame: Artifact | None = None
        frame_bytes: bytes | None = None
        image_intent: ImageGenerationIntent | None = None
        video_intent: VideoGenerationIntentV1 | None = None
        if node_type == "keyframe":
            workbench_image_reference = next(
                (
                    reference
                    for reference in workbench_planned_references
                    if reference.role == "reference_image"
                    and reference.artifact_id is not None
                    and reference.delivery != "unsupported"
                ),
                None,
            )
            canonical_artifact_id = (
                workbench_image_reference.artifact_id
                if workbench_image_reference is not None
                else snap.get("canonical_artifact_id")
            )
            reference_uuid: UUID | None = None
            if canonical_artifact_id is not None:
                try:
                    reference_uuid = UUID(str(canonical_artifact_id))
                except (TypeError, ValueError, AttributeError):
                    reference_uuid = None
            raw_ratio = str(snap.get("aspect_ratio") or project.aspect_ratio or "")
            image_ratio: Literal["9:16", "16:9"] | None = (
                "9:16" if raw_ratio == "9:16" else "16:9" if raw_ratio == "16:9" else None
            )
            if image_ratio is None:
                raise ValidationAppError(
                    "unified image request has an unsupported aspect ratio",
                    details={"code": "ASPECT_RATIO_UNSUPPORTED", "aspect_ratio": raw_ratio},
                )
            image_intent = ImageGenerationIntent(
                prompt=prompt,
                size=None,
                aspect_ratio=image_ratio,
                seed=None,
                reference_artifact_id=reference_uuid,
                reference_fingerprint=(
                    workbench_image_reference.fingerprint
                    if workbench_image_reference is not None
                    else hashlib.sha256(canonical_image_bytes).hexdigest()
                    if canonical_image_bytes is not None
                    else None
                ),
                reference_mime=(
                    workbench_image_reference.mime_type
                    if workbench_image_reference is not None
                    else str(snap.get("canonical_mime_type") or "image/png")
                ),
                selection=ModelSelectionIntent(
                    mode="explicit_binding",
                    model_binding_id=frozen_binding_id,
                ),
            )
        else:
            first_frame = await approved_first_frame_for_video(session, video_run=run)
            try:
                frame_bytes = await obj_store.get_bytes(object_key=first_frame.object_key)
            except Exception:
                frame_bytes = None
            if not frame_bytes:
                raise ValidationAppError(
                    "UPSTREAM_ARTIFACT_MISSING: approved first-frame bytes unavailable "
                    "for video I2V"
                )
            raw_duration = snap.get("duration_seconds")
            try:
                duration_seconds = round(float(str(raw_duration)))
            except (TypeError, ValueError):
                duration_seconds = 0
            if duration_seconds <= 0:
                raise ValidationAppError(
                    "unified video request has no valid duration",
                    details={"code": "DURATION_REQUIRED"},
                )
            raw_ratio = str(snap.get("aspect_ratio") or project.aspect_ratio or "")
            video_ratio: Literal["9:16", "16:9"] | None = (
                "9:16" if raw_ratio == "9:16" else "16:9" if raw_ratio == "16:9" else None
            )
            if video_ratio is None:
                raise ValidationAppError(
                    "unified video request has an unsupported aspect ratio",
                    details={"code": "ASPECT_RATIO_UNSUPPORTED", "aspect_ratio": raw_ratio},
                )
            planned_video_references = [
                reference
                for reference in workbench_planned_references
                if reference.artifact_id is not None
                and reference.role is not None
                and reference.delivery != "unsupported"
            ]
            planned_first_frame = next(
                (
                    reference
                    for reference in planned_video_references
                    if reference.role == "first_frame"
                ),
                None,
            )
            if (
                planned_first_frame is not None
                and planned_first_frame.artifact_id != first_frame.id
            ):
                raise ValidationAppError(
                    "frozen Workbench first_frame does not match the formal keyframe",
                    details={"code": "FORMAL_KEYFRAME_SNAPSHOT_MISMATCH"},
                )
            intent_references = [
                ArtifactReferenceIntent(
                    artifact_id=cast(UUID, reference.artifact_id),
                    role=cast(
                        Literal[
                            "first_frame",
                            "last_frame",
                            "reference_image",
                            "reference_video",
                            "reference_audio",
                        ],
                        reference.role,
                    ),
                    required=True,
                )
                for reference in planned_video_references
            ]
            if not intent_references:
                intent_references = [
                    ArtifactReferenceIntent(
                        artifact_id=first_frame.id,
                        role="first_frame",
                        required=True,
                    )
                ]
            video_intent = VideoGenerationIntentV1(
                prompt=prompt,
                output=VideoOutputIntent(
                    aspect_ratio=video_ratio,
                    duration_seconds=duration_seconds,
                    generate_audio=False,
                ),
                references=intent_references,
                selection=ModelSelectionIntent(
                    mode="explicit_binding",
                    model_binding_id=frozen_binding_id,
                ),
            )

        service = ModelSelectionService(session)
        raw_frozen_selection = (
            op.selection_plan
            if op is not None and isinstance(op.selection_plan, dict)
            else snap.get("selection_plan")
        )
        if frozen_identity is not None:
            if not isinstance(raw_frozen_selection, dict):
                raise ValidationAppError(
                    "frozen execution selection is missing",
                    details={"code": "EXECUTION_IDENTITY_INVALID"},
                )
            selection_snapshot = json.loads(json.dumps(raw_frozen_selection))
            raw_resolution = selection_snapshot.get("execution_model_resolution")
            try:
                frozen_resolution = ExecutionModelResolution.model_validate(raw_resolution)
            except (TypeError, ValueError) as exc:
                raise ValidationAppError(
                    "frozen model resolution is invalid",
                    details={"code": "EXECUTION_IDENTITY_INVALID"},
                ) from exc
            if (
                frozen_resolution.provider_model_binding_id
                != frozen_identity.provider_model_binding_id
                or frozen_resolution.resolved_model_id
                != frozen_identity.resolved_model
                or frozen_resolution.manifest_hash != frozen_identity.manifest_hash
                or frozen_resolution.invoke_model_value
                != frozen_identity.invoke_model_value
            ):
                raise ValidationAppError(
                    "frozen model resolution does not match execution identity",
                    details={"code": "EXECUTION_IDENTITY_MISMATCH"},
                )
            resolved = await ProviderRuntimeResolver(session).resolve_runtime_for_identity(
                identity=frozen_identity,
                workspace_id=project.workspace_id,
                operation=op,
            )
            if (
                resolved.binding is None
                or resolved.catalog_entry is None
                or resolved.invoke_model_value is None
            ):
                raise ValidationAppError(
                    "frozen runtime resolution returned incomplete identity",
                    details={"code": "EXECUTION_IDENTITY_MODEL_UNAVAILABLE"},
                )
            connection = resolved.connection
            binding = resolved.binding
            entry = resolved.catalog_entry
            invoke_model_value = resolved.invoke_model_value
            connection_revision = await session.get(
                ProviderConnectionRevision,
                frozen_identity.connection_revision_id,
            )
            if (
                connection_revision is None
                or connection_revision.connection_id != frozen_identity.connection_id
                or connection_revision.credential_revision_id
                != frozen_identity.credential_revision_id
            ):
                raise ValidationAppError(
                    "frozen provider connection revision is unavailable",
                    details={"code": "EXECUTION_IDENTITY_REVISION_UNAVAILABLE"},
                )
            if (
                resolved.manifest_hash != frozen_identity.manifest_hash
                or resolved.invoke_model_value != frozen_identity.invoke_model_value
            ):
                raise ValidationAppError(
                    "runtime resolution changed the frozen execution identity",
                    details={"code": "EXECUTION_IDENTITY_MISMATCH"},
                )
            provider_type = connection.provider_type
            protocol_profile = connection.protocol_profile
            runtime = resolved.runtime
            plan = SimpleNamespace(
                model_binding_id=frozen_identity.provider_model_binding_id,
                provider_type=provider_type,
                protocol_profile=protocol_profile,
                catalog_entry_id=frozen_identity.catalog_entry_id,
                model_id=frozen_identity.resolved_model,
                invoke_model_value=frozen_identity.invoke_model_value,
                connection_id=frozen_identity.connection_id,
                execution_model_resolution=frozen_resolution,
                mode_id=frozen_identity.mode_id,
                manifest_hash=frozen_identity.manifest_hash,
            )
            pricing_currency = _binding_pricing_currency(binding, required=False)
        else:
            if workbench_plan is not None:
                # P4 Workbench plans are already frozen at queue time.  Their
                # ExecutionModelResolution and connection/credential revision
                # must be consumed verbatim; re-running ModelSelectionService
                # here could silently observe a newer profile binding.
                frozen_resolution = workbench_plan.resolved_model
                if (
                    frozen_resolution.status != "RESOLVED"
                    or frozen_resolution.provider_model_binding_id is None
                    or frozen_resolution.provider_connection_id is None
                    or frozen_resolution.catalog_entry_id is None
                    or frozen_resolution.provider_connection_revision_id is None
                    or frozen_resolution.credential_revision_id is None
                    or workbench_plan.connection_revision_id
                    != frozen_resolution.provider_connection_revision_id
                    or workbench_plan.credential_revision_id
                    != frozen_resolution.credential_revision_id
                ):
                    raise ValidationAppError(
                        "professional workbench plan has incomplete frozen identity",
                        details={"code": "EXECUTION_IDENTITY_INVALID"},
                    )
                if (
                    frozen_binding_id is not None
                    and frozen_resolution.provider_model_binding_id != frozen_binding_id
                ):
                    raise ValidationAppError(
                        "professional workbench plan changed its model binding",
                        details={"code": "MODEL_BINDING_SNAPSHOT_MISMATCH"},
                    )
                connection = await session.get(
                    ProviderConnection, frozen_resolution.provider_connection_id
                )
                binding = await session.get(
                    ProviderModelBinding, frozen_resolution.provider_model_binding_id
                )
                entry = await session.get(
                    ModelCatalogEntry, frozen_resolution.catalog_entry_id
                )
                if connection is None or binding is None or entry is None:
                    raise ValidationAppError(
                        "professional workbench plan references missing identity",
                        details={"code": "MODEL_BINDING_MISSING"},
                    )
                if (
                    connection.workspace_id != project.workspace_id
                    or binding.workspace_id != project.workspace_id
                    or binding.connection_id != connection.id
                    or connection.enabled is not True
                ):
                    raise ValidationAppError(
                        "professional workbench provider identity is unavailable",
                        details={"code": "MODEL_RUNTIME_IDENTITY_INVALID"},
                    )
                provider_type = connection.provider_type
                protocol_profile = connection.protocol_profile
                invoke_model_value = binding.invoke_model_value
                if (
                    invoke_model_value is None
                    or frozen_resolution.resolved_model_id is None
                    or frozen_resolution.manifest_hash is None
                    or frozen_resolution.model_revision is None
                    or frozen_resolution.provider_connection_id != connection.id
                    or frozen_resolution.invoke_model_value != invoke_model_value
                    or frozen_resolution.resolved_model_id
                    != f"{connection.provider_type}/{binding.model_id}"
                    or frozen_resolution.manifest_hash != entry.contract_manifest_hash
                    or frozen_resolution.model_revision != entry.model_revision
                ):
                    raise ValidationAppError(
                        "professional workbench model identity is unavailable",
                        details={"code": "MODEL_RUNTIME_IDENTITY_INVALID"},
                    )
                connection_revision = await session.get(
                    ProviderConnectionRevision,
                    frozen_resolution.provider_connection_revision_id,
                )
                if (
                    connection_revision is None
                    or connection_revision.connection_id != connection.id
                    or connection_revision.provider_type != connection.provider_type
                    or connection_revision.protocol_profile != connection.protocol_profile
                    or connection_revision.credential_revision_id
                    != frozen_resolution.credential_revision_id
                ):
                    raise ValidationAppError(
                        "professional workbench connection revision is unavailable",
                        details={"code": "EXECUTION_IDENTITY_REVISION_UNAVAILABLE"},
                    )
                pricing_currency = _binding_pricing_currency(binding, required=False)
                resolved = await ProviderRuntimeResolver(
                    session
                ).resolve_runtime_for_resolution(
                    resolution=frozen_resolution,
                    workspace_id=project.workspace_id,
                    connection_revision_id=connection_revision.id,
                    credential_revision_id=connection_revision.credential_revision_id,
                )
                if (
                    resolved.binding is None
                    or resolved.catalog_entry is None
                    or resolved.invoke_model_value is None
                ):
                    raise ValidationAppError(
                        "professional workbench runtime resolution is incomplete",
                        details={"code": "MODEL_RUNTIME_IDENTITY_INVALID"},
                    )
                connection = resolved.connection
                binding = resolved.binding
                entry = resolved.catalog_entry
                invoke_model_value = resolved.invoke_model_value
                runtime = resolved.runtime
                provider_type = connection.provider_type
                protocol_profile = connection.protocol_profile
                plan = SelectionPlan(
                    intent_hash=workbench_plan.plan_fingerprint or "",
                    purpose="keyframe" if node_type == "keyframe" else "video",
                    mode=workbench_plan.mode_id,
                    mode_id=workbench_plan.mode_id,
                    model_binding_id=frozen_resolution.provider_model_binding_id,
                    provider_type=provider_type,
                    protocol_profile=protocol_profile,
                    catalog_entry_id=frozen_resolution.catalog_entry_id,
                    model_id=binding.model_id,
                    invoke_model_value=invoke_model_value,
                    connection_id=connection.id,
                    execution_model_resolution=frozen_resolution,
                    manifest_hash=frozen_resolution.manifest_hash,
                    compiled_by=entry.catalog_source,
                )
                raw_frozen_selection = snap.get("selection_plan")
                if not isinstance(raw_frozen_selection, dict):
                    raise ValidationAppError(
                        "professional workbench selection snapshot is missing",
                        details={"code": "EXECUTION_IDENTITY_INVALID"},
                    )
                selection_snapshot = json.loads(json.dumps(raw_frozen_selection))
                selection_snapshot["execution_model_resolution"] = (
                    frozen_resolution.model_dump(mode="json")
                )
            else:
                if node_type == "keyframe":
                    assert image_intent is not None
                    plan = await service.select_image(
                        project=project,
                        intent=image_intent,
                    )
                else:
                    assert video_intent is not None
                    plan = await service.select_video(
                        project=project,
                        intent=video_intent,
                    )
                if frozen_binding_id is not None and plan.model_binding_id != frozen_binding_id:
                    raise ValidationAppError(
                        "unified selection changed the frozen model binding",
                        details={"code": "MODEL_BINDING_SNAPSHOT_MISMATCH"},
                    )
                selection_snapshot = json.loads(json.dumps(asdict(plan), default=str))
                selection_snapshot["execution_model_resolution"] = (
                    plan.execution_model_resolution.model_dump(mode="json")
                )
                invoke_model_value = plan.invoke_model_value
                provider_type = plan.provider_type
                protocol_profile = plan.protocol_profile
                if invoke_model_value is None or provider_type is None or protocol_profile is None:
                    raise ValidationAppError("unified selection has no model/provider identity")
                connection = await session.get(ProviderConnection, plan.connection_id)
                binding = await session.get(ProviderModelBinding, plan.model_binding_id)
                entry = await session.get(ModelCatalogEntry, plan.catalog_entry_id)
                if connection is None or binding is None or entry is None:
                    raise ValidationAppError(
                        "unified selection references missing connection/binding/catalog",
                        details={"code": "MODEL_BINDING_MISSING"},
                    )
                pricing_currency = _binding_pricing_currency(binding, required=False)
                connection_revision = await ProviderConnectionService(
                    session
                ).current_connection_revision(connection=connection)
                if connection_revision is None:
                    raise ValidationAppError(
                        "unified selection has no provider connection revision",
                        details={"code": "EXECUTION_IDENTITY_REVISION_UNAVAILABLE"},
                    )
                resolved = await ProviderRuntimeResolver(
                    session
                ).resolve_runtime_for_resolution(
                    resolution=plan.execution_model_resolution,
                    workspace_id=project.workspace_id,
                    connection_revision_id=connection_revision.id,
                    credential_revision_id=connection_revision.credential_revision_id,
                )
                if (
                    resolved.binding is None
                    or resolved.catalog_entry is None
                    or resolved.invoke_model_value is None
                ):
                    raise ValidationAppError(
                        "binding-based runtime resolution returned incomplete identity",
                        details={"code": "MODEL_RUNTIME_IDENTITY_INVALID"},
                    )
                connection = resolved.connection
                binding = resolved.binding
                entry = resolved.catalog_entry
                invoke_model_value = resolved.invoke_model_value
                provider_type = connection.provider_type
                protocol_profile = connection.protocol_profile
                runtime = resolved.runtime

        if frozen_identity is None:
            snap = {
                **snap,
                "model_binding_id": str(plan.model_binding_id),
                "execution_model_resolution": plan.execution_model_resolution.model_dump(
                    mode="json"
                ),
                "selection_plan": selection_snapshot,
            }
            run.input_snapshot = snap
            await session.flush()
        manifest = ModelCapabilityManifest.model_validate(entry.capability_manifest_json)
        # Dispatch-time multi-subject fail-closed gate (G-WF-05 / G-WF-06).
        # The keyframe must not be submitted when the shot's frozen participation
        # plan carries more visible controlled subjects than this model's catalog
        # manifest can bind as reference images.  A silent single-reference POST
        # would prove only character A survived (the banned "只发角色 A 后宣称
        # multi-character PASS" outcome).  Planning surfaces are advisory; this is
        # the authoritative boundary and it raises before any Provider request.
        # The frozen plan lives in ``Shot.director_state``; we read it here, not
        # from the snapshot, because the snapshot is deliberately minimized.
        if node_type == "keyframe":
            from app.assets.models import Shot as _ShotModel
            from app.director.workflows.reference_capability import dispatch_capability_gate

            participation_snapshot: Mapping[str, object] = {}
            raw_shot_id = snap.get("shot_id")
            if isinstance(raw_shot_id, str) and raw_shot_id:
                try:
                    shot_row = await session.get(_ShotModel, UUID(raw_shot_id))
                except (ValueError, TypeError):
                    # A non-UUID (or missing) shot id means the run is not backed
                    # by a real shot with a participation plan; there is nothing to
                    # gate, so dispatch proceeds exactly as before.
                    shot_row = None
                if shot_row is not None:
                    participation_snapshot = {
                        "workflow_participations": (
                            shot_row.director_state or {}
                        ).get("workflow_participations")
                    }
            gate = dispatch_capability_gate(
                snapshot=participation_snapshot,
                operations=cast(Mapping[str, object], manifest.operations),
            )
            if gate is not None:
                await _commit_terminal_failure(
                    session,
                    run=run,
                    error_code="MULTI_SUBJECT_UNSUPPORTED",
                    error_summary=gate.reason,
                )
                raise ValidationAppError(
                    f"MULTI_SUBJECT_UNSUPPORTED: {gate.reason}",
                    details={
                        "code": "MULTI_SUBJECT_UNSUPPORTED",
                        "required_subject_references": gate.required_subject_references,
                        "max_subject_references": gate.max_subject_references,
                    },
                )
        compiled: CompiledImageRequest | CompiledVideoRequest
        identity_references: list[ExecutionIdentityReference] = []

        async def _load_workbench_reference(
            reference: Any,
            *,
            existing_artifact: Artifact | None = None,
            existing_bytes: bytes | None = None,
        ) -> ResolvedReference:
            """Load one frozen Workbench artifact for the existing compiler.

            The plan has already validated project/asset lineage.  At the
            worker boundary we additionally verify the immutable storage hash
            before handing bytes/URL transport to the provider adapter, so a
            later Asset/Binding change cannot alter a queued run.
            """

            artifact_id = getattr(reference, "artifact_id", None)
            role = getattr(reference, "role", None)
            if artifact_id is None or not isinstance(role, str) or not role:
                raise ValidationAppError(
                    "frozen Workbench reference identity is incomplete",
                    details={"code": "REFERENCE_IDENTITY_INVALID"},
                )
            artifact = existing_artifact or await session.get(Artifact, artifact_id)
            if (
                artifact is None
                or artifact.project_id != project.id
                or artifact.storage_state != "available"
                or artifact.deleted_at is not None
            ):
                raise ValidationAppError(
                    "frozen Workbench reference artifact is unavailable",
                    details={"code": "REFERENCE_ARTIFACT_REQUIRED"},
                )
            frozen_mime = getattr(reference, "mime_type", None)
            frozen_fingerprint = getattr(reference, "fingerprint", None)
            if frozen_mime and frozen_mime != artifact.mime_type:
                raise ValidationAppError(
                    "frozen Workbench reference MIME does not match the artifact",
                    details={"code": "REFERENCE_METADATA_MISMATCH"},
                )
            if frozen_fingerprint and frozen_fingerprint != artifact.content_hash:
                raise ValidationAppError(
                    "frozen Workbench reference fingerprint does not match the artifact",
                    details={"code": "REFERENCE_METADATA_MISMATCH"},
                )
            content_bytes: bytes | None = None
            content_bytes = existing_bytes if artifact.id == artifact_id else None
            if content_bytes is None:
                try:
                    content_bytes = await obj_store.get_bytes(
                        object_key=artifact.object_key
                    )
                except Exception as exc:
                    raise ValidationAppError(
                        "frozen Workbench reference bytes are unavailable",
                        details={"code": "REFERENCE_ARTIFACT_REQUIRED"},
                    ) from exc
            if (
                not content_bytes
                or hashlib.sha256(content_bytes).hexdigest() != artifact.content_hash
            ):
                raise ValidationAppError(
                    "frozen Workbench reference hash mismatch",
                    details={"code": "ARTIFACT_HASH_MISMATCH"},
                )
            return await _unified_resolved_reference(
                session,
                project=project,
                run=run,
                role=role,
                artifact=artifact,
                content_bytes=content_bytes,
                mime_type=str(getattr(reference, "mime_type", None) or artifact.mime_type),
                fingerprint=str(getattr(reference, "fingerprint", None) or artifact.content_hash),
                provider_type=provider_type,
            )

        if node_type == "keyframe":
            image_compiler = resolved.image_compiler
            if image_compiler is None:
                raise ValidationAppError("unified plugin has no image compiler")
            assert image_intent is not None
            refs: list[ResolvedReference] = []
            if workbench_planned_references:
                refs = [
                    await _load_workbench_reference(reference)
                    for reference in workbench_planned_references
                    if reference.delivery != "unsupported"
                ]
            elif has_canonical_binding and canonical_image_bytes is not None:
                refs.append(
                    await _unified_resolved_reference(
                        session,
                        project=project,
                        run=run,
                        role="reference_image",
                        artifact=canonical_artifact,
                        content_bytes=canonical_image_bytes,
                        mime_type=str(snap.get("canonical_mime_type") or "image/png"),
                        fingerprint=hashlib.sha256(canonical_image_bytes).hexdigest(),
                        provider_type=provider_type,
                    )
                )
            identity_references = [
                ExecutionIdentityReference(
                    role=reference.role,
                    artifact_id=reference.artifact_id,
                    mime_type=reference.mime_type,
                    fingerprint=reference.fingerprint,
                )
                for reference in refs
            ]
            compiled = await image_compiler.compile(
                image_intent,
                manifest,
                refs,
                invoke_model_value=invoke_model_value,
            )
        else:
            assert first_frame is not None and frame_bytes is not None
            assert video_intent is not None
            video_compiler = resolved.video_compiler
            if video_compiler is None:
                raise ValidationAppError("unified plugin has no video compiler")
            if workbench_planned_references:
                video_references = [
                    await _load_workbench_reference(
                        reference,
                        existing_artifact=first_frame
                        if reference.artifact_id == first_frame.id
                        else None,
                        existing_bytes=frame_bytes
                        if reference.artifact_id == first_frame.id
                        else None,
                    )
                    for reference in workbench_planned_references
                    if reference.delivery != "unsupported"
                ]
            else:
                # Historical unified runs without a P4 plan retain the formal
                # first-frame path exactly as before.
                video_references = [
                    await _unified_resolved_reference(
                        session,
                        project=project,
                        run=run,
                        role="first_frame",
                        artifact=first_frame,
                        content_bytes=frame_bytes,
                        mime_type=first_frame.mime_type or "image/png",
                        fingerprint=first_frame.content_hash,
                        provider_type=provider_type,
                    )
                ]
            identity_references = [
                ExecutionIdentityReference(
                    role=reference.role,
                    artifact_id=reference.artifact_id,
                    mime_type=reference.mime_type,
                    fingerprint=reference.fingerprint,
                )
                for reference in video_references
            ]
            compiled = await video_compiler.compile(
                video_intent,
                manifest,
                video_references,
                invoke_model_value=invoke_model_value,
            )

        if workbench_planned_references:
            expected_reference_ids = [
                reference.artifact_id
                for reference in workbench_planned_references
                if reference.delivery != "unsupported" and reference.artifact_id is not None
            ]
            if list(compiled.reference_artifact_ids) != expected_reference_ids:
                raise ValidationAppError(
                    "Provider compiler did not preserve the frozen Workbench references",
                    details={"code": "REFERENCE_COMPILER_MISMATCH"},
                )

        kind = node_type
        fingerprint = hashlib.sha256(
            f"{kind}:{prompt}:{compiled.model_dump_json()}".encode()
        ).hexdigest()
        prompt_fingerprint = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if image_intent is not None:
            requested_options: dict[str, object] = {
                "size": image_intent.size,
                "aspect_ratio": image_intent.aspect_ratio,
            }
            effective_options: dict[str, object] = {
                "size": compiled.safe_request_summary.get("size"),
                "aspect_ratio": compiled.safe_request_summary.get("aspect_ratio"),
            }
        else:
            assert video_intent is not None
            requested_options = {
                "aspect_ratio": video_intent.output.aspect_ratio,
                "duration_seconds": video_intent.output.duration_seconds,
                "generate_audio": video_intent.output.generate_audio,
            }
            effective_options = {
                "aspect_ratio": compiled.safe_request_summary.get("aspect_ratio"),
                "duration_seconds": compiled.safe_request_summary.get("duration_seconds"),
                "frame_rate": compiled.safe_request_summary.get("frame_rate"),
                "num_frames": compiled.safe_request_summary.get("num_frames"),
                "generate_audio": compiled.safe_request_summary.get("native_audio"),
            }
        effective_request = {
            "operation": compiled.operation,
            "model_id": compiled.model_id,
            "prompt_fingerprint": prompt_fingerprint,
            "common_options": effective_options,
            "reference_artifact_ids": [
                str(value) for value in compiled.reference_artifact_ids
            ],
            "reference_fingerprints": list(compiled.reference_fingerprints),
        }
        raw_transformations = compiled.safe_request_summary.get(
            "translation_transformations"
        )
        if raw_transformations is None:
            transformations: list[dict[str, object]] = []
        elif isinstance(raw_transformations, list):
            transformations = [
                RequestTransformation.model_validate(item).model_dump(mode="json")
                for item in raw_transformations
            ]
        else:
            raise ValidationAppError(
                "compiler returned malformed translation evidence",
                details={"code": "COMPILER_TRANSLATION_EVIDENCE_INVALID"},
            )
        translation_report = {
            "requested_options": requested_options,
            "effective_options": effective_options,
            "transformations": transformations,
            "dropped_options": [],
            "warnings": [],
        }
        if frozen_identity is None:
            identity = ExecutionIdentitySnapshot(
                requested_model=(
                    plan.execution_model_resolution.requested_model_id or plan.model_id
                ),
                resolved_model=(
                    plan.execution_model_resolution.resolved_model_id
                    or plan.model_id
                    or invoke_model_value
                ),
                resolution_source=plan.execution_model_resolution.source,
                provider_model_binding_id=binding.id,
                catalog_entry_id=entry.id,
                model_revision=entry.model_revision,
                manifest_hash=entry.contract_manifest_hash,
                invoke_model_value=invoke_model_value,
                connection_id=connection.id,
                connection_revision_id=connection_revision.id,
                credential_revision_id=connection_revision.credential_revision_id,
                capability=plan.execution_model_resolution.capability.value,
                mode_id=plan.mode_id,
                effective_options=cast(dict[str, JsonValue], effective_options),
                resolved_references=identity_references,
                translation_report=cast(dict[str, JsonValue], translation_report),
                request_fingerprint=fingerprint,
            )
            # The selection resolver above is allowed to inspect mutable
            # configuration, but the network boundary must consume the exact
            # immutable revision captured in the identity.  Rebuild the
            # runtime from that identity before persisting submission_started
            # so an endpoint/credential update between selection and submit
            # cannot change the first Provider request.
            resolved = await ProviderRuntimeResolver(
                session
            ).resolve_runtime_for_identity(
                identity=identity,
                workspace_id=project.workspace_id,
            )
            runtime = resolved.runtime
            connection = resolved.connection
            binding = resolved.binding
            entry = resolved.catalog_entry
            if binding is None or entry is None:
                raise ValidationAppError(
                    "frozen runtime resolution returned incomplete identity",
                    details={"code": "EXECUTION_IDENTITY_MODEL_UNAVAILABLE"},
                )
        else:
            candidate_identity = ExecutionIdentitySnapshot(
                requested_model=frozen_identity.requested_model,
                resolved_model=frozen_identity.resolved_model,
                resolution_source=frozen_identity.resolution_source,
                provider_model_binding_id=frozen_identity.provider_model_binding_id,
                catalog_entry_id=frozen_identity.catalog_entry_id,
                model_revision=frozen_identity.model_revision,
                manifest_hash=frozen_identity.manifest_hash,
                invoke_model_value=frozen_identity.invoke_model_value,
                connection_id=frozen_identity.connection_id,
                connection_revision_id=frozen_identity.connection_revision_id,
                credential_revision_id=frozen_identity.credential_revision_id,
                capability=frozen_identity.capability,
                mode_id=frozen_identity.mode_id,
                effective_options=cast(dict[str, JsonValue], effective_options),
                resolved_references=identity_references,
                translation_report=cast(dict[str, JsonValue], translation_report),
                request_fingerprint=fingerprint,
            )
            if candidate_identity != frozen_identity:
                raise ValidationAppError(
                    "retry changed its frozen execution identity",
                    details={"code": "EXECUTION_IDENTITY_MISMATCH"},
                )
            identity = frozen_identity
        if connection_revision is None:
            raise ValidationAppError(
                "unified execution has no frozen provider connection revision",
                details={"code": "EXECUTION_IDENTITY_REVISION_UNAVAILABLE"},
            )
        identity_json = identity.model_dump(mode="json")
        selection_snapshot["execution_identity"] = identity_json
        snap = {
            **snap,
            "execution_identity": identity_json,
        }
        if frozen_identity is not None:
            snap["selection_plan"] = selection_snapshot
        run.input_snapshot = snap
        # Revalidate after request compilation, immediately before persisting
        # the submission marker and making the paid call.
        if op is None:
            op = ProviderOperation(
                node_run_id=run.id,
                attempt_no=run.attempt_no,
                purpose="primary",
                operation_kind=f"{node_type}.generate",
                actual_provider=provider_type,
                actual_model=invoke_model_value,
                protocol_profile=protocol_profile,
                request_fingerprint=fingerprint,
                status="submission_started",
                request_summary=normalize_request_summary({
                    "kind": kind,
                    "execution_path": UNIFIED_PATH_VERSION,
                    "intent": (
                        image_intent.model_dump(mode="json")
                        if image_intent is not None
                        else video_intent.model_dump(mode="json")
                        if video_intent is not None
                        else {}
                    ),
                    "compiled_request": compiled.safe_request_summary,
                    "effective_request": effective_request,
                    "translation_report": translation_report,
                    "reference_artifact_ids": [
                        str(value) for value in compiled.reference_artifact_ids
                    ],
                    "reference_fingerprints": list(compiled.reference_fingerprints),
                    "frozen_model_binding_id": str(binding.id),
                    "provider_connection_revision_id": str(connection_revision.id),
                    "execution_identity": identity_json,
                    "capability_manifest_hash": plan.manifest_hash,
                    "execution_model_resolution": plan.execution_model_resolution.model_dump(
                        mode="json"
                    ),
                }),
                response_summary={},
                submitted_at=now,
                connection_id=connection.id,
                provider_connection_revision_id=connection_revision.id,
                credential_revision_id=connection_revision.credential_revision_id,
                model_binding_id=binding.id,
                catalog_entry_id=entry.id,
                capability_manifest_hash=plan.manifest_hash,
                selection_plan=selection_snapshot,
                execution_path_version=UNIFIED_PATH_VERSION,
                currency=pricing_currency or "USD",
            )
            session.add(op)
        else:
            # Rejected earlier without a remote task: retry reuses the same op.
            op.status = "submission_started"
            op.error_code = None
            op.error_summary = None
            op.provider_operation_id = None
            op.remote_secondary_id = None
            op.request_fingerprint = fingerprint
            op.response_summary = {}
            op.completed_at = None
            op.resume_token = None
            op.currency = pricing_currency or op.currency
        await session.flush()
        await session.commit()
        await set_node_run_rls_context(session, node_run_id=run.id)

        if isinstance(compiled, CompiledImageRequest):
            result = await resolved.runtime.submit_image(compiled)
        else:
            result = await resolved.runtime.submit_video(compiled)
        if result.status == "unknown_submission":
            op.status = "unknown_submission"
            op.error_code = str(result.error_code or "PROVIDER_SUBMISSION_UNKNOWN")
            op.error_summary = _unknown_submission_error_summary(result.error)
            op.completed_at = datetime.now(UTC)
            await _commit_terminal_failure(
                session,
                run=run,
                error_code="PROVIDER_SUBMISSION_UNKNOWN",
                error_summary=op.error_summary,
            )
            raise ValidationAppError("PROVIDER_SUBMISSION_UNKNOWN")
        if result.status in {"failed", "error", "cancelled"}:
            error_text = str(result.error or "provider rejected task creation")[:500]
            if result.error_code == "PROVIDER_RATE_LIMITED":
                raw_retry_after = getattr(result, "retry_after_seconds", None)
                try:
                    retry_after = float(raw_retry_after) if raw_retry_after else 5.0
                except (TypeError, ValueError):
                    retry_after = 5.0
                # The provider explicitly refused with 429 and did not create a
                # remote task. Mark the op rejected and COMMIT so a worker
                # rollback cannot leave it dangling as submission_started; the
                # scheduler requeues the run and the retry resubmits.
                op.status = "rejected"
                op.error_code = "PROVIDER_RATE_LIMITED"
                op.error_summary = error_text
                op.completed_at = datetime.now(UTC)
                await session.commit()
                raise ProviderRateLimitedError(retry_after_seconds=retry_after)
            op.status = "failed"
            op.error_code = "PROVIDER_CREATE_FAILED"
            op.error_summary = error_text
            failure_summary: dict[str, object] = {
                "create_status": result.status,
                "create_error": error_text[:300],
            }
            if result.error_code:
                failure_summary["provider_error_code"] = str(result.error_code)
            if result.http_status is not None:
                failure_summary["create_http_status"] = result.http_status
            if result.retry_after_seconds is not None:
                failure_summary["retry_after_seconds"] = result.retry_after_seconds
            op.response_summary = failure_summary
            op.completed_at = datetime.now(UTC)
            await _commit_terminal_failure(
                session,
                run=run,
                error_code="PROVIDER_CREATE_FAILED",
                error_summary=error_text,
            )
            raise ValidationAppError(f"PROVIDER_CREATE_FAILED: {error_text}")
        remote = str(result.remote_task_id or "")
        if not remote:
            op.status = "failed"
            op.error_code = "PROVIDER_RESPONSE_INVALID"
            op.error_summary = "provider create response has no remote task id"
            op.completed_at = datetime.now(UTC)
            await _commit_terminal_failure(
                session,
                run=run,
                error_code="PROVIDER_RESPONSE_INVALID",
                error_summary=op.error_summary,
            )
            raise ValidationAppError("PROVIDER_RESPONSE_INVALID")
        op.provider_operation_id = remote
        op.remote_secondary_id = result.remote_secondary_id
        op.status = "submitted"
        if result.resume_token is not None:
            op.resume_token = result.resume_token.model_dump(mode="json")
            resume = result.resume_token
        op.response_summary = {
            "create_status": result.status,
            "query_kind": result.query_kind,
        }
        # Synchronous image submissions already carry the result URL; no poll.
        synchronous_image = (
            isinstance(compiled, CompiledImageRequest)
            and result.status == "succeeded"
            and result.artifact_uri is not None
        )
        op.request_summary = {
            **op.request_summary,
            **result.request_summary,
            "execution_identity": identity_json,
        }
        initial_status = str(result.status)
        await session.flush()
        await session.commit()
        await set_node_run_rls_context(session, node_run_id=run.id)

    if runtime is None:
        raise ValidationAppError("unified runtime was not resolved")
    if resume is None:
        raise ValidationAppError("unified operation has no resume token")

    # Poll loop (resume token driven). Synchronous image submissions already
    # carry the result URL and skip polling entirely.
    if not synchronous_image:
        poll_timeout_s = 1_620.0 if node_type in {"video", "video_review"} else 120.0
        poll_interval_s = 5.0 if node_type in {"video", "video_review"} else 3.0
        deadline = asyncio.get_running_loop().time() + poll_timeout_s
        poll = PollResult(status=initial_status)
        poll_count = 0
        while True:
            poll = await runtime.poll_video(resume)
            poll_count += 1
            status = str(poll.status)
            op.last_polled_at = datetime.now(UTC)
            op.status = "running"
            poll_error = poll.error_code
            if poll.http_status is not None or poll_error:
                summary = dict(op.response_summary or {})
                summary["last_poll_error"] = str(poll_error or f"http_{poll.http_status}")[:200]
                raw_count = summary.get("poll_error_count", 0) or 0
                summary["poll_error_count"] = (raw_count if isinstance(raw_count, int) else 0) + 1
                if poll.http_status is not None:
                    summary["last_poll_http_status"] = poll.http_status
                op.response_summary = summary
                await session.commit()
                await set_node_run_rls_context(session, node_run_id=run.id)
            if status in {"succeeded", "completed", "success", "failed", "cancelled"}:
                break
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                op.status = "timed_out"
                op.error_code = "PROVIDER_POLL_TIMEOUT"
                op.error_summary = (
                    f"remote task still pending after {poll_timeout_s:.0f}s; resume polling"
                )
                op.response_summary = {
                    "create_status": create_status,
                    "final_status": "running",
                    "poll_count": poll_count,
                    "query_kind": resume.query_kind,
                }
                run.status = "queued"
                run.error_code = "PROVIDER_TASK_PENDING"
                run.error_summary = "Remote Provider task is still running"
                run.output_summary = {
                    "status": "provider_pending",
                    "provider_operation_id": str(op.id),
                }
                await session.commit()
                raise ProviderTaskPendingError()
            poll_retry_after = poll.retry_after_seconds
            sleep_s = poll_interval_s
            if isinstance(poll_retry_after, int | float) and poll_retry_after > 0:
                sleep_s = max(sleep_s, float(poll_retry_after))
            await asyncio.sleep(min(sleep_s, remaining))
    else:
        assert result is not None and result.artifact_uri is not None
        poll = PollResult(status="succeeded", artifact_uri=result.artifact_uri)
        poll_count = 0

    cost = await runtime.fetch_cost(resume)
    status = str(poll.status)
    cost_amount = getattr(cost, "amount", None)
    cost_status = str(getattr(cost, "cost_status", "not_reported"))
    op.provider_cost = (
        Decimal(str(cost_amount)) if cost_amount is not None else None
    )
    if cost_amount is not None or cost_status in {"reported", "reconciled"}:
        op.currency = str(getattr(cost, "currency", op.currency)).upper()
    op.response_summary = {
        "create_status": create_status,
        "final_status": status,
        "poll_count": poll_count,
        "query_kind": resume.query_kind,
        "provider_reported_cost": (
            str(op.provider_cost) if op.provider_cost is not None else None
        ),
        "cost_status": cost_status,
    }
    if status not in {"succeeded", "completed", "success"}:
        error_summary = str(getattr(poll, "error_code", None) or status)[:500]
        op.status = "failed"
        op.error_code = "PROVIDER_FAILED"
        op.error_summary = error_summary
        op.completed_at = datetime.now(UTC)
        await _commit_terminal_failure(
            session,
            run=run,
            error_code="PROVIDER_FAILED",
            error_summary=error_summary,
        )
        raise ValidationAppError(f"PROVIDER_FAILED: {error_summary}")

    op.status = "succeeded"
    op.completed_at = datetime.now(UTC)
    uri = poll.artifact_uri
    data = await _resolve_media_bytes(
        kind=node_type,
        remote=remote,
        prompt=prompt,
        artifact_uri=uri,
    )

    mime, ext, art_type = _mime_for_node(node_type)
    object_key = f"projects/{run.project_id}/nodes/{node.node_key}/{run.id}.{ext}"
    media_metadata = _inspect_media_metadata(kind=node_type, data=data)
    stored = await obj_store.put_bytes(object_key=object_key, data=data, mime_type=mime)
    art = await get_or_create_artifact(
        session,
        project_id=run.project_id,
        artifact_type=art_type,
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type=stored.mime_type,
        byte_size=stored.byte_size,
        produced_by_run_id=run.id,
    )
    _apply_media_metadata(art, media_metadata)

    run.status = "completed"
    run.result_artifact_id = art.id
    run.provider_cost = op.provider_cost or Decimal("0")
    run.finished_at = datetime.now(UTC)
    run.output_summary = {
        "artifact_id": str(art.id),
        "node_type": node_type,
        "byte_size": art.byte_size,
        "content_hash": art.content_hash,
        "source_commit": get_settings().source_commit,
        "identity_evidence_policy": identity_evidence_policy_snapshot(),
        "execution_path": UNIFIED_PATH_VERSION,
    }
    node.latest_successful_run_id = run.id
    await session.flush()
    return ExecuteNodeResult(
        node_run_id=run.id,
        artifact_id=art.id,
        object_key=art.object_key,
        content_hash=art.content_hash,
        byte_size=art.byte_size,
        identity_status=None,
        provider_operation_id=op.id,
        node_type=node_type,
    )


async def execute_media_node_run(
    session: AsyncSession,
    *,
    node_run_id: UUID,
    store: ObjectStore | None = None,
    require_canonical: bool = False,
    canonical_image_bytes: bytes | None = None,
    already_claimed: bool = False,
) -> ExecuteNodeResult:
    """Worker entry for shot-p0-v1 media nodes. Never called from user Route."""
    from datetime import UTC, datetime

    run = await session.get(NodeRun, node_run_id)
    if run is None:
        raise ValidationAppError("node_run not found")
    node = await session.get(GraphNode, run.graph_node_id)
    if node is None:
        raise ValidationAppError("graph_node not found")
    node_type = node.node_type

    if run.status in {"completed", "cached", "completed_after_cancel"}:
        return await _completed_result(session, run=run, node_type=node_type)

    if already_claimed:
        if run.status != "running":
            raise ValidationAppError(f"claimed node_run cannot execute from status={run.status}")
    else:
        now = datetime.now(UTC)
        claimed = await session.execute(
            update(NodeRun)
            .where(NodeRun.id == node_run_id, NodeRun.status == "queued")
            .values(status="running", started_at=now)
            .returning(NodeRun.id)
        )
        if claimed.scalar_one_or_none() is None:
            await session.refresh(run)
            if run.status in {"completed", "cached", "completed_after_cancel"}:
                return await _completed_result(session, run=run, node_type=node_type)
            if run.status == "running":
                raise NodeRunAlreadyClaimedError()
            raise ValidationAppError(f"node_run cannot execute from status={run.status}")

    obj_store = store or get_object_store()
    if node.node_key == "final_film_assembly":
        from app.production.final_film import execute_final_film_node_run

        return await execute_final_film_node_run(
            session,
            run=run,
            node=node,
            obj_store=obj_store,
        )
    if node_type == "composite":
        return await _complete_composite_node(
            session,
            run=run,
            node=node,
            obj_store=obj_store,
        )

    snap = dict(run.input_snapshot or {})
    if node.node_key in {"identity_review", "video_drift_review"}:
        snap = await _bind_review_input_artifacts(session, run=run, node=node)
    canonical_artifact: Artifact | None = None
    # Formal Worker path resolves canonical only from a complete Artifact binding.
    if canonical_image_bytes is None:
        try:
            canonical_artifact, canonical_image_bytes = await _read_bound_artifact(
                session,
                run=run,
                snapshot=snap,
                prefix="canonical",
                store=obj_store,
                artifact_type="image",
            )
        except ValidationAppError:
            canonical_image_bytes = None
    if require_canonical and canonical_image_bytes is None:
        await _commit_terminal_failure(
            session,
            run=run,
            error_code="CANONICAL_REFERENCE_REQUIRED",
            error_summary="canonical reference required",
        )
        raise ValidationAppError("CANONICAL_REFERENCE_REQUIRED")

    lead_identity_required = snap.get("lead_identity_required") is True
    canonical_artifact_id = snap.get("canonical_artifact_id")
    has_canonical_binding = isinstance(canonical_artifact_id, str) and bool(canonical_artifact_id)
    missing_bound_canonical = (
        node_type == "keyframe"
        and lead_identity_required
        and (not has_canonical_binding or canonical_image_bytes is None)
    )
    if missing_bound_canonical:
        await _commit_terminal_failure(
            session,
            run=run,
            error_code="CANONICAL_REFERENCE_REQUIRED",
            error_summary="lead keyframe requires canonical reference image",
        )
        raise ValidationAppError("CANONICAL_REFERENCE_REQUIRED")

    plan_snapshot = snap.get("plan")
    prompt = str(plan_snapshot or {})
    if isinstance(plan_snapshot, dict):
        prompt = str(plan_snapshot.get("prompt", prompt))
    else:
        prompt = str(snap.get("prompt", f"{node_type}:{run.id}"))

    # Pure review / compose nodes: no Provider, zero cost, document/image result.
    PURE_NODES = {
        "identity_review",
        "video_review",
        "continuity_review",
        "prompt_compose",
        "prompt",
        "subtitle",
    }
    if node_type in PURE_NODES or node.node_key in {
        "identity_review",
        "video_drift_review",
        "continuity_review",
        "prompt",
        "subtitle",
    }:
        if node.node_key in {"identity_review", "video_drift_review"} or node_type in {
            "identity_review",
            "video_review",
        }:
            validate_identity_evidence_policy(snap)
        return await _complete_pure_node(
            session,
            run=run,
            node=node,
            node_type=node_type,
            snap=snap,
            obj_store=obj_store,
            canonical_image_bytes=canonical_image_bytes,
            prompt=prompt,
        )

    project = await session.scalar(select(Project).where(Project.id == run.project_id))
    if project is None:
        raise ValidationAppError("project not found for node run")
    if await set_node_run_rls_context(session, node_run_id=run.id) is None:
        raise ValidationAppError("node_run ownership context unavailable")

    _unified_op = await session.scalar(
        select(ProviderOperation)
        .where(
            ProviderOperation.node_run_id == run.id,
            ProviderOperation.execution_path_version == UNIFIED_PATH_VERSION,
        )
        .order_by(ProviderOperation.attempt_no.desc(), ProviderOperation.created_at.desc())
        .limit(1)
    )
    if node_type == "voice":
        from app.execution.voice_path import execute_voice_node_run

        return await execute_voice_node_run(
            session,
            run=run,
            node=node,
            snapshot=snap,
            store=obj_store,
            prompt=prompt,
        )
    # Keyframe and video are always executed by the unified compiler/runtime.
    if _unified_op is not None or node_type in {"keyframe", "video"}:
        return await _execute_unified_media_node_run(
            session,
            run=run,
            node=node,
            node_type=node_type,
            snap=snap,
            obj_store=obj_store,
            prompt=prompt,
            canonical_image_bytes=canonical_image_bytes,
            lead_identity_required=lead_identity_required,
            has_canonical_binding=has_canonical_binding,
            canonical_artifact=canonical_artifact,
        )
    raise ValidationAppError(f"unsupported executable node type: {node_type}")


async def _completed_result(
    session: AsyncSession,
    *,
    run: NodeRun,
    node_type: str,
) -> ExecuteNodeResult:
    art = await session.get(Artifact, run.result_artifact_id) if run.result_artifact_id else None
    if art is None:
        raise ValidationAppError("completed run missing artifact")
    output = run.output_summary or {}
    return ExecuteNodeResult(
        node_run_id=run.id,
        artifact_id=art.id,
        object_key=art.object_key,
        content_hash=art.content_hash,
        byte_size=art.byte_size,
        identity_status=(
            str(output.get("identity_review_status"))
            if output.get("identity_review_status") is not None
            else None
        ),
        provider_operation_id=None,
        node_type=node_type,
    )


def _mime_for_node(node_type: str) -> tuple[str, str, str]:
    if node_type in {"keyframe", "identity_review", "prompt_compose", "prompt"}:
        return "image/png", "png", "image"
    if node_type in {"video", "video_review", "composite"}:
        return "video/mp4", "mp4", "video"
    if node_type in {"voice"}:
        return "audio/wav", "wav", "audio"
    if node_type in {"subtitle"}:
        return "application/x-subrip", "srt", "subtitle"
    if node_type in {"continuity_review"}:
        return "application/json", "json", "document"
    return "application/octet-stream", "bin", "document"


async def _complete_composite_node(
    session: AsyncSession,
    *,
    run: NodeRun,
    node: GraphNode,
    obj_store: ObjectStore,
) -> ExecuteNodeResult:
    """Compose local video, voice, and subtitles without a Provider operation."""
    from datetime import UTC, datetime

    from app.config import get_settings
    from app.execution.composite_media import (
        CompositeInputMissingError,
        render_composite_bytes,
        resolve_composite_inputs,
    )

    try:
        inputs = await resolve_composite_inputs(session, run=run, store=obj_store)
    except CompositeInputMissingError as exc:
        await _commit_terminal_failure(
            session,
            run=run,
            error_code="COMPOSITE_INPUT_MISSING",
            error_summary=str(exc),
        )
        raise ValidationAppError(f"COMPOSITE_INPUT_MISSING: {exc}") from exc

    # Persist the source lineage before rendering so a terminal render failure
    # remains auditable.
    run.input_snapshot = {
        **(run.input_snapshot or {}),
        "media_inputs": inputs.media_inputs,
    }

    try:
        data = await render_composite_bytes(inputs)
    except Exception as exc:  # noqa: BLE001 - local render must fail closed
        detail = str(exc) or type(exc).__name__
        await _commit_terminal_failure(
            session,
            run=run,
            error_code="COMPOSITE_RENDER_FAILED",
            error_summary=detail,
        )
        raise ValidationAppError(f"COMPOSITE_RENDER_FAILED: {detail}") from exc

    try:
        object_key = f"projects/{run.project_id}/nodes/{node.node_key}/{run.id}.mp4"
        stored = await obj_store.put_bytes(
            object_key=object_key,
            data=data,
            mime_type="video/mp4",
        )
        art = await get_or_create_artifact(
            session,
            project_id=run.project_id,
            artifact_type="video",
            object_key=stored.object_key,
            content_hash=stored.content_hash,
            mime_type=stored.mime_type,
            byte_size=stored.byte_size,
            produced_by_run_id=run.id,
        )
    except Exception as exc:  # noqa: BLE001 - local composite output must fail closed
        detail = str(exc) or type(exc).__name__
        await _commit_terminal_failure(
            session,
            run=run,
            error_code="COMPOSITE_RENDER_FAILED",
            error_summary=detail,
        )
        raise ValidationAppError(f"COMPOSITE_RENDER_FAILED: {type(exc).__name__}") from exc

    run.status = "completed"
    run.result_artifact_id = art.id
    run.provider_cost = Decimal("0")
    run.platform_cost = Decimal("0")
    run.finished_at = datetime.now(UTC)
    run.output_summary = {
        "artifact_id": str(art.id),
        "node_type": "composite",
        "byte_size": art.byte_size,
        "content_hash": art.content_hash,
        "media_inputs": inputs.media_inputs,
        "source_commit": get_settings().source_commit,
    }
    if (
        (run.input_snapshot or {}).get("execution_branch") == "formal"
        and (run.input_snapshot or {}).get("experiment_id") is None
    ):
        from app.assets.models import Shot

        shot_id = (run.input_snapshot or {}).get("shot_id")
        if shot_id:
            shot = await session.get(Shot, UUID(str(shot_id)))
            if shot is not None and shot.project_id == run.project_id:
                shot.formal_composite_artifact_id = art.id
                shot.version = (shot.version or 1) + 1
    node.latest_successful_run_id = run.id
    await session.flush()
    return ExecuteNodeResult(
        node_run_id=run.id,
        artifact_id=art.id,
        object_key=art.object_key,
        content_hash=art.content_hash,
        byte_size=art.byte_size,
        identity_status=None,
        provider_operation_id=None,
        node_type="composite",
    )


async def _complete_pure_node(
    session: AsyncSession,
    *,
    run: NodeRun,
    node: GraphNode,
    node_type: str,
    snap: dict[str, object],
    obj_store: ObjectStore,
    canonical_image_bytes: bytes | None,
    prompt: str,
) -> ExecuteNodeResult:
    """Complete review/subtitle/prompt nodes without Provider (zero cost)."""
    import json
    from datetime import UTC, datetime

    from app.config import get_settings
    from app.consistency.continuity import continuity_four_layers

    identity_status: str | None = None
    review_status = "passed"
    payload: dict[str, object] = {
        "run_id": str(run.id),
        "shot_id": str(snap.get("shot_id") or ""),
        "node_type": node_type,
        "node_key": node.node_key,
        "zero_provider_cost": True,
    }

    key = node.node_key
    if key == "identity_review" or node_type == "identity_review":
        if snap.get("lead_identity_required") is not True:
            identity_status = "not_applicable"
            review_status = "not_applicable"
            payload["review_rule"] = "lead_identity_not_required"
        else:
            try:
                canonical_artifact, canonical = await _read_bound_artifact(
                    session,
                    run=run,
                    snapshot=snap,
                    prefix="canonical",
                    store=obj_store,
                    artifact_type="image",
                )
                probe_artifact, probe = await _read_bound_artifact(
                    session,
                    run=run,
                    snapshot=snap,
                    prefix="probe",
                    store=obj_store,
                    artifact_type="image",
                )
                review = identity_review_images(
                    probe_image_bytes=probe,
                    canonical_image_bytes=canonical,
                )
                identity_status = review.status
                review_status = review.status
                payload.update(
                    {
                        "review_rule": review.rule,
                        "canonical_artifact_id": str(canonical_artifact.id),
                        "canonical_content_hash": canonical_artifact.content_hash,
                        "probe_artifact_id": str(probe_artifact.id),
                        "probe_content_hash": probe_artifact.content_hash,
                    }
                )
            except ValidationAppError as exc:
                identity_status = "blocked"
                review_status = "blocked"
                payload.update(
                    {
                        "review_rule": "invalid_two_source_binding",
                        "review_error_code": str(exc.details.get("code") or exc.code),
                    }
                )
        payload.update(
            {
                "status": review_status,
                "identity_review_status": identity_status,
                "automatic_identity_decision": False,
                "human_review_required": identity_status == "needs_human",
            }
        )
        data = json.dumps(payload, sort_keys=True).encode()
        mime, ext, art_type = "application/json", "json", "document"
    elif key == "video_drift_review" or node_type == "video_review":
        from app.consistency.video_drift import (
            VIDEO_DRIFT_POLICY_ID,
            VIDEO_DRIFT_POLICY_STATUS,
            VIDEO_DRIFT_SAMPLING_VERSION,
            decide_video_drift,
            extract_video_samples,
            score_video_samples,
        )

        if snap.get("lead_identity_required") is not True:
            review_status = "not_applicable"
            payload.update(
                {
                    "status": review_status,
                    "review_rule": "lead_identity_not_required",
                    "video_drift_policy": {
                        "status": "not_applicable",
                        "sampling_version": VIDEO_DRIFT_SAMPLING_VERSION,
                    },
                }
            )
        else:
            try:
                canonical_artifact, canonical = await _read_bound_artifact(
                    session,
                    run=run,
                    snapshot=snap,
                    prefix="canonical",
                    store=obj_store,
                    artifact_type="image",
                )
                video_artifact, video = await _read_bound_artifact(
                    session,
                    run=run,
                    snapshot=snap,
                    prefix="video",
                    store=obj_store,
                    artifact_type="video",
                )
                samples = score_video_samples(
                    extract_video_samples(video),
                    canonical_image_bytes=canonical,
                )
                decision = decide_video_drift(samples)
                review_status = str(decision["status"])
                payload.update(
                    {
                        "status": review_status,
                        "review_rule": decision["reason"],
                        "canonical_artifact_id": str(canonical_artifact.id),
                        "canonical_content_hash": canonical_artifact.content_hash,
                        "video_artifact_id": str(video_artifact.id),
                        "video_content_hash": video_artifact.content_hash,
                        "samples": samples,
                        "video_drift_policy": {
                            "status": VIDEO_DRIFT_POLICY_STATUS,
                            "sampling_version": VIDEO_DRIFT_SAMPLING_VERSION,
                            "policy_id": VIDEO_DRIFT_POLICY_ID,
                            "automatic_identity_decision": False,
                        },
                    }
                )
            except (ValidationAppError, ValueError) as exc:
                review_status = "needs_human"
                payload.update(
                    {
                        "status": review_status,
                        "review_rule": "video_evidence_unavailable",
                        "review_error_code": (
                            str(exc.details.get("code") or exc.code)
                            if isinstance(exc, ValidationAppError)
                            else type(exc).__name__
                        ),
                        "samples": [],
                        "video_drift_policy": {
                            "status": VIDEO_DRIFT_POLICY_STATUS,
                            "sampling_version": VIDEO_DRIFT_SAMPLING_VERSION,
                            "policy_id": VIDEO_DRIFT_POLICY_ID,
                            "automatic_identity_decision": False,
                        },
                    }
                )
        data = json.dumps(payload, sort_keys=True).encode()
        mime, ext, art_type = "application/json", "json", "document"
    elif key == "continuity_review" or node_type == "continuity_review":
        subtitle = str(snap.get("subtitle") or snap.get("dialogue") or prompt or "")
        visual = str(snap.get("visual") or snap.get("visual_description") or prompt or "")
        lead = snap.get("lead_name")
        cont = continuity_four_layers(
            subtitle=subtitle,
            visual_desc=visual,
            lead_name=str(lead) if lead else None,
            shot_id=str(snap.get("shot_id") or "") or None,
        )
        review_status = cont.status
        payload.update(cont.to_dict())
        data = json.dumps(payload, sort_keys=True).encode()
        mime, ext, art_type = "application/json", "json", "document"
    elif key == "subtitle" or node_type == "subtitle":
        text = str(snap.get("subtitle") or snap.get("dialogue") or prompt or "Shot")
        # The cue number is not rendered. Making it run-specific keeps every
        # rerun independently attributable without changing the subtitle text
        # or timing.
        data = f"{run.id.int}\n00:00:00,000 --> 00:00:02,000\n{text}\n".encode()
        mime, ext, art_type = "application/x-subrip", "srt", "subtitle"
        payload["status"] = "passed"
    else:
        # prompt_compose
        data = json.dumps({"prompt": prompt, "status": "passed"}, sort_keys=True).encode()
        mime, ext, art_type = "application/json", "json", "document"
        payload["status"] = "passed"

    object_key = f"projects/{run.project_id}/nodes/{node.node_key}/{run.id}.{ext}"
    stored = await obj_store.put_bytes(object_key=object_key, data=data, mime_type=mime)
    art = await get_or_create_artifact(
        session,
        project_id=run.project_id,
        artifact_type=art_type,
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type=stored.mime_type,
        byte_size=stored.byte_size,
        produced_by_run_id=run.id,
    )

    run.status = "completed"
    run.result_artifact_id = art.id
    run.provider_cost = Decimal("0")
    run.finished_at = datetime.now(UTC)
    run.output_summary = {
        **payload,
        "artifact_id": str(art.id),
        "status": (
            review_status
            if key in {"identity_review", "video_drift_review", "continuity_review"}
            or node_type in {"identity_review", "video_review", "continuity_review"}
            else "passed"
        ),
        "identity_review_status": identity_status,
        "byte_size": art.byte_size,
        "content_hash": art.content_hash,
        "source_commit": get_settings().source_commit,
        "identity_evidence_policy": identity_evidence_policy_snapshot(),
    }
    node.latest_successful_run_id = run.id
    await session.flush()
    return ExecuteNodeResult(
        node_run_id=run.id,
        artifact_id=art.id,
        object_key=art.object_key,
        content_hash=art.content_hash,
        byte_size=art.byte_size,
        identity_status=identity_status,
        provider_operation_id=None,
        node_type=node_type,
    )


async def _resolve_media_bytes(
    *,
    kind: str,
    remote: str,
    prompt: str,
    artifact_uri: object,
) -> bytes:
    """Load media bytes from URI. Never invent STUB success media on formal path."""
    from app.config import get_settings

    if isinstance(artifact_uri, bytes):
        return _validate_provider_media(kind=kind, data=artifact_uri, content_type=None)
    if isinstance(artifact_uri, str) and artifact_uri:
        if artifact_uri.startswith("data:") and "," in artifact_uri:
            import base64

            header, b64 = artifact_uri.split(",", 1)
            max_encoded_chars = ((_MAX_PROVIDER_MEDIA_BYTES + 2) // 3) * 4
            if len(b64) > max_encoded_chars:
                raise ValidationAppError("PROVIDER_MEDIA_INVALID: data URI is too large")
            try:
                data = base64.b64decode(b64, validate=True)
            except (ValueError, TypeError) as exc:
                raise ValidationAppError("PROVIDER_MEDIA_INVALID: malformed data URI") from exc
            mime = header[5:].split(";", 1)[0].strip().lower()
            return _validate_provider_media(kind=kind, data=data, content_type=mime)
        if artifact_uri.startswith("http://") or artifact_uri.startswith("https://"):
            return await _download_provider_media(kind=kind, artifact_uri=artifact_uri)
        if artifact_uri.startswith("fake://") and get_settings().app_env == "test":
            # Explicit test-only fake URI → synthetic bytes for contract tests
            return f"{kind}-TESTFAKE:{remote}:{prompt}".encode()
        # Non-URL string payload only if it looks like raw content (not a stub label)
        if not artifact_uri.startswith(("fake://", "stub://")):
            return artifact_uri.encode() if not isinstance(artifact_uri, bytes) else artifact_uri
    if get_settings().app_env == "test":
        # Test adapters without blobs: deterministic bytes for unit tests only
        return f"{kind}-TESTFAKE:{remote}:{prompt}".encode()
    raise ValidationAppError(
        f"PROVIDER_MEDIA_MISSING: adapter succeeded but no artifact_uri bytes "
        f"(kind={kind} remote={remote}). Refusing STUB media on formal path."
    )
