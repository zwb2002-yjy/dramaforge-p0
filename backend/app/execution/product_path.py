"""Product execution path: enqueue NodeRun for Worker (no Adapter in request thread)."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpcore
import httpx
from httpcore._backends.base import (
    SOCKET_OPTION,
    AsyncNetworkBackend,
    AsyncNetworkStream,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.config import get_settings
from app.consistency.face_policy import (
    approved_face_policy_snapshot,
    approved_face_threshold,
    approved_face_threshold_from_snapshot,
)
from app.consistency.face_review import face_review_images
from app.creation.models import CreationPlan
from app.execution.artifact_lineage import get_or_create_artifact
from app.execution.models import Artifact, GraphEdge, GraphNode, NodeRun, ProviderOperation
from app.execution.shot_pipeline import (
    SHOT_PIPELINE_TEMPLATE_KEY,
    shot_pipeline_definition,
)
from app.production.service import GraphService
from app.providers.base import ProviderAdapter
from app.providers.fake import FakeFluxAdapter
from app.shared.db import set_node_run_rls_context
from app.shared.errors import (
    AppError,
    NodeRunAlreadyClaimedError,
    ProviderTaskPendingError,
    ValidationAppError,
)
from app.storage.minio_store import ObjectStore, get_object_store

if TYPE_CHECKING:
    from app.director.execution_guard import DirectorMediaExecutionContext
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
        raise ValidationAppError(
            "PROVIDER_MEDIA_URL_INVALID: media URL port is invalid"
        ) from exc
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
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=20.0),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client, client.stream("GET", value) as response:
            if response.is_redirect:
                raise ValidationAppError(
                    "PROVIDER_MEDIA_INVALID: provider media redirects are not allowed"
                )
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > _MAX_PROVIDER_MEDIA_BYTES:
                        raise ValidationAppError(
                            "PROVIDER_MEDIA_INVALID: response is too large"
                        )
                except ValueError as exc:
                    raise ValidationAppError(
                        "PROVIDER_MEDIA_INVALID: response Content-Length is invalid"
                    ) from exc
            body = bytearray()
            async for chunk in response.aiter_bytes(1024 * 1024):
                body.extend(chunk)
                if len(body) > _MAX_PROVIDER_MEDIA_BYTES:
                    raise ValidationAppError(
                        "PROVIDER_MEDIA_INVALID: response is too large"
                    )
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
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=20.0),
            follow_redirects=False,
            trust_env=False,
            transport=base_transport,
        ) as client, client.stream("GET", value) as response:
            if response.is_redirect:
                raise ValidationAppError(
                    "PROVIDER_MEDIA_INVALID: provider media redirects are not allowed"
                )
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > _MAX_PROVIDER_MEDIA_BYTES:
                        raise ValidationAppError(
                            "PROVIDER_MEDIA_INVALID: response is too large"
                        )
                except ValueError as exc:
                    raise ValidationAppError(
                        "PROVIDER_MEDIA_INVALID: response Content-Length is invalid"
                    ) from exc
            body = bytearray()
            async for chunk in response.aiter_bytes(1024 * 1024):
                body.extend(chunk)
                if len(body) > _MAX_PROVIDER_MEDIA_BYTES:
                    raise ValidationAppError(
                        "PROVIDER_MEDIA_INVALID: response is too large"
                    )
            return _validate_provider_media(
                kind=kind,
                data=bytes(body),
                content_type=response.headers.get("Content-Type"),
            )
    finally:
        await base_transport.aclose()


def _media_magic_matches(kind: str, data: bytes) -> bool:
    if kind in {"keyframe", "image"}:
        return data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff") or (
            len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
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
class EnqueueKeyframeResult:
    graph_id: UUID
    graph_version_id: UUID
    node_run_id: UUID
    graph_node_id: UUID


@dataclass(frozen=True)
class ExecuteNodeResult:
    node_run_id: UUID
    artifact_id: UUID
    object_key: str
    content_hash: str
    byte_size: int
    face_status: str | None
    face_score: float | None
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
    """Freeze the direct same-Shot, same-attempt media input into a Review snapshot."""
    upstream_key = {
        "face_review": "keyframe",
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
                    NodeRun.attempt_no == run.attempt_no,
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
                key=lambda item: (item.created_at, str(item.id)),
                reverse=True,
            )
            if str((candidate.input_snapshot or {}).get("shot_id") or "") == shot_id
        ),
        None,
    )
    if source is None:
        raise ValidationAppError(
            f"same-attempt {upstream_key} Run is missing",
            details={"code": "UPSTREAM_RUN_MISSING"},
        )
    artifact = (
        await session.get(Artifact, source.result_artifact_id)
        if source.result_artifact_id
        else None
    )
    if artifact is None or artifact.project_id != run.project_id:
        raise ValidationAppError(
            f"same-attempt {upstream_key} Artifact is missing",
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
    prefix = "probe" if node.node_key == "face_review" else "video"
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


async def _bind_director_canonical_source(
    session: AsyncSession,
    *,
    run: NodeRun,
    snapshot: dict[str, object],
) -> dict[str, object]:
    """Resolve the Director's frozen canonical source without a silent fallback."""

    raw_source_id = snapshot.get("canonical_source_run_id")
    if raw_source_id is None or snapshot.get("canonical_artifact_id") is not None:
        return snapshot
    try:
        source_id = UUID(str(raw_source_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationAppError(
            "canonical source NodeRun binding is invalid",
            details={"code": "CANONICAL_SOURCE_RUN_INVALID"},
        ) from exc
    source = await session.get(NodeRun, source_id)
    if (
        source is None
        or source.project_id != run.project_id
        or run.production_batch_id is None
        or source.production_batch_id != run.production_batch_id
    ):
        raise ValidationAppError(
            "canonical source NodeRun is outside this Director production batch",
            details={"code": "CANONICAL_SOURCE_RUN_INVALID"},
        )
    if (
        source.status not in {"completed", "cached", "completed_after_cancel"}
        or source.result_artifact_id is None
    ):
        raise ValidationAppError(
            "canonical source NodeRun has not completed with an image",
            details={"code": "CANONICAL_SOURCE_NOT_READY"},
        )
    artifact = await session.get(Artifact, source.result_artifact_id)
    origin = (
        await session.get(NodeRun, source.reused_from_run_id)
        if source.reused_from_run_id is not None
        else source
    )
    if (
        artifact is None
        or artifact.project_id != run.project_id
        or artifact.artifact_type != "image"
        or artifact.storage_state != "available"
        or artifact.deleted_at is not None
        or origin is None
        or artifact.produced_by_run_id != origin.id
    ):
        raise ValidationAppError(
            "canonical source NodeRun image Artifact is missing",
            details={"code": "CANONICAL_SOURCE_ARTIFACT_MISSING"},
        )
    resolved = {
        **snapshot,
        **_artifact_snapshot(artifact, prefix="canonical"),
        "canonical_source_run_id": str(source.id),
    }
    return resolved


def identity_priority_keyframe_prompt(
    prompt: str,
    *,
    canonical_locked_prompt: str,
) -> str:
    """Preserve the planned beat while making a two-source face review feasible."""
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


async def _validate_director_submission_or_block(
    session: AsyncSession,
    *,
    run: NodeRun,
    node: GraphNode,
    provider_operation: ProviderOperation | None = None,
) -> DirectorMediaExecutionContext | None:
    from datetime import UTC, datetime

    from app.director.execution_guard import (
        DirectorExecutionGuardError,
        validate_director_media_submission,
    )

    try:
        return await validate_director_media_submission(
            session,
            run=run,
            node=node,
        )
    except DirectorExecutionGuardError as exc:
        if provider_operation is not None:
            provider_operation.status = "rejected"
            provider_operation.error_code = exc.code
            provider_operation.error_summary = exc.message[:500]
            provider_operation.completed_at = datetime.now(UTC)
        blocked_budget = exc.code in {
            "DIRECTOR_PRODUCTION_CONTEXT_REQUIRED",
            "DIRECTOR_BUDGET_RESERVATION_INVALID",
            "DIRECTOR_BUDGET_AUTHORIZATION_INACTIVE",
            "DIRECTOR_BUDGET_AUTHORIZATION_EXCEEDED",
        }
        await _commit_terminal_failure(
            session,
            run=run,
            error_code=exc.code,
            error_summary=exc.message,
            status="blocked_budget" if blocked_budget else "failed",
        )
        raise


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


async def enqueue_keyframe_after_plan(
    session: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    plan: CreationPlan,
    materialization_ops: list[str],
    shot_id: UUID | None = None,
    shot_plan: dict[str, object] | None = None,
) -> EnqueueKeyframeResult:
    """Publish the full Shot graph and queue its first keyframe NodeRun.

    The remaining nodes are intentionally started through the per-shot API once
    the operator is ready to advance that shot. This keeps provider work
    explicit while giving every run the same persisted Plan context.
    """
    graphs = GraphService(session)
    shot_id = shot_id or uuid4()
    shot_body = dict(shot_plan or {})
    prompt = str(
        shot_body.get("keyframe_prompt")
        or shot_body.get("prompt")
        or plan.plan.get("prompt")
        or "Cinematic keyframe, 9:16"
    )
    from app.access.models import Project

    project = await session.get(Project, project_id)
    assert project is not None
    from app.providers.model_profiles.node_snapshot import planned_node_model_profile

    model_profile = await planned_node_model_profile(
        session, project=project, node_key="keyframe"
    )
    graph = await graphs.create_graph(
        project_id=project_id,
        scope_type="shot",
        scope_entity_id=shot_id,
        template_key=SHOT_PIPELINE_TEMPLATE_KEY,
        created_by=user_id,
        definition=shot_pipeline_definition(
            materialization=materialization_ops,
            plan_id=str(plan.id),
            shot_id=str(shot_id),
            shot=shot_body,
            model_profile=model_profile,
        ),
    )
    assert graph.current_version_id is not None
    materialized = await graphs.materialize_definition(version_id=graph.current_version_id)
    version = await graphs.publish(version_id=materialized.version.id, published_by=user_id)
    nodes = materialized.nodes
    node = nodes["keyframe"]
    # Attach project lead canonical if registered (P0 face gate / consistency).
    from sqlalchemy import select

    from app.assets.models import Asset, Character, CharacterReference

    canonical_artifact: Artifact | None = None
    canonical_locked_prompt = ""
    ref = (
        await session.execute(
            select(CharacterReference, Character.locked_prompt, Artifact)
            .join(Character, Character.id == CharacterReference.character_id)
            .join(Asset, Asset.id == Character.id)
            .outerjoin(Artifact, Artifact.id == CharacterReference.artifact_id)
            .where(Asset.project_id == project_id)
            .where(CharacterReference.is_canonical.is_(True))
            .limit(1)
        )
    ).one_or_none()
    if ref is not None:
        canonical_artifact = ref[2]
        canonical_locked_prompt = ref[1]
    lead_identity_required = shot_body.get("lead_identity_required") is True
    if lead_identity_required and canonical_locked_prompt:
        prompt = identity_priority_keyframe_prompt(
            prompt,
            canonical_locked_prompt=canonical_locked_prompt,
        )

    snapshot: dict[str, object] = {
        "plan_id": str(plan.id),
        "shot_id": str(shot_id),
        "node_key": "keyframe",
        "source_commit": get_settings().source_commit,
        "plan": {
            "prompt": prompt,
            "shot": shot_body,
            "visual_bible": plan.plan.get("visual_bible", {}),
        },
        "prompt": prompt,
        "materialization": materialization_ops,
        "lead_identity_required": lead_identity_required,
        "face_policy": approved_face_policy_snapshot(),
        "model_profile": model_profile,
    }
    if canonical_artifact is not None:
        snapshot.update(_artifact_snapshot(canonical_artifact, prefix="canonical"))
    if canonical_locked_prompt:
        snapshot["canonical_locked_prompt"] = canonical_locked_prompt

    # The graph declares prompt -> keyframe. Materialization of the accepted Plan
    # is a deterministic, zero-cost upstream result, so persist its document and
    # lineage before queueing any paid image work.
    import json
    from datetime import UTC, datetime

    prompt_node = nodes["prompt"]
    prompt_snapshot: dict[str, object] = {
        **snapshot,
        "node_key": "prompt",
        # prompt_compose has no model slot; drop the keyframe slot's profile.
        "model_profile": {},
    }
    prompt_hash = _input_hash(prompt_snapshot)
    now = datetime.now(UTC)
    prompt_run = NodeRun(
        id=uuid4(),
        project_id=project_id,
        graph_version_id=version.id,
        graph_node_id=prompt_node.id,
        attempt_no=1,
        idempotency_key=f"prompt:{shot_id}:{prompt_hash}",
        input_hash=prompt_hash,
        status="running",
        input_snapshot=prompt_snapshot,
        output_summary={},
        started_at=now,
        created_by=user_id,
    )
    session.add(prompt_run)
    await session.flush()
    prompt_bytes = json.dumps(
        {"prompt": prompt, "status": "passed"},
        ensure_ascii=True,
        sort_keys=True,
    ).encode("utf-8")
    prompt_store = get_object_store()
    stored_prompt = await prompt_store.put_bytes(
        object_key=f"projects/{project_id}/nodes/prompt/{prompt_run.id}.json",
        data=prompt_bytes,
        mime_type="application/json",
    )
    prompt_artifact = await get_or_create_artifact(
        session,
        project_id=project_id,
        artifact_type="document",
        object_key=stored_prompt.object_key,
        content_hash=stored_prompt.content_hash,
        mime_type=stored_prompt.mime_type,
        byte_size=stored_prompt.byte_size,
        produced_by_run_id=prompt_run.id,
    )
    prompt_run.result_artifact_id = prompt_artifact.id
    prompt_run.status = "completed"
    prompt_run.finished_at = now
    prompt_run.output_summary = {
        "status": "passed",
        "zero_provider_cost": True,
        "artifact_id": str(prompt_artifact.id),
        "content_hash": prompt_artifact.content_hash,
        "byte_size": prompt_artifact.byte_size,
        "source_commit": get_settings().source_commit,
    }
    prompt_node.latest_successful_run_id = prompt_run.id

    ih = _input_hash(snapshot)
    node_run = NodeRun(
        project_id=project_id,
        graph_version_id=version.id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=f"keyframe:{shot_id}:{ih}",
        input_hash=ih,
        status="queued",
        input_snapshot=snapshot,
        created_by=user_id,
    )
    session.add(node_run)
    await session.flush()
    return EnqueueKeyframeResult(
        graph_id=graph.id,
        graph_version_id=version.id,
        node_run_id=node_run.id,
        graph_node_id=node.id,
    )


async def execute_keyframe_node_run(
    session: AsyncSession,
    *,
    node_run_id: UUID,
    store: ObjectStore | None = None,
    flux: ProviderAdapter | None = None,
    require_canonical: bool = False,
    canonical_embedding: list[float] | None = None,
    canonical_image_bytes: bytes | None = None,
) -> ExecuteNodeResult:
    """Worker: Adapter → ObjectStore → Artifact → face review from *image bytes*."""
    return await execute_media_node_run(
        session,
        node_run_id=node_run_id,
        store=store,
        flux=flux,
        require_canonical=require_canonical,
        canonical_embedding=canonical_embedding,
        canonical_image_bytes=canonical_image_bytes,
    )


async def _run_shadow_selection(
    session: AsyncSession,
    *,
    project: Project,
    node_type: str,
    prompt: str,
    first_frame: Artifact | None,
    op: ProviderOperation,
    legacy_provider: str,
    legacy_model: str,
) -> None:
    """Stage B1: resolve the intent through the unified path and compare with the
    legacy resolution. Pure observation — never submits to a Provider."""
    try:
        from app.providers.intents import (
            ArtifactReferenceIntent,
            ImageGenerationIntent,
            ModelSelectionIntent,
            VideoGenerationIntentV1,
        )
        from app.providers.selection import ModelSelectionService

        service = ModelSelectionService(session)
        selection = ModelSelectionIntent(mode="explicit_binding")
        if node_type == "keyframe":
            image_intent = ImageGenerationIntent(prompt=prompt, selection=selection)
            plan = await service.select_image(project=project, intent=image_intent)
        else:
            references = []
            if first_frame is not None:
                references.append(
                    ArtifactReferenceIntent(
                        artifact_id=first_frame.id,
                        role="first_frame",
                        required=True,
                    )
                )
            video_intent = VideoGenerationIntentV1(
                prompt=prompt,
                references=references,
                selection=selection,
            )
            plan = await service.select_video(project=project, intent=video_intent)
        summary = dict(op.request_summary or {})
        summary["shadow_selection"] = {
            "resolved": True,
            "provider_type": plan.provider_type,
            "protocol_profile": plan.protocol_profile,
            "model_id": plan.model_id,
            "invoke_model_value": plan.invoke_model_value,
            "model_binding_id": str(plan.model_binding_id) if plan.model_binding_id else None,
            "manifest_hash": plan.manifest_hash,
            "legacy_provider": legacy_provider,
            "legacy_model": legacy_model,
            "matches_legacy": (
                plan.provider_type == legacy_provider
                and plan.invoke_model_value == legacy_model
            ),
        }
        op.request_summary = summary
        await session.flush()
    except Exception as exc:  # noqa: BLE001 - shadow is observational, never blocks
        summary = dict(op.request_summary or {})
        summary["shadow_selection"] = {
            "resolved": False,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }
        op.request_summary = summary
        await session.flush()


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
    """Resolve one artifact reference to the transport the selected Provider
    requires: Ark references are short-lived public HTTPS URLs (issued through
    the platform grant), Agnes references travel as bytes (data URI / raw
    base64). A missing reference fails closed."""
    from app.providers.reference_delivery import issue_artifact_reference
    from app.providers.runtime import ResolvedReference

    if provider_type == "volcengine":
        if artifact is None:
            raise ValidationAppError(
                "Ark reference requires a bound image artifact",
                details={"code": "REFERENCE_ARTIFACT_REQUIRED"},
            )
        grant = await issue_artifact_reference(
            session,
            artifact=artifact,
            workspace_id=project.workspace_id,
            created_by_run_id=run.id,
        )
        return ResolvedReference(
            role=role,
            artifact_id=artifact.id,
            content_url=grant.url,
            mime_type=artifact.mime_type or mime_type,
            fingerprint=artifact.content_hash,
        )
    if content_bytes is None:
        raise ValidationAppError(
            "reference bytes are required",
            details={"code": "REFERENCE_ARTIFACT_REQUIRED"},
        )
    return ResolvedReference(
        role=role,
        artifact_id=artifact.id if artifact is not None else UUID(int=0),
        content_bytes=content_bytes,
        mime_type=mime_type,
        fingerprint=fingerprint,
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
    canonical_embedding: list[float] | None,
    lead_identity_required: bool,
    has_canonical_binding: bool,
    face_threshold: float,
    canonical_artifact: Artifact | None = None,
) -> ExecuteNodeResult:
    """Stage B4: binding-driven unified execution path.

    Single-path submission: a persisted ``execution_path_version`` wins over any
    flag; resume never re-creates a remote task; ``submission_started`` without a
    remote id (crash between commit and response) is escalated to
    ``unknown_submission`` for manual reconciliation instead of a duplicate POST.
    """
    from dataclasses import asdict
    from datetime import UTC, datetime

    from app.providers.catalog_models import ModelCatalogEntry
    from app.providers.intents import (
        ArtifactReferenceIntent,
        ImageGenerationIntent,
        ModelSelectionIntent,
        VideoGenerationIntentV1,
        VideoOutputIntent,
    )
    from app.providers.manifest import ModelCapabilityManifest
    from app.providers.models import ProviderConnection, ProviderModelBinding
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
    from app.providers.selection import ModelSelectionService
    from app.providers.workspace_credentials import runtime_connection_settings
    from app.shared.errors import ProviderRateLimitedError, ProviderTaskPendingError

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

    create_status = "created"
    remote = ""
    runtime: ProviderRuntime | None = None
    resume: ProviderResumeToken | None = None
    initial_status = "queued"
    synchronous_image = False
    result: SubmissionResult | None = None
    director_context: DirectorMediaExecutionContext | None = None

    resubmit = bool(
        op is not None
        and op.status == "rejected"
        and not op.provider_operation_id
    )
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
        # Resume only. Never create a second remote task.
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
        director_context = await _validate_director_submission_or_block(
            session,
            run=run,
            node=node,
        )
        frozen_binding_id = (
            director_context.model_binding_id if director_context is not None else None
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
            canonical_artifact_id = snap.get("canonical_artifact_id")
            reference_uuid: UUID | None = None
            if isinstance(canonical_artifact_id, str):
                try:
                    reference_uuid = UUID(canonical_artifact_id)
                except ValueError:
                    reference_uuid = None
            raw_ratio = str(snap.get("aspect_ratio") or project.aspect_ratio or "")
            image_size = {
                "9:16": "1080x1920",
                "16:9": "1920x1080",
            }.get(raw_ratio)
            if image_size is None:
                raise ValidationAppError(
                    "Director image request has an unsupported aspect ratio",
                    details={"code": "ASPECT_RATIO_UNSUPPORTED", "aspect_ratio": raw_ratio},
                )
            image_intent = ImageGenerationIntent(
                prompt=prompt,
                size=image_size,
                seed=None,
                reference_artifact_id=reference_uuid,
                reference_fingerprint=(
                    hashlib.sha256(canonical_image_bytes).hexdigest()
                    if canonical_image_bytes is not None
                    else None
                ),
                reference_mime=str(snap.get("canonical_mime_type") or "image/png"),
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
                    "Director video request has no valid duration",
                    details={"code": "DURATION_REQUIRED"},
                )
            raw_ratio = str(snap.get("aspect_ratio") or project.aspect_ratio or "")
            video_ratio: Literal["9:16", "16:9"] | None = (
                "9:16" if raw_ratio == "9:16" else "16:9" if raw_ratio == "16:9" else None
            )
            if video_ratio is None:
                raise ValidationAppError(
                    "Director video request has an unsupported aspect ratio",
                    details={"code": "ASPECT_RATIO_UNSUPPORTED", "aspect_ratio": raw_ratio},
                )
            video_intent = VideoGenerationIntentV1(
                prompt=prompt,
                output=VideoOutputIntent(
                    aspect_ratio=video_ratio,
                    duration_seconds=duration_seconds,
                    generate_audio=False,
                ),
                references=[
                    ArtifactReferenceIntent(
                        artifact_id=first_frame.id,
                        role="first_frame",
                        required=True,
                    )
                ],
                selection=ModelSelectionIntent(
                    mode="explicit_binding",
                    model_binding_id=frozen_binding_id,
                ),
            )

        service = ModelSelectionService(session)
        if node_type == "keyframe":
            assert image_intent is not None
            plan = await service.select_image(project=project, intent=image_intent)
        else:
            assert video_intent is not None
            plan = await service.select_video(project=project, intent=video_intent)
        if frozen_binding_id is not None and plan.model_binding_id != frozen_binding_id:
            raise ValidationAppError(
                "unified selection changed the frozen model binding",
                details={"code": "MODEL_BINDING_SNAPSHOT_MISMATCH"},
            )
        invoke_model_value = plan.invoke_model_value
        provider_type = plan.provider_type
        protocol_profile = plan.protocol_profile
        if (
            invoke_model_value is None
            or provider_type is None
            or protocol_profile is None
        ):
            raise ValidationAppError("unified selection has no model/provider identity")
        connection = await session.get(ProviderConnection, plan.connection_id)
        binding = await session.get(ProviderModelBinding, plan.model_binding_id)
        entry = await session.get(ModelCatalogEntry, plan.catalog_entry_id)
        if connection is None or binding is None or entry is None:
            raise ValidationAppError(
                "unified selection references missing connection/binding/catalog",
                details={"code": "MODEL_BINDING_MISSING"},
            )
        plugin = get_plugin(provider_type, protocol_profile)
        cfg = await runtime_connection_settings(session, connection=connection)
        resolved = await ProviderRuntimeResolver(session).resolve(
            plugin=plugin,
            connection=connection,
            binding=binding,
            entry=entry,
            settings=cfg,
        )
        runtime = resolved.runtime
        manifest = ModelCapabilityManifest.model_validate(entry.capability_manifest_json)
        compiled: CompiledImageRequest | CompiledVideoRequest
        if node_type == "keyframe":
            image_compiler = resolved.image_compiler
            if image_compiler is None:
                raise ValidationAppError("unified plugin has no image compiler")
            assert image_intent is not None
            refs: list[ResolvedReference] = []
            if has_canonical_binding and canonical_image_bytes is not None:
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
            compiled = await video_compiler.compile(
                video_intent,
                manifest,
                [
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
                ],
                invoke_model_value=invoke_model_value,
            )

        kind = node_type
        fingerprint = hashlib.sha256(
            f"{kind}:{prompt}:{compiled.model_dump_json()}".encode()
        ).hexdigest()
        # Revalidate after request compilation, immediately before persisting
        # the submission marker and making the paid call.
        if director_context is not None:
            await _validate_director_submission_or_block(
                session,
                run=run,
                node=node,
            )
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
                request_summary={
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
                    "reference_artifact_ids": [
                        str(value) for value in compiled.reference_artifact_ids
                    ],
                    "reference_fingerprints": list(compiled.reference_fingerprints),
                    "frozen_model_binding_id": str(binding.id),
                    "capability_manifest_hash": plan.manifest_hash,
                },
                response_summary={},
                submitted_at=now,
                connection_id=connection.id,
                model_binding_id=binding.id,
                catalog_entry_id=entry.id,
                capability_manifest_hash=plan.manifest_hash,
                selection_plan=json.loads(json.dumps(asdict(plan), default=str)),
                execution_path_version=UNIFIED_PATH_VERSION,
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
        await session.flush()
        await session.commit()
        await set_node_run_rls_context(session, node_run_id=run.id)

        if director_context is not None:
            await _validate_director_submission_or_block(
                session,
                run=run,
                node=node,
                provider_operation=op,
            )

        if isinstance(compiled, CompiledImageRequest):
            result = await resolved.runtime.submit_image(compiled)
        else:
            result = await resolved.runtime.submit_video(compiled)
        if result.status == "unknown_submission":
            op.status = "unknown_submission"
            op.error_code = str(result.error_code or "PROVIDER_SUBMISSION_UNKNOWN")
            op.error_summary = (
                "Provider submission outcome is unknown; manual reconciliation required"
            )
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
            op.response_summary = {"create_status": result.status, "create_error": error_text[:300]}
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
        op.request_summary = {**op.request_summary, **result.request_summary}
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
    op.provider_cost = Decimal(str(getattr(cost, "amount", 0.0)))
    op.currency = str(getattr(cost, "currency", "USD"))
    op.response_summary = {
        "create_status": create_status,
        "final_status": status,
        "poll_count": poll_count,
        "query_kind": resume.query_kind,
    }
    if run.production_batch_id is not None and run.budget_reservation_id is not None:
        from app.director.execution_guard import settle_director_media_cost

        await settle_director_media_cost(session, run=run, operation=op)
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

    face_status: str | None = None
    face_score: float | None = None
    if node_type in {"keyframe", "face_review"}:
        if not lead_identity_required:
            face_status = "not_applicable"
        elif canonical_image_bytes is not None:
            review = face_review_images(
                probe_image_bytes=data,
                canonical_image_bytes=canonical_image_bytes,
                threshold=face_threshold,
            )
            face_status = review.status
            face_score = review.score
        else:
            face_status = "needs_human"
            face_score = None

    run.status = "completed"
    run.result_artifact_id = art.id
    run.provider_cost = op.provider_cost or Decimal("0")
    run.finished_at = datetime.now(UTC)
    run.output_summary = {
        "artifact_id": str(art.id),
        "node_type": node_type,
        "face_review": face_status,
        "face_score": face_score,
        "byte_size": art.byte_size,
        "content_hash": art.content_hash,
        "source_commit": get_settings().source_commit,
        "face_policy": approved_face_policy_snapshot(),
        "face_threshold": face_threshold,
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
        face_status=face_status,
        face_score=face_score,
        provider_operation_id=op.id,
        node_type=node_type,
    )


async def execute_media_node_run(
    session: AsyncSession,
    *,
    node_run_id: UUID,
    store: ObjectStore | None = None,
    flux: ProviderAdapter | None = None,
    require_canonical: bool = False,
    canonical_embedding: list[float] | None = None,
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
    if node_type == "composite":
        return await _complete_composite_node(
            session,
            run=run,
            node=node,
            obj_store=obj_store,
        )

    snap = dict(run.input_snapshot or {})
    if node.node_key in {"face_review", "video_drift_review"}:
        snap = await _bind_review_input_artifacts(session, run=run, node=node)
    if snap.get("canonical_source_run_id") is not None:
        try:
            snap = await _bind_director_canonical_source(
                session,
                run=run,
                snapshot=snap,
            )
        except ValidationAppError as exc:
            error_code = str(exc.details.get("code") or "CANONICAL_REFERENCE_REQUIRED")
            await _commit_terminal_failure(
                session,
                run=run,
                error_code=error_code,
                error_summary=exc.message,
            )
            raise
    face_threshold = approved_face_threshold()
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
    if require_canonical and canonical_embedding is None and canonical_image_bytes is None:
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
        "face_review",
        "video_review",
        "continuity_review",
        "prompt_compose",
        "prompt",
        "subtitle",
    }
    if node_type in PURE_NODES or node.node_key in {
        "face_review",
        "video_drift_review",
        "continuity_review",
        "prompt",
        "subtitle",
    }:
        if node.node_key in {"face_review", "video_drift_review"} or node_type in {
            "face_review",
            "video_review",
        }:
            face_threshold = approved_face_threshold_from_snapshot(snap)
        return await _complete_pure_node(
            session,
            run=run,
            node=node,
            node_type=node_type,
            snap=snap,
            obj_store=obj_store,
            canonical_image_bytes=canonical_image_bytes,
            face_threshold=face_threshold,
            prompt=prompt,
        )

    project = await session.scalar(select(Project).where(Project.id == run.project_id))
    if project is None:
        raise ValidationAppError("project not found for node run")
    if await set_node_run_rls_context(session, node_run_id=run.id) is None:
        raise ValidationAppError("node_run ownership context unavailable")

    # Stage B4: unified path is driven by persisted execution_path_version or the
    # enable flag. A persisted unified op wins over any flag (single-path rule).
    _unified_op = await session.scalar(
        select(ProviderOperation)
        .where(
            ProviderOperation.node_run_id == run.id,
            ProviderOperation.execution_path_version == UNIFIED_PATH_VERSION,
        )
        .order_by(ProviderOperation.attempt_no.desc(), ProviderOperation.created_at.desc())
        .limit(1)
    )
    if _unified_op is not None or (
        get_settings().provider_unified_path_enabled
        and node_type in {"keyframe", "video", "video_review"}
    ):
        return await _execute_unified_media_node_run(
            session,
            run=run,
            node=node,
            node_type=node_type,
            snap=snap,
            obj_store=obj_store,
            prompt=prompt,
            canonical_image_bytes=canonical_image_bytes,
            canonical_embedding=canonical_embedding,
            lead_identity_required=lead_identity_required,
            has_canonical_binding=has_canonical_binding,
            face_threshold=face_threshold,
            canonical_artifact=canonical_artifact,
        )

    # Select Adapter: real Agnes when configured. No silent Fake outside test.
    adapter = flux
    if adapter is None:
        from app.config import get_settings as _gs
        from app.providers.flux import (
            ProviderNotConfiguredError,
            get_flux_adapter_for_workspace,
        )
        from app.providers.kling import get_kling_adapter_for_workspace

        _env = _gs().app_env
        allow_fake = _env == "test"
        try:
            if node_type == "voice" and not allow_fake:
                from app.providers.local_tts import get_local_tts_adapter

                adapter = get_local_tts_adapter()
            elif node_type in {"video", "video_review"}:
                adapter = await get_kling_adapter_for_workspace(
                    session,
                    workspace_id=project.workspace_id,
                    allow_fake=allow_fake,
                )
            elif node_type == "voice":
                # TTS off for P0 — only allow deterministic stub under test
                if not allow_fake:
                    raise ProviderNotConfiguredError(
                        "provider_not_configured: TTS disabled (TTS_ENABLED=false). "
                        "Use audited manual media for voice or enable a voice Provider."
                    )
                adapter = FakeFluxAdapter()
            else:
                adapter = await get_flux_adapter_for_workspace(
                    session,
                    workspace_id=project.workspace_id,
                    allow_fake=allow_fake,
                )
        except AppError as exc:
            await _commit_terminal_failure(
                session,
                run=run,
                error_code=exc.code,
                error_summary=exc.message,
            )
            raise

    # Persist the paid attempt before POST. A restart may then resume an existing
    # remote task, but can never mistake it for a new submission.
    kind = node_type
    _settings = get_settings()
    provider_name = str(getattr(adapter, "provider", "flux") or "flux")
    if type(adapter).__name__.startswith("Agnes") or provider_name in {"agnes", "flux"}:
        if node_type in {"video", "video_review"}:
            model_name = _settings.agnes_video_model
        else:
            model_name = _settings.agnes_image_model
    elif type(adapter).__name__.startswith("Fake"):
        model_name = f"fake-{node_type}"
    else:
        model_name = str(getattr(adapter, "model", None) or provider_name)
    op = await session.scalar(
        select(ProviderOperation)
        .where(
            ProviderOperation.node_run_id == run.id,
            ProviderOperation.provider_operation_id.is_not(None),
            ProviderOperation.status.in_({"submitted", "running", "timed_out"}),
        )
        .order_by(ProviderOperation.attempt_no.desc(), ProviderOperation.created_at.desc())
        .limit(1)
    )
    create: dict[str, object]
    if op is None:
        director_context = await _validate_director_submission_or_block(
            session,
            run=run,
            node=node,
        )
        create_request: dict[str, object] = {"prompt": prompt, "kind": kind}
        safe_request_summary: dict[str, object] = {"kind": kind}
        first_frame = None
        if node_type == "keyframe" and lead_identity_required and has_canonical_binding:
            create_request["canonical_image_bytes"] = canonical_image_bytes
            create_request["canonical_image_mime"] = str(
                snap.get("canonical_mime_type") or "image/png"
            )
            if snap.get("canonical_artifact_id"):
                create_request["canonical_artifact_id"] = str(snap["canonical_artifact_id"])
                safe_request_summary["reference_artifact_ids"] = [
                    str(snap["canonical_artifact_id"])
                ]
            if canonical_image_bytes:
                safe_request_summary["reference_fingerprints"] = [
                    hashlib.sha256(canonical_image_bytes).hexdigest()
                ]
                safe_request_summary["reference_transport"] = "data_uri"
        if node_type == "video" and provider_name == "agnes":
            from app.providers.reference_delivery import approved_first_frame_for_video

            first_frame = await approved_first_frame_for_video(session, video_run=run)
            # Agnes China accepts a base64 Data URI for the I2V first-frame
            # (verified 2026-08-04: data URI -> video task completed). This
            # removes the public HTTPS origin dependency for the P0 video chain.
            try:
                first_frame_bytes = await obj_store.get_bytes(
                    object_key=first_frame.object_key
                )
            except Exception:
                first_frame_bytes = None
            if not first_frame_bytes:
                raise ValidationAppError(
                    "UPSTREAM_ARTIFACT_MISSING: approved first-frame bytes unavailable "
                    "for video I2V"
                )
            create_request.update(
                {
                    "image_bytes": first_frame_bytes,
                    "image_mime": first_frame.mime_type or "image/png",
                    "num_frames": _snapshot_int(snap.get("num_frames"), default=121),
                    "frame_rate": _snapshot_int(snap.get("frame_rate"), default=24),
                    "reference_artifact_ids": [str(first_frame.id)],
                    "reference_fingerprints": [first_frame.content_hash],
                }
            )
            safe_request_summary.update(
                {
                    "reference_artifact_ids": [str(first_frame.id)],
                    "reference_fingerprints": [first_frame.content_hash],
                    "reference_transport": "data_uri",
                    "num_frames": create_request["num_frames"],
                    "frame_rate": create_request["frame_rate"],
                }
            )
        initial_fingerprint = hashlib.sha256(
            f"{kind}:{prompt}:{safe_request_summary}".encode()
        ).hexdigest()
        if director_context is not None:
            await _validate_director_submission_or_block(
                session,
                run=run,
                node=node,
            )
        # Idempotent: a 429 requeue re-executes this node_run; reuse the single
        # ProviderOperation row (uq_provider_operations_node_run) instead of
        # inserting a duplicate.
        op = (
            await session.execute(
                select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
            )
        ).scalars().first()
        if op is None:
            op = ProviderOperation(
                node_run_id=run.id,
                attempt_no=run.attempt_no,
                purpose="primary",
                operation_kind=f"{node_type}.generate",
                actual_provider=provider_name,
                actual_model=model_name,
                provider_operation_id=None,
                protocol_profile=str(getattr(adapter, "protocol_profile", "") or "") or None,
                request_fingerprint=initial_fingerprint,
                status="created",
                request_summary=safe_request_summary,
                response_summary={},
                submitted_at=datetime.now(UTC),
            )
            session.add(op)
        else:
            op.status = "created"
            op.error_code = None
            op.error_summary = None
            op.provider_operation_id = None
            op.request_fingerprint = initial_fingerprint
            op.request_summary = safe_request_summary
            op.response_summary = {}
            op.submitted_at = datetime.now(UTC)
            op.completed_at = None
        await session.flush()
        await session.commit()
        await set_node_run_rls_context(session, node_run_id=run.id)
        if director_context is not None:
            await _validate_director_submission_or_block(
                session,
                run=run,
                node=node,
                provider_operation=op,
            )
        if (
            get_settings().provider_unified_shadow
            and provider_name in {"agnes", "volcengine"}
            and node_type in {"keyframe", "video"}
        ):
            # Stage B1: observe whether the unified path resolves to the same
            # model before the legacy path pays for a submission.
            await _run_shadow_selection(
                session,
                project=project,
                node_type=node_type,
                prompt=prompt,
                first_frame=first_frame,
                op=op,
                legacy_provider=provider_name,
                legacy_model=model_name,
            )
        try:
            create = await adapter.create(create_request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider boundary is sanitized
            create = {
                "status": "failed",
                "error": f"provider create raised {type(exc).__name__}",
            }
        create_status = str(create.get("status", "unknown"))
        create_rejected = create_status in {"failed", "error", "cancelled"}
        remote_value = create.get("remote_task_id")
        remote = str(remote_value) if remote_value else ""
        op.actual_provider = str(create.get("actual_provider") or provider_name)
        op.actual_model = str(create.get("actual_model") or model_name)
        op.protocol_profile = (
            str(create.get("protocol_profile"))
            if create.get("protocol_profile")
            else op.protocol_profile
        )
        op.provider_operation_id = remote if remote and not create_rejected else None
        secondary = create.get("remote_secondary_id")
        op.remote_secondary_id = str(secondary) if secondary else None
        op.request_fingerprint = str(
            create.get("request_fingerprint")
            or create.get("effective_prompt_fingerprint")
            or initial_fingerprint
        )
        adapter_summary = create.get("request_summary")
        if isinstance(adapter_summary, dict):
            op.request_summary = {**safe_request_summary, **adapter_summary}
        op.response_summary = {
            "create_status": create_status,
            "query_kind": create.get("query_kind"),
        }
    else:
        remote = str(op.provider_operation_id)
        create_status = "resumed"
        query_kind = (op.response_summary or {}).get("query_kind")
        create = {
            "status": "running",
            "remote_task_id": remote,
            "remote_secondary_id": op.remote_secondary_id,
            "query_kind": query_kind,
        }
        op.status = "running"
        op.error_code = None
        op.error_summary = None

    create_unknown = create_status == "unknown_submission"
    create_failed = create_status in {"failed", "error", "cancelled"}
    if create_unknown:
        op.status = "unknown_submission"
        op.error_code = str(create.get("error_code") or "PROVIDER_SUBMISSION_UNKNOWN")
        op.error_summary = "Provider submission outcome is unknown; manual reconciliation required"
        op.completed_at = datetime.now(UTC)
        await _commit_terminal_failure(
            session,
            run=run,
            error_code="PROVIDER_SUBMISSION_UNKNOWN",
            error_summary=op.error_summary,
        )
        raise ValidationAppError("PROVIDER_SUBMISSION_UNKNOWN")

    if create_failed:
        create_error = str(create.get("error") or "provider rejected task creation")[:500]
        # 429 rate limit: defer and retry after Retry-After (plan §11.2), never
        # mark the node terminally failed on a transient provider throttle.
        if str(create.get("error_code")) == "PROVIDER_RATE_LIMITED":
            raw_retry_after = create.get("retry_after_seconds")
            try:
                retry_after = float(str(raw_retry_after)) if raw_retry_after else 5.0
            except (TypeError, ValueError):
                retry_after = 5.0
            op.status = "failed"
            op.error_code = "PROVIDER_RATE_LIMITED"
            op.error_summary = create_error
            op.completed_at = datetime.now(UTC)
            await session.flush()
            from app.shared.errors import ProviderRateLimitedError

            raise ProviderRateLimitedError(retry_after_seconds=retry_after)
        op.status = "failed"
        op.error_code = "PROVIDER_CREATE_FAILED"
        op.error_summary = create_error
        op.response_summary = {
            "create_status": create_status,
            "create_error": create_error[:300],
        }
        op.completed_at = datetime.now(UTC)
        await _commit_terminal_failure(
            session,
            run=run,
            error_code="PROVIDER_CREATE_FAILED",
            error_summary=create_error,
        )
        raise ValidationAppError(f"PROVIDER_CREATE_FAILED: {create_error}")

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

    op.status = "submitted"
    await session.flush()
    await session.commit()
    await set_node_run_rls_context(session, node_run_id=run.id)

    # Provider video tasks can stay running for several minutes. Keep polling
    # inside the heavy worker's 30-minute job budget; never submit a second task.
    poll_timeout_s = 1_620.0 if node_type in {"video", "video_review"} else 120.0
    poll_interval_s = 5.0 if node_type in {"video", "video_review"} else 3.0
    deadline = asyncio.get_running_loop().time() + poll_timeout_s
    poll: dict[str, object] = {"status": str(create.get("status", "queued"))}
    poll_count = 0
    while True:
        persisted_poll = getattr(adapter, "poll_persisted", None)
        if node_type == "video" and op.actual_provider == "agnes" and callable(persisted_poll):
            poll = await persisted_poll(
                remote,
                query_kind=(op.response_summary or {}).get("query_kind"),
            )
        else:
            poll = await adapter.poll(remote)
        poll_count += 1
        status = str(poll.get("status", "failed"))
        op.last_polled_at = datetime.now(UTC)
        op.status = "running"
        poll_error = poll.get("poll_error")
        if poll_error:
            # Plan §11.2: transient poll errors are recorded, never terminal.
            summary = dict(op.response_summary or {})
            summary["last_poll_error"] = str(poll_error)[:200]
            prior_count = summary.get("poll_error_count")
            summary["poll_error_count"] = (
                int(prior_count) if isinstance(prior_count, int) else 0
            ) + 1
            http_status = poll.get("http_status")
            if isinstance(http_status, int):
                summary["last_poll_http_status"] = http_status
            op.response_summary = summary
            # Persist transient poll-error evidence immediately. Without this a
            # worker crash mid-poll rolls back the in-loop mutation and the 429/5xx
            # bookkeeping is silently lost even though the remote task survives.
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
            poll_trail = dict(op.response_summary or {})
            op.response_summary = {
                "create_status": str(create.get("status", "unknown")),
                "final_status": "running",
                "poll_count": poll_count,
                "query_kind": poll_trail.get("query_kind"),
            }
            if poll_trail.get("poll_error_count"):
                # Keep transient poll-error bookkeeping visible on a pending task.
                op.response_summary["last_poll_error"] = poll_trail.get("last_poll_error")
                op.response_summary["poll_error_count"] = poll_trail["poll_error_count"]
                if poll_trail.get("last_poll_http_status"):
                    op.response_summary["last_poll_http_status"] = poll_trail[
                        "last_poll_http_status"
                    ]
            run.status = "queued"
            run.error_code = "PROVIDER_TASK_PENDING"
            run.error_summary = "Remote Provider task is still running"
            run.output_summary = {
                "status": "provider_pending",
                "provider_operation_id": str(op.id),
            }
            await session.commit()
            raise ProviderTaskPendingError()
        poll_retry_after = poll.get("retry_after_seconds")
        sleep_s = poll_interval_s
        if isinstance(poll_retry_after, int | float) and poll_retry_after > 0:
            sleep_s = max(sleep_s, float(poll_retry_after))
        await asyncio.sleep(min(sleep_s, remaining))

    cost = await adapter.fetch_cost(remote)
    status = str(poll.get("status", "failed"))
    op.provider_cost = Decimal(str(cost.get("amount", 0.0)))
    op.currency = str(cost.get("currency", "USD"))
    poll_trail = dict(op.response_summary or {})
    op.response_summary = {
        "create_status": str(create.get("status", "unknown")),
        "final_status": status,
        "poll_count": poll_count,
        "query_kind": poll_trail.get("query_kind"),
    }
    if poll_trail.get("poll_error_count"):
        op.response_summary["last_poll_error"] = poll_trail.get("last_poll_error")
        op.response_summary["poll_error_count"] = poll_trail["poll_error_count"]
        if poll_trail.get("last_poll_http_status"):
            op.response_summary["last_poll_http_status"] = poll_trail["last_poll_http_status"]
    if run.production_batch_id is not None and run.budget_reservation_id is not None:
        from app.director.execution_guard import settle_director_media_cost

        await settle_director_media_cost(session, run=run, operation=op)
    if status not in {"succeeded", "completed", "success"}:
        error_summary = str(poll.get("error") or status)[:500]
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
    adapter_blobs = getattr(adapter, "blobs", {})
    if remote in adapter_blobs:
        data = adapter_blobs[remote]
    else:
        uri = poll.get("artifact_uri") or create.get("artifact_uri")
        data = await _resolve_media_bytes(kind=kind, remote=remote, prompt=prompt, artifact_uri=uri)

    # Node-specific mime / key
    mime, ext, art_type = _mime_for_node(node_type)
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

    face_status: str | None = None
    face_score: float | None = None
    if node_type in {"keyframe", "face_review"}:
        # Two-source review only. Never self-match probe to itself.
        lead_identity_required = snap.get("lead_identity_required") is True
        if not lead_identity_required:
            face_status = "not_applicable"
        elif canonical_image_bytes is not None:
            review = face_review_images(
                probe_image_bytes=data,
                canonical_image_bytes=canonical_image_bytes,
                threshold=face_threshold,
            )
            face_status = review.status
            face_score = review.score
        else:
            face_status = "needs_human"
            face_score = None

    run.status = "completed"
    run.result_artifact_id = art.id
    run.provider_cost = op.provider_cost or Decimal("0")
    run.finished_at = datetime.now(UTC)
    run.output_summary = {
        "artifact_id": str(art.id),
        "node_type": node_type,
        "face_review": face_status,
        "face_score": face_score,
        "byte_size": art.byte_size,
        "content_hash": art.content_hash,
        "source_commit": _settings.source_commit,
        "face_policy": approved_face_policy_snapshot(),
        "face_threshold": face_threshold,
    }
    node.latest_successful_run_id = run.id
    await session.flush()
    return ExecuteNodeResult(
        node_run_id=run.id,
        artifact_id=art.id,
        object_key=art.object_key,
        content_hash=art.content_hash,
        byte_size=art.byte_size,
        face_status=face_status,
        face_score=face_score,
        provider_operation_id=op.id,
        node_type=node_type,
    )


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
        face_status=(
            str(output.get("face_review")) if output.get("face_review") is not None else None
        ),
        face_score=(
            float(str(output["face_score"])) if output.get("face_score") is not None else None
        ),
        provider_operation_id=None,
        node_type=node_type,
    )


def _mime_for_node(node_type: str) -> tuple[str, str, str]:
    if node_type in {"keyframe", "face_review", "prompt_compose", "prompt"}:
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
    node.latest_successful_run_id = run.id
    await session.flush()
    return ExecuteNodeResult(
        node_run_id=run.id,
        artifact_id=art.id,
        object_key=art.object_key,
        content_hash=art.content_hash,
        byte_size=art.byte_size,
        face_status=None,
        face_score=None,
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
    face_threshold: float,
    prompt: str,
) -> ExecuteNodeResult:
    """Complete review/subtitle/prompt nodes without Provider (zero cost)."""
    import json
    from datetime import UTC, datetime

    from app.config import get_settings
    from app.consistency.continuity import continuity_four_layers
    from app.consistency.image_embed import insightface_status

    face_status: str | None = None
    face_score: float | None = None
    review_status = "passed"
    payload: dict[str, object] = {
        "run_id": str(run.id),
        "shot_id": str(snap.get("shot_id") or ""),
        "node_type": node_type,
        "node_key": node.node_key,
        "zero_provider_cost": True,
    }

    key = node.node_key
    if key == "face_review" or node_type == "face_review":
        if snap.get("lead_identity_required") is not True:
            face_status = "not_applicable"
            face_score = None
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
                review = face_review_images(
                    probe_image_bytes=probe,
                    canonical_image_bytes=canonical,
                    threshold=face_threshold,
                )
                face_status = review.status
                face_score = review.score
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
                face_status = "blocked"
                review_status = "blocked"
                payload.update(
                    {
                        "review_rule": "invalid_two_source_binding",
                        "review_error_code": str(exc.details.get("code") or exc.code),
                    }
                )
        st = insightface_status()
        payload.update(
            {
                "status": review_status,
                "face_review": face_status,
                "face_score": face_score,
                "insightface_backend": st.get("backend"),
                "insightface_available": st.get("available"),
            }
        )
        data = json.dumps(payload, sort_keys=True).encode()
        mime, ext, art_type = "application/json", "json", "document"
    elif key == "video_drift_review" or node_type == "video_review":
        from app.consistency.video_drift import (
            VIDEO_DRIFT_POLICY_ID,
            VIDEO_DRIFT_POLICY_STATUS,
            VIDEO_DRIFT_SAMPLING_VERSION,
            VIDEO_DRIFT_THRESHOLD,
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
                        "drift_mean_score": decision.get("mean_score"),
                        "drift_scored_frames": decision.get("scored_frames"),
                        "drift_unscorable_frames": decision.get("unscorable_frames"),
                        "drift_min_score": decision.get("min_score"),
                        "drift_max_score": decision.get("max_score"),
                        "drift_frames_above_threshold": decision.get("frames_above_threshold"),
                        "video_drift_policy": {
                            "status": VIDEO_DRIFT_POLICY_STATUS,
                            "sampling_version": VIDEO_DRIFT_SAMPLING_VERSION,
                            "threshold": VIDEO_DRIFT_THRESHOLD,
                            "approval_id": VIDEO_DRIFT_POLICY_ID,
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
                            "threshold": VIDEO_DRIFT_THRESHOLD,
                            "approval_id": VIDEO_DRIFT_POLICY_ID,
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
            if key in {"face_review", "video_drift_review", "continuity_review"}
            or node_type in {"face_review", "video_review", "continuity_review"}
            else "passed"
        ),
        "face_review": face_status,
        "face_score": face_score,
        "byte_size": art.byte_size,
        "content_hash": art.content_hash,
        "source_commit": get_settings().source_commit,
        "face_policy": approved_face_policy_snapshot(),
        "face_threshold": face_threshold,
    }
    node.latest_successful_run_id = run.id
    await session.flush()
    return ExecuteNodeResult(
        node_run_id=run.id,
        artifact_id=art.id,
        object_key=art.object_key,
        content_hash=art.content_hash,
        byte_size=art.byte_size,
        face_status=face_status,
        face_score=face_score,
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
