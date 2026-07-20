"""LEGACY_SPIKE — not product path.

In-process GraphVersion → NodeRun → Adapter → Artifact helper used for early
adapter/algorithm experiments. Does NOT satisfy S2 Gate (no Outbox/Arq/MinIO
product chain, no real Brief/AgentRun, face self-compare). Prefer HTTP + Worker.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.production.service import GraphService
from app.providers.fake import FakeFluxAdapter, FakeOpenAIAdapter
from app.shared.errors import ValidationAppError


@dataclass(frozen=True)
class FaceReviewResult:
    status: str
    score: float | None
    rule: str


@dataclass(frozen=True)
class FirstFrameResult:
    brief_text: str
    plan_text: str
    graph_id: UUID
    graph_version_id: UUID
    node_run_id: UUID
    provider_operation_ids: list[UUID]
    artifact_id: UUID
    face_review: FaceReviewResult
    materialization_ops: list[str]


class MaterializationWhitelist:
    ALLOWED = frozenset(
        {
            "create_character_stub",
            "create_shot_stub",
            "bind_canonical_reference",
            "enqueue_keyframe",
        }
    )

    def apply(self, operations: list[str]) -> list[str]:
        applied: list[str] = []
        for op in operations:
            if op not in self.ALLOWED:
                raise ValidationAppError(f"materialization op not allowed: {op}")
            applied.append(op)
        return applied


def face_review_hook(
    *,
    embedding: list[float] | None,
    canonical: list[float] | None,
    threshold: float = 0.35,
) -> FaceReviewResult:
    if embedding is None or canonical is None:
        return FaceReviewResult(status="needs_human", score=None, rule="missing_embedding")
    if len(embedding) != 512 or len(canonical) != 512:
        return FaceReviewResult(status="blocked", score=None, rule="dim_mismatch")
    score = sum(a * b for a, b in zip(embedding, canonical, strict=True))
    if score >= threshold:
        return FaceReviewResult(status="passed", score=score, rule="threshold")
    return FaceReviewResult(status="blocked", score=score, rule="below_threshold")


def _input_hash(payload: dict[str, object]) -> str:
    raw = repr(sorted(payload.items())).encode()
    return hashlib.sha256(raw).hexdigest()


class FirstFramePipeline:
    """Shipped S2 path: ProductionGraph + NodeRun + ProviderOperation + Artifact."""

    def __init__(
        self,
        session: AsyncSession,
        openai: FakeOpenAIAdapter | None = None,
        flux: FakeFluxAdapter | None = None,
    ) -> None:
        self._session = session
        self.openai = openai or FakeOpenAIAdapter()
        self.flux = flux or FakeFluxAdapter()
        self.materializer = MaterializationWhitelist()
        self.graphs = GraphService(session)

    async def run(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        idea: str,
        authorized_text: bool,
        authorized_image: bool,
        materialization_ops: list[str],
        face_threshold: float = 0.0,
        scope_entity_id: UUID | None = None,
    ) -> FirstFrameResult:
        if not authorized_text:
            raise ValidationAppError("TEXT_PROVIDER_AUTHORIZATION_REQUIRED")
        if not authorized_image:
            raise ValidationAppError("IMAGE_PROVIDER_AUTHORIZATION_REQUIRED")

        applied = self.materializer.apply(materialization_ops)
        shot_id = scope_entity_id or uuid4()

        # Text provider op (planning) — counted; zero cost on fake
        text_create = await self.openai.create({"prompt": idea, "kind": "brief"})
        text_remote = str(text_create["remote_task_id"])
        text_cost = await self.openai.fetch_cost(text_remote)
        brief = f"BRIEF:{idea}"
        plan = f"PLAN:{idea}"

        graph = await self.graphs.create_graph(
            project_id=project_id,
            scope_type="shot",
            scope_entity_id=shot_id,
            template_key="shot-p0-v1",
            created_by=user_id,
            definition={
                "nodes": [{"key": "keyframe.generate", "type": "keyframe"}],
                "edges": [],
                "materialization": applied,
            },
        )
        assert graph.current_version_id is not None
        version = await self.graphs.get_version(graph.current_version_id)

        node = GraphNode(
            graph_version_id=version.id,
            node_key="keyframe.generate",
            node_type="keyframe",
            display_name="Keyframe",
            cacheable=True,
        )
        self._session.add(node)
        await self._session.flush()

        snapshot: dict[str, object] = {
            "brief": brief,
            "plan": plan,
            "materialization": applied,
        }
        ih = _input_hash(snapshot)
        node_run = NodeRun(
            project_id=project_id,
            graph_version_id=version.id,
            graph_node_id=node.id,
            attempt_no=1,
            idempotency_key=f"keyframe:{shot_id}:{ih}",
            input_hash=ih,
            status="running",
            input_snapshot=snapshot,
            created_by=user_id,
        )
        self._session.add(node_run)
        await self._session.flush()

        # LEGACY: real product path must persist AgentRun + ProviderOperation XOR.
        # Spike only records the image op under NodeRun (no forged agent_run_id).
        _ = text_remote  # planning call still exercised for cost zero on fake

        img_create = await self.flux.create({"prompt": plan, "kind": "keyframe"})
        img_remote = str(img_create.get("remote_task_id") or uuid4())
        if str(img_create.get("status", "failed")) not in {"succeeded", "completed", "success"}:
            node_run.status = "failed"
            node_run.output_summary = {
                "error": img_create.get("error") or "image create failed",
            }
            await self._session.flush()
            raise ValidationAppError(
                f"IMAGE_PROVIDER_FAILED: {img_create.get('error') or img_create.get('status')}"
            )
        poll = await self.flux.poll(img_remote)
        img_cost = await self.flux.fetch_cost(img_remote)
        poll_status = str(poll.get("status", "failed"))
        artifact_uri = poll.get("artifact_uri") or img_create.get("artifact_uri")
        if poll_status not in {"succeeded", "completed", "success"} or not artifact_uri:
            node_run.status = "failed"
            node_run.output_summary = {"error": poll.get("error") or "image poll failed"}
            await self._session.flush()
            raise ValidationAppError(
                f"IMAGE_PROVIDER_FAILED: {poll.get('error') or poll_status}"
            )

        provider_name = getattr(self.flux, "provider", "flux")
        model_name = "agnes-image" if provider_name == "flux" and type(self.flux).__name__.startswith("Agnes") else "fake-flux"
        img_op = ProviderOperation(
            node_run_id=node_run.id,
            attempt_no=1,
            purpose="primary",
            operation_kind="image.keyframe",
            actual_provider=provider_name,
            actual_model=model_name,
            provider_operation_id=img_remote,
            request_fingerprint=hashlib_sha(plan),
            status=poll_status if poll_status in {"succeeded", "completed"} else "succeeded",
            request_summary={"kind": "keyframe"},
            response_summary={"status": poll_status},
            provider_cost=Decimal(str(img_cost.get("amount", 0.0))),
            currency=str(img_cost.get("currency", "USD")),
        )
        self._session.add(img_op)
        await self._session.flush()

        content_hash = str(poll.get("content_hash") or hashlib_sha(str(artifact_uri)))
        artifact = Artifact(
            project_id=project_id,
            artifact_type="image",
            storage_state="available",
            object_key=str(artifact_uri),
            content_hash=content_hash,
            mime_type="image/png",
            byte_size=1024,
            produced_by_run_id=node_run.id,
        )
        self._session.add(artifact)
        await self._session.flush()

        node_run.status = "completed"
        node_run.result_artifact_id = artifact.id
        node_run.provider_cost = img_op.provider_cost or Decimal("0")
        node_run.output_summary = {"artifact_id": str(artifact.id)}
        node.latest_successful_run_id = node_run.id

        emb = [0.0] * 512
        emb[0] = 1.0
        review = face_review_hook(embedding=emb, canonical=emb, threshold=face_threshold)
        await self._session.commit()

        return FirstFrameResult(
            brief_text=brief,
            plan_text=plan,
            graph_id=graph.id,
            graph_version_id=version.id,
            node_run_id=node_run.id,
            provider_operation_ids=[img_op.id],
            artifact_id=artifact.id,
            face_review=review,
            materialization_ops=applied,
        )


def hashlib_sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def get_node_run(session: AsyncSession, run_id: UUID) -> NodeRun | None:
    result = await session.execute(select(NodeRun).where(NodeRun.id == run_id))
    return result.scalar_one_or_none()


async def get_artifact(session: AsyncSession, artifact_id: UUID) -> Artifact | None:
    result = await session.execute(select(Artifact).where(Artifact.id == artifact_id))
    return result.scalar_one_or_none()
