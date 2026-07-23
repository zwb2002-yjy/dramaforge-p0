"""Product execution path: enqueue NodeRun for Worker (no Adapter in request thread)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.consistency.face_review import face_review_images
from app.creation.models import CreationPlan
from app.execution.artifact_lineage import get_or_create_artifact
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.execution.shot_pipeline import (
    SHOT_PIPELINE_NODES,
    SHOT_PIPELINE_TEMPLATE_KEY,
    shot_pipeline_definition,
)
from app.production.service import GraphService
from app.providers.fake import FakeFluxAdapter
from app.shared.db import set_rls_context
from app.shared.errors import NodeRunAlreadyClaimedError, ValidationAppError
from app.storage.minio_store import ObjectStore, get_object_store


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
    provider_operation_id: UUID
    node_type: str


# Back-compat alias
ExecuteKeyframeResult = ExecuteNodeResult


def _input_hash(payload: dict[str, object]) -> str:
    raw = repr(sorted(payload.items())).encode()
    return hashlib.sha256(raw).hexdigest()


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
            raise NodeRunAlreadyClaimedError()
        raise ValidationAppError(f"node_run cannot execute from status={run.status}")

    user_id = run.created_by
    project_id = run.project_id
    await session.commit()
    await set_rls_context(
        session,
        user_id=user_id,
        project_id=project_id,
    )
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
        ),
    )
    assert graph.current_version_id is not None
    version = await graphs.get_version(graph.current_version_id)
    nodes: dict[str, GraphNode] = {}
    for spec in SHOT_PIPELINE_NODES:
        node = GraphNode(
            graph_version_id=version.id,
            node_key=spec.key,
            node_type=spec.node_type,
            display_name=spec.display_name,
            cacheable=True,
        )
        session.add(node)
        nodes[spec.key] = node
    await session.flush()
    node = nodes["keyframe"]
    # Attach project lead canonical if registered (P0 face gate / consistency).
    from sqlalchemy import select

    from app.assets.models import Asset, Character, CharacterReference

    canon_key: str | None = None
    ref = (
        await session.execute(
            select(CharacterReference)
            .join(Character, Character.id == CharacterReference.character_id)
            .join(Asset, Asset.id == Character.id)
            .where(Asset.project_id == project_id)
            .where(CharacterReference.is_canonical.is_(True))
            .limit(1)
        )
    ).scalar_one_or_none()
    if ref is not None:
        canon_key = ref.object_key

    snapshot: dict[str, object] = {
        "plan_id": str(plan.id),
        "shot_id": str(shot_id),
        "node_key": "keyframe",
        "plan": {
            "prompt": prompt,
            "shot": shot_body,
            "visual_bible": plan.plan.get("visual_bible", {}),
        },
        "prompt": prompt,
        "materialization": materialization_ops,
    }
    if canon_key:
        snapshot["canonical_object_key"] = canon_key
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
    flux: FakeFluxAdapter | None = None,
    face_threshold: float = 0.35,
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
        face_threshold=face_threshold,
        require_canonical=require_canonical,
        canonical_embedding=canonical_embedding,
        canonical_image_bytes=canonical_image_bytes,
    )


async def execute_media_node_run(
    session: AsyncSession,
    *,
    node_run_id: UUID,
    store: ObjectStore | None = None,
    flux: FakeFluxAdapter | None = None,
    face_threshold: float = 0.35,
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
    snap = run.input_snapshot or {}
    # Resolve canonical from snapshot object key before enforce (Worker path).
    if canonical_image_bytes is None:
        snap_canon = snap.get("canonical_object_key")
        if isinstance(snap_canon, str) and snap_canon:
            try:
                canonical_image_bytes = await obj_store.get_bytes(object_key=snap_canon)
            except Exception:
                canonical_image_bytes = None
    if require_canonical and canonical_embedding is None and canonical_image_bytes is None:
        run.status = "failed"
        run.error_code = "CANONICAL_REFERENCE_REQUIRED"
        run.error_summary = "canonical reference required"
        await session.flush()
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

    # Select Adapter: real Agnes when configured. No silent Fake outside test.
    adapter = flux
    if adapter is None:
        from app.config import get_settings as _gs
        from app.providers.flux import ProviderNotConfiguredError, get_flux_adapter
        from app.providers.kling import get_kling_adapter

        _env = _gs().app_env
        allow_fake = _env == "test"
        try:
            if node_type == "voice" and not allow_fake:
                from app.providers.local_tts import get_local_tts_adapter

                adapter = get_local_tts_adapter()
            elif node_type in {"video", "video_review", "composite"}:
                adapter = get_kling_adapter(allow_fake=allow_fake)
            elif node_type == "voice":
                # TTS off for P0 — only allow deterministic stub under test
                if not allow_fake:
                    raise ProviderNotConfiguredError(
                        "provider_not_configured: TTS disabled (TTS_ENABLED=false). "
                        "Use audited manual media for voice or enable a voice Provider."
                    )
                adapter = FakeFluxAdapter()
            else:
                adapter = get_flux_adapter(allow_fake=allow_fake)
        except ProviderNotConfiguredError as exc:
            run.status = "failed"
            run.error_code = "PROVIDER_NOT_CONFIGURED"
            run.error_summary = exc.message[:500]
            run.finished_at = datetime.now(UTC)
            await session.flush()
            raise

    # Produce media bytes by node type via Adapter contract
    kind = node_type
    create = await adapter.create({"prompt": prompt, "kind": kind})
    remote = str(create.get("remote_task_id") or uuid4())
    # Video may stay queued — poll a few times when not immediate
    poll = await adapter.poll(remote)
    for _ in range(40):
        status = str(poll.get("status", "failed"))
        if status in {"succeeded", "completed", "success", "failed", "cancelled"}:
            break
        import asyncio

        await asyncio.sleep(3.0)
        poll = await adapter.poll(remote)
    cost = await adapter.fetch_cost(remote)
    status = str(poll.get("status", "failed"))
    if status not in {"succeeded", "completed", "success"}:
        run.status = "failed"
        run.error_code = "PROVIDER_FAILED"
        run.error_summary = str(poll.get("error") or status)[:500]
        run.finished_at = datetime.now(UTC)
        await session.flush()
        raise ValidationAppError(f"PROVIDER_FAILED: {run.error_summary}")

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

    from app.config import get_settings

    _settings = get_settings()
    provider_name = str(getattr(adapter, "provider", "flux") or "flux")
    if type(adapter).__name__.startswith("Agnes") or provider_name in {"agnes", "flux"}:
        if node_type in {"video", "video_review", "composite"}:
            model_name = _settings.agnes_video_model
        else:
            model_name = _settings.agnes_image_model
    elif type(adapter).__name__.startswith("Fake"):
        model_name = f"fake-{node_type}"
    else:
        model_name = str(getattr(adapter, "model", None) or provider_name)

    op = ProviderOperation(
        node_run_id=run.id,
        attempt_no=1,
        purpose="primary",
        operation_kind=f"{node_type}.generate",
        actual_provider=provider_name,
        actual_model=model_name,
        provider_operation_id=remote,
        request_fingerprint=hashlib.sha256(f"{kind}:{prompt}".encode()).hexdigest(),
        status="succeeded",
        request_summary={"kind": kind},
        response_summary={"status": status},
        provider_cost=Decimal(str(cost.get("amount", 0.0))),
        currency=str(cost.get("currency", "USD")),
    )
    session.add(op)
    await session.flush()

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
        if canonical_image_bytes is not None:
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
        provider_operation_id=uuid4(),
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
    if key in {"face_review", "video_drift_review"} or node_type in {
        "face_review",
        "video_review",
    }:
        # Compare probe (prior keyframe bytes if present) vs canonical.
        probe = None
        probe_key = snap.get("probe_object_key") or snap.get("keyframe_object_key")
        if isinstance(probe_key, str) and probe_key:
            try:
                probe = await obj_store.get_bytes(object_key=probe_key)
            except Exception:
                probe = None
        if probe is None and isinstance(snap.get("probe_bytes_b64"), str):
            import base64

            try:
                probe = base64.b64decode(str(snap["probe_bytes_b64"]))
            except Exception:
                probe = None
        # Fall back: find latest keyframe artifact for this shot via snapshot shot_id
        if probe is None:
            from sqlalchemy import select

            shot_id = str(snap.get("shot_id") or "")
            arts = list(
                (
                    await session.execute(
                        select(Artifact)
                        .where(Artifact.project_id == run.project_id)
                        .where(Artifact.storage_state == "available")
                        .where(Artifact.artifact_type == "image")
                        .order_by(Artifact.created_at.desc())
                        .limit(20)
                    )
                )
                .scalars()
                .all()
            )
            for a in arts:
                if shot_id and shot_id in (a.object_key or ""):
                    try:
                        probe = await obj_store.get_bytes(object_key=a.object_key)
                        break
                    except Exception:
                        continue
            if probe is None and arts:
                try:
                    probe = await obj_store.get_bytes(object_key=arts[0].object_key)
                except Exception:
                    probe = None

        if probe is not None and canonical_image_bytes is not None:
            review = face_review_images(
                probe_image_bytes=probe,
                canonical_image_bytes=canonical_image_bytes,
                threshold=face_threshold,
            )
            face_status = review.status
            face_score = review.score
            review_status = review.status
        elif probe is not None:
            face_status = "needs_human"
            review_status = "needs_human"
        else:
            face_status = "needs_human"
            review_status = "needs_human"
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
        data = f"1\n00:00:00,000 --> 00:00:02,000\n{text}\n".encode()
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
        provider_operation_id=uuid4(),
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

    if isinstance(artifact_uri, str) and artifact_uri:
        if artifact_uri.startswith("data:") and "," in artifact_uri:
            import base64

            _, b64 = artifact_uri.split(",", 1)
            return base64.b64decode(b64)
        if artifact_uri.startswith("http://") or artifact_uri.startswith("https://"):
            import httpx

            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                resp = await client.get(artifact_uri)
                resp.raise_for_status()
                return resp.content
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
