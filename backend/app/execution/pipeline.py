"""S2 local vertical: confirm plan → fake adapters → artifact + face review hook."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from app.providers.fake import FakeFluxAdapter, FakeOpenAIAdapter
from app.shared.errors import ValidationAppError


@dataclass
class ProviderOperationRecord:
    id: UUID
    provider: str
    purpose: str
    remote_task_id: str
    status: str
    cost_amount: float
    cost_currency: str


@dataclass
class ArtifactRecord:
    id: UUID
    object_key: str
    content_hash: str
    media_type: str
    provider_operation_id: UUID


@dataclass
class FaceReviewResult:
    status: str  # passed | blocked | needs_human
    score: float | None
    rule: str


@dataclass
class FirstFrameResult:
    brief_text: str
    plan_text: str
    provider_operations: list[ProviderOperationRecord] = field(default_factory=list)
    artifact: ArtifactRecord | None = None
    face_review: FaceReviewResult | None = None
    materialization_ops: list[str] = field(default_factory=list)


class MaterializationWhitelist:
    """materialization-p0-v1 command allowlist (S2 subset)."""

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
    """Configurable face gate for tests; does not claim S0-A FAR/FRR calibration."""
    if embedding is None or canonical is None:
        return FaceReviewResult(status="needs_human", score=None, rule="missing_embedding")
    if len(embedding) != 512 or len(canonical) != 512:
        return FaceReviewResult(status="blocked", score=None, rule="dim_mismatch")
    # Cosine on unit-ish vectors
    score = sum(a * b for a, b in zip(embedding, canonical, strict=True))
    if score >= threshold:
        return FaceReviewResult(status="passed", score=score, rule="threshold")
    return FaceReviewResult(status="blocked", score=score, rule="below_threshold")


class FirstFramePipeline:
    """Local S2 path using fake OpenAI + Flux; zero paid BYOK required."""

    def __init__(
        self,
        openai: FakeOpenAIAdapter | None = None,
        flux: FakeFluxAdapter | None = None,
    ) -> None:
        self.openai = openai or FakeOpenAIAdapter()
        self.flux = flux or FakeFluxAdapter()
        self.materializer = MaterializationWhitelist()

    async def run(
        self,
        *,
        idea: str,
        authorized_text: bool,
        authorized_image: bool,
        materialization_ops: list[str],
        face_threshold: float = 0.0,
    ) -> FirstFrameResult:
        if not authorized_text:
            raise ValidationAppError("TEXT_PROVIDER_AUTHORIZATION_REQUIRED")
        if not authorized_image:
            raise ValidationAppError("IMAGE_PROVIDER_AUTHORIZATION_REQUIRED")

        applied = self.materializer.apply(materialization_ops)
        ops: list[ProviderOperationRecord] = []

        text_create = await self.openai.create({"prompt": idea, "kind": "brief"})
        text_id = str(text_create["remote_task_id"])
        text_cost = await self.openai.fetch_cost(text_id)
        ops.append(
            ProviderOperationRecord(
                id=uuid4(),
                provider="openai",
                purpose="primary",
                remote_task_id=text_id,
                status="succeeded",
                cost_amount=float(text_cost.get("amount", 0.0)),
                cost_currency=str(text_cost.get("currency", "USD")),
            )
        )
        brief = f"BRIEF:{idea}"
        plan = f"PLAN:{idea}"

        img_create = await self.flux.create({"prompt": plan, "kind": "keyframe"})
        img_id = str(img_create["remote_task_id"])
        poll = await self.flux.poll(img_id)
        img_cost = await self.flux.fetch_cost(img_id)
        op_id = uuid4()
        ops.append(
            ProviderOperationRecord(
                id=op_id,
                provider="flux",
                purpose="primary",
                remote_task_id=img_id,
                status=str(poll.get("status", "failed")),
                cost_amount=float(img_cost.get("amount", 0.0)),
                cost_currency=str(img_cost.get("currency", "USD")),
            )
        )
        artifact = ArtifactRecord(
            id=uuid4(),
            object_key=str(poll.get("artifact_uri", "")),
            content_hash=str(poll.get("content_hash", "")),
            media_type="image/png",
            provider_operation_id=op_id,
        )
        # Synthetic unit embedding for gate wiring (not S0-A evidence)
        emb = [0.0] * 512
        emb[0] = 1.0
        review = face_review_hook(embedding=emb, canonical=emb, threshold=face_threshold)
        return FirstFrameResult(
            brief_text=brief,
            plan_text=plan,
            provider_operations=ops,
            artifact=artifact,
            face_review=review,
            materialization_ops=applied,
        )
