"""Unified Generation API service (V3 spec §58, §44).

Standalone generation operations are backed by the existing NodeRun engine: a
minimal one-node graph + NodeRun is created exactly like the canonical-image
path, then dispatched through the standard Worker (Outbox + Arq) — so the full
submission safety machinery (submit-once, submit-unknown, resume-no-recreate,
artifact import, RLS) is inherited with zero new submission code.

Intent idempotency reuses ``NodeRun.idempotency_key`` + the existing
``UNIQUE(project_id, idempotency_key)``: the API's Idempotency-Key maps to a
deterministic generation key, so a retry returns the SAME operation instead of
submitting twice (spec §44/§43 — no second intent table).

P0 supports ``image.generate`` standalone (T2I/I2I). Video modes require the
Shot gate chain (keyframe → face → video) and stay with the production
pipeline; text modes run through the existing Agent Brief/Plan API. The API
rejects unsupported capabilities explicitly rather than guessing a degraded
execution path (spec §2.6).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.config import get_settings
from app.execution.models import GraphNode, NodeRun
from app.providers.capabilities import Capability
from app.providers.contracts import ArtifactRef, ImageGenerateRequest
from app.providers.idempotency import v3_request_fingerprint
from app.providers.router import CapabilityRouter
from app.runtime.scheduler import AgentRunScheduler
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

# Capabilities the standalone Generation API can execute in P0. Each maps to a
# NodeRun node_type the unified executor already drives.
_STANDALONE_NODE_TYPE: dict[Capability, str] = {
    Capability.IMAGE_GENERATE: "keyframe",
}

_GENERATION_TEMPLATE_KEY = "generation-v1"


class GenerationService:
    """Creates and drives standalone generation operations."""

    def __init__(self, session: AsyncSession, router: CapabilityRouter) -> None:
        self._session = session
        self._router = router

    async def create_generation(
        self,
        *,
        project: Project,
        actor: User,
        capability: Capability,
        model_id: str | None,
        input_data: dict[str, Any],
        options: dict[str, Any],
        native_options: dict[str, Any],
        idempotency_key: str | None,
    ) -> NodeRun:
        node_type = _STANDALONE_NODE_TYPE.get(capability)
        if node_type is None:
            raise ValidationAppError(
                f"capability is not supported for standalone generation: {capability}",
                details={
                    "code": "CAPABILITY_NOT_STANDALONE",
                    "capability": str(capability),
                    "hint": "video modes use the Shot pipeline; text modes use the Agent API",
                },
            )
        request = _build_request(
            capability,
            input_data=input_data,
            options=options,
            native_options=native_options,
        )
        # Resolve + validate through the CapabilityRouter (spec §33/§58). The
        # manifest is also needed to seed the run snapshot.
        model = self._router.selector.select(
            capability=capability,
            requested_model=model_id,
            registry=self._router.registry,
        )
        spec = model.manifest.capability_specs.get(capability)
        if spec is None:
            raise ValidationAppError(
                f"model does not support capability: {capability}",
                details={"code": "UNSUPPORTED_CAPABILITY", "capability": str(capability)},
            )
        self._router.validator.validate(request, spec)

        fingerprint = v3_request_fingerprint(capability, request, model_id=model.manifest.id)

        # Intent idempotency: deterministic NodeRun key per (idempotency_key).
        if idempotency_key:
            existing = await self._session.scalar(
                select(NodeRun).where(
                    NodeRun.project_id == project.id,
                    NodeRun.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return existing

        shot_id = uuid4()
        prompt = str(request.prompt)
        snapshot: dict[str, object] = {
            "plan_id": "",
            "shot_id": str(shot_id),
            "node_key": node_type,
            "source_commit": get_settings().source_commit,
            "plan": {
                "prompt": prompt,
            },
            "prompt": prompt,
            "materialization": [],
            "lead_identity_required": False,
            "generation": {
                "capability": str(capability),
                "requested_model": model.manifest.id,
                "request_fingerprint": fingerprint,
            },
        }

        run = await _create_generation_run(
            self._session,
            project=project,
            user_id=actor.id,
            node_type=node_type,
            node_key=node_type,
            snapshot=snapshot,
            idempotency_key=idempotency_key or fingerprint,
            input_hash=fingerprint,
        )
        return run

    async def enqueue(self, run: NodeRun) -> str:
        scheduler = AgentRunScheduler(self._session)
        return await scheduler.enqueue_node_run_only(run.id)

    async def get_generation(self, *, project: Project, operation_id: UUID) -> NodeRun:
        run = await self._session.scalar(
            select(NodeRun).where(
                NodeRun.id == operation_id,
                NodeRun.project_id == project.id,
            )
        )
        if run is None:
            raise NotFoundError("generation operation not found")
        return run

    async def cancel_generation(self, *, project: Project, operation_id: UUID) -> NodeRun:
        run = await self.get_generation(project=project, operation_id=operation_id)
        if run.status not in {"queued", "running"}:
            raise ConflictError("generation is not cancellable in its current state")
        run.status = "cancel_requested"
        run.cancellation_requested_at = datetime.now(UTC)
        await self._session.flush()
        return run


def _build_request(
    capability: Capability,
    *,
    input_data: dict[str, Any],
    options: dict[str, Any],
    native_options: dict[str, Any],
) -> ImageGenerateRequest:
    if capability is not Capability.IMAGE_GENERATE:
        raise ValidationAppError(
            f"capability is not supported for standalone generation: {capability}",
            details={"code": "CAPABILITY_NOT_STANDALONE", "capability": str(capability)},
        )
    prompt = str(input_data.get("prompt") or "")
    if not prompt.strip():
        raise ValidationAppError("prompt is required", details={"code": "REQUEST_INVALID"})
    reference_images = [
        ArtifactRef(artifact_id=str(ref["artifact_id"]))
        for ref in input_data.get("reference_images", [])
        if isinstance(ref, dict) and ref.get("artifact_id")
    ]
    try:
        return ImageGenerateRequest(
            prompt=prompt,
            reference_images=reference_images,
            size=options.get("size"),
            seed=options.get("seed"),
            native_options=native_options,
        )
    except Exception as exc:  # noqa: BLE001 - pydantic validation surfaced to API
        raise ValidationAppError(
            f"generation request is invalid for {capability}",
            details={"code": "REQUEST_INVALID", "error": str(exc)[:300]},
        ) from exc


async def _create_generation_run(
    session: AsyncSession,
    *,
    project: Project,
    user_id: UUID,
    node_type: str,
    node_key: str,
    snapshot: dict[str, object],
    idempotency_key: str,
    input_hash: str,
) -> NodeRun:
    """Create the one-node graph + queued NodeRun that backs a generation op."""
    from app.production.service import GraphService

    graphs = GraphService(session)
    graph = await graphs.create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key=_GENERATION_TEMPLATE_KEY,
        created_by=user_id,
        definition={
            "nodes": [
                {
                    "key": node_key,
                    "type": node_type,
                    "display_name": "Generation",
                }
            ],
            "edges": [],
        },
    )
    assert graph.current_version_id is not None
    node = GraphNode(
        graph_version_id=graph.current_version_id,
        node_key=node_key,
        node_type=node_type,
        display_name="Generation",
        cacheable=False,
    )
    session.add(node)
    await session.flush()
    run = NodeRun(
        project_id=project.id,
        graph_version_id=graph.current_version_id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=idempotency_key,
        input_hash=input_hash,
        status="queued",
        input_snapshot=snapshot,
        created_by=user_id,
    )
    session.add(run)
    await session.flush()
    return run
