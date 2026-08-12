"""Materialize confirmed Director plans into immutable production batches."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.access.projects import ProjectService
from app.assets.models import Episode, Scene, Shot
from app.director.enums import ApprovalKind, ArtifactKind, WorkflowStatus
from app.director.models import (
    ApprovalRecord,
    BudgetAuthorization,
    BudgetReservation,
    CreativeArtifactVersion,
    ProductionBatch,
    ProductionBatchShot,
    WorkflowStepRun,
)
from app.director.production_templates import (
    DIALOGUE_POST_DUB_SHOT_V1,
    QUALITY_POLICY_V1,
    dialogue_post_dub_definition,
)
from app.director.service import DirectorService, content_hash
from app.director.shooting import (
    CharacterBiblePayload,
    CostEstimatePayload,
    SelectionPlanPayload,
    StoryboardPlanPayload,
    TrialPlanPayload,
    TrialReviewPayload,
    VisualBiblePayload,
    VoiceBiblePayload,
)
from app.events.service import EventService
from app.execution.models import Artifact, NodeRun
from app.production.models import GraphVersion, ProductionGraph, definition_hash
from app.production.service import GraphService
from app.shared.enums import GraphStatus
from app.shared.errors import ConflictError, ValidationAppError

if TYPE_CHECKING:
    from app.delivery.export_service import ExportResult
    from app.storage.minio_store import ObjectStore

_MEDIA_NODE_KEYS = frozenset({"character_reference", "keyframe", "video", "voice"})


class DirectorProductionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._director = DirectorService(session)
        self._projects = ProjectService(session)
        self._graphs = GraphService(session)
        self._events = EventService(session)

    async def materialize_trial(
        self,
        *,
        project_id: UUID,
        actor: User,
        idempotency_key: str,
    ) -> tuple[ProductionBatch, list[NodeRun]]:
        project = await self._projects.get_project_for_owner(project_id=project_id, actor=actor)
        workflow = await self._director.get_workflow(project_id=project_id, actor=actor)
        existing = await self._batch_by_key(project_id, idempotency_key)
        if existing is not None:
            return existing, await self._batch_runs(existing.id)
        if workflow.status != WorkflowStatus.TRIAL_RUNNING.value:
            raise ValidationAppError(
                "trial can only be materialized after explicit budget approval",
                details={"code": "TRIAL_AUTHORIZATION_REQUIRED"},
            )
        approval, authorization = await self._active_budget_approval(
            project_id=project_id,
            workflow_id=workflow.id,
            approval_kind=ApprovalKind.TRIAL_BUDGET,
        )
        artifacts = await self._locked_inputs(approval.approved_artifact_versions)
        storyboard = StoryboardPlanPayload.model_validate(
            artifacts[ArtifactKind.STORYBOARD_PLAN].payload
        )
        character = CharacterBiblePayload.model_validate(
            artifacts[ArtifactKind.CHARACTER_BIBLE].payload
        )
        visual = VisualBiblePayload.model_validate(artifacts[ArtifactKind.VISUAL_BIBLE].payload)
        voice = VoiceBiblePayload.model_validate(artifacts[ArtifactKind.VOICE_BIBLE].payload)
        selection = SelectionPlanPayload.model_validate(
            artifacts[ArtifactKind.SELECTION_PLAN].payload
        )
        cost = CostEstimatePayload.model_validate(artifacts[ArtifactKind.COST_ESTIMATE].payload)
        trial = TrialPlanPayload.model_validate(artifacts[ArtifactKind.TRIAL_PLAN].payload)
        self._assert_media_preflight(selection=selection, cost=cost, stage="trial")
        shot = next(
            (item for item in storyboard.shots if item.shot_id == trial.representative_shot_id),
            None,
        )
        if shot is None:
            raise ConflictError("trial plan representative shot is absent from storyboard")
        estimated_trial = cost.trial_total
        if estimated_trial is None or estimated_trial > authorization.limit_amount:
            raise ValidationAppError(
                "trial estimate exceeds the authorized budget limit",
                details={
                    "code": "TRIAL_BUDGET_LIMIT_INSUFFICIENT",
                    "estimated_amount": (
                        str(estimated_trial) if estimated_trial is not None else None
                    ),
                    "authorized_limit": str(authorization.limit_amount),
                    "currency": authorization.currency,
                },
            )

        locked_refs = {
            kind.value: str(row.id)
            for kind, row in artifacts.items()
            if kind in {
                ArtifactKind.CHARACTER_BIBLE,
                ArtifactKind.VISUAL_BIBLE,
                ArtifactKind.VOICE_BIBLE,
                ArtifactKind.STORYBOARD_PLAN,
                ArtifactKind.RISK_REPORT,
                ArtifactKind.SELECTION_PLAN,
                ArtifactKind.COST_ESTIMATE,
                ArtifactKind.TRIAL_PLAN,
            }
        }
        selection_snapshot = selection.model_dump(mode="json")
        batch_hash = content_hash(
            {
                "kind": "trial",
                "versions": locked_refs,
                "selected_shots": [shot.shot_id],
                "selection": selection_snapshot,
                "budget_authorization_id": str(authorization.id),
                "quality_policy_id": QUALITY_POLICY_V1,
            }
        )
        batch = ProductionBatch(
            project_id=project.id,
            workflow_run_id=workflow.id,
            batch_kind="trial",
            idempotency_key=idempotency_key,
            status="materializing",
            budget_authorization_id=authorization.id,
            locked_version_refs=locked_refs,
            selected_shot_ids=[shot.shot_id],
            template_keys=[DIALOGUE_POST_DUB_SHOT_V1],
            quality_policy_id=QUALITY_POLICY_V1,
            selection_snapshot=selection_snapshot,
            semantic_hash=batch_hash,
            created_by=actor.id,
        )
        self._session.add(batch)
        await self._session.flush()
        reservation = BudgetReservation(
            project_id=project.id,
            batch_id=batch.id,
            authorization_id=authorization.id,
            idempotency_key=f"{idempotency_key}:budget",
            reserved_amount=(
                estimated_trial if estimated_trial > 0 else authorization.limit_amount
            ),
            currency=authorization.currency,
            status="reserved",
        )
        self._session.add(reservation)
        await self._session.flush()
        shot_row = await self._project_storyboard_shot(
            project=project,
            storyboard=storyboard,
            logical_shot_id=shot.shot_id,
        )
        batch_shot = ProductionBatchShot(
            project_id=project.id,
            batch_id=batch.id,
            logical_shot_id=shot.shot_id,
            shot_id=shot_row.id,
            status="materializing",
            semantic_hash=self._shot_semantic_hash(
                shot=shot.model_dump(mode="json"),
                locked_refs=locked_refs,
                selection_snapshot=selection_snapshot,
            ),
        )
        self._session.add(batch_shot)
        await self._session.flush()
        runs = await self._materialize_shot_graph(
            project=project,
            actor=actor,
            batch=batch,
            reservation=reservation,
            batch_shot=batch_shot,
            storyboard=storyboard,
            shot=shot,
            character=character,
            visual=visual,
            voice=voice,
            selection=selection,
        )
        batch.status = "running"
        batch.started_at = datetime.now(UTC)
        batch_shot.status = "queued"
        package_run = WorkflowStepRun(
            project_id=project.id,
            workflow_run_id=workflow.id,
            step_key="materialize_trial",
            skill_id="production_preflight",
            skill_version="1.0.0",
            execution_kind="domain_service",
            idempotency_key=f"{idempotency_key}:materialize",
            status="succeeded",
            input_version_refs=list(locked_refs.values()),
            output_version_refs=[],
            service_run_ref=f"production-batch:{batch.id}",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        self._session.add(package_run)
        for run in runs:
            await self._events.append_with_outbox(
                project_id=project.id,
                aggregate_type="production_batch",
                aggregate_id=batch.id,
                event_type="director.node_run.queued",
                topic="node_run.enqueue",
                payload={
                    "node_run_id": str(run.id),
                    "production_batch_id": str(batch.id),
                    "logical_shot_id": shot.shot_id,
                },
                actor_id=actor.id,
            )
        await self._session.commit()
        await self._session.refresh(batch)
        _ = approval
        return batch, runs

    async def materialize_production(
        self,
        *,
        project_id: UUID,
        actor: User,
        idempotency_key: str,
    ) -> tuple[ProductionBatch, list[NodeRun]]:
        """Freeze and materialize the accepted 3-6 shot production plan.

        The production approval is the authorization boundary.  Its exact
        artifact-version snapshot, model selection and budget authorization are
        persisted into the batch before any NodeRun can be queued.
        """
        project = await self._projects.get_project_for_owner(project_id=project_id, actor=actor)
        workflow = await self._director.get_workflow(project_id=project_id, actor=actor)
        existing = await self._batch_by_key(project_id, idempotency_key)
        if existing is not None:
            if existing.batch_kind != "production":
                raise ConflictError("idempotency key belongs to another batch kind")
            return existing, await self._batch_runs(existing.id)
        if workflow.status != WorkflowStatus.PRODUCTION_RUNNING.value:
            raise ValidationAppError(
                "production can only be materialized after explicit budget approval",
                details={"code": "PRODUCTION_AUTHORIZATION_REQUIRED"},
            )
        approval, authorization = await self._active_budget_approval(
            project_id=project_id,
            workflow_id=workflow.id,
            approval_kind=ApprovalKind.PRODUCTION_BUDGET,
        )
        artifacts = await self._locked_inputs(approval.approved_artifact_versions)
        storyboard = StoryboardPlanPayload.model_validate(
            artifacts[ArtifactKind.STORYBOARD_PLAN].payload
        )
        character = CharacterBiblePayload.model_validate(
            artifacts[ArtifactKind.CHARACTER_BIBLE].payload
        )
        visual = VisualBiblePayload.model_validate(artifacts[ArtifactKind.VISUAL_BIBLE].payload)
        voice = VoiceBiblePayload.model_validate(artifacts[ArtifactKind.VOICE_BIBLE].payload)
        selection = SelectionPlanPayload.model_validate(
            artifacts[ArtifactKind.SELECTION_PLAN].payload
        )
        cost = CostEstimatePayload.model_validate(artifacts[ArtifactKind.COST_ESTIMATE].payload)
        trial_plan = TrialPlanPayload.model_validate(artifacts[ArtifactKind.TRIAL_PLAN].payload)
        self._assert_media_preflight(selection=selection, cost=cost, stage="production")
        estimated_production = cost.production_total
        if (
            estimated_production is None
            or estimated_production > authorization.limit_amount
        ):
            raise ValidationAppError(
                "production estimate exceeds the authorized budget limit",
                details={
                    "code": "PRODUCTION_BUDGET_LIMIT_INSUFFICIENT",
                    "estimated_amount": (
                        str(estimated_production)
                        if estimated_production is not None
                        else None
                    ),
                    "authorized_limit": str(authorization.limit_amount),
                    "currency": authorization.currency,
                },
            )
        raw_trial_review_id = approval.approved_artifact_versions.get(
            ArtifactKind.TRIAL_REVIEW.value
        )
        if raw_trial_review_id is None:
            raise ValidationAppError(
                "an accepted representative trial is required",
                details={"code": "ACCEPTED_TRIAL_REQUIRED"},
            )
        trial_review_row = await self._session.get(
            CreativeArtifactVersion, UUID(raw_trial_review_id)
        )
        if (
            trial_review_row is None
            or trial_review_row.project_id != project.id
            or trial_review_row.workflow_run_id != workflow.id
        ):
            raise ConflictError("approved trial review evidence is missing")
        trial_review = TrialReviewPayload.model_validate(trial_review_row.payload)
        if trial_review.decision != "accept" or not trial_review.accepted_quality:
            raise ValidationAppError(
                "the representative trial was not accepted",
                details={"code": "ACCEPTED_TRIAL_REQUIRED"},
            )

        locked_refs = {
            kind.value: str(row.id)
            for kind, row in artifacts.items()
            if kind
            in {
                ArtifactKind.CHARACTER_BIBLE,
                ArtifactKind.VISUAL_BIBLE,
                ArtifactKind.VOICE_BIBLE,
                ArtifactKind.STORYBOARD_PLAN,
                ArtifactKind.RISK_REPORT,
                ArtifactKind.SELECTION_PLAN,
                ArtifactKind.COST_ESTIMATE,
                ArtifactKind.TRIAL_PLAN,
            }
        }
        locked_refs[ArtifactKind.TRIAL_REVIEW.value] = str(trial_review_row.id)
        selection_snapshot = selection.model_dump(mode="json")
        logical_shot_ids = [shot.shot_id for shot in storyboard.shots]
        batch_hash = content_hash(
            {
                "kind": "production",
                "versions": locked_refs,
                "selected_shots": logical_shot_ids,
                "selection": selection_snapshot,
                "budget_authorization_id": str(authorization.id),
                "quality_policy_id": QUALITY_POLICY_V1,
            }
        )
        batch = ProductionBatch(
            project_id=project.id,
            workflow_run_id=workflow.id,
            batch_kind="production",
            idempotency_key=idempotency_key,
            status="materializing",
            budget_authorization_id=authorization.id,
            locked_version_refs=locked_refs,
            selected_shot_ids=logical_shot_ids,
            template_keys=[DIALOGUE_POST_DUB_SHOT_V1],
            quality_policy_id=QUALITY_POLICY_V1,
            selection_snapshot=selection_snapshot,
            semantic_hash=batch_hash,
            created_by=actor.id,
        )
        self._session.add(batch)
        await self._session.flush()
        reservation = BudgetReservation(
            project_id=project.id,
            batch_id=batch.id,
            authorization_id=authorization.id,
            idempotency_key=f"{idempotency_key}:budget",
            reserved_amount=(
                estimated_production
                if estimated_production > 0
                else authorization.limit_amount
            ),
            currency=authorization.currency,
            status="reserved",
        )
        self._session.add(reservation)
        await self._session.flush()

        reusable_trial = await self._accepted_trial_shot(
            project_id=project.id,
            workflow_id=workflow.id,
            batch_id=trial_review.batch_id,
            logical_shot_id=trial_plan.representative_shot_id,
        )
        runs: list[NodeRun] = []
        for shot in storyboard.shots:
            shot_row = await self._project_storyboard_shot(
                project=project,
                storyboard=storyboard,
                logical_shot_id=shot.shot_id,
            )
            semantic = self._shot_semantic_hash(
                shot=shot.model_dump(mode="json"),
                locked_refs=locked_refs,
                selection_snapshot=selection_snapshot,
            )
            reuse = (
                reusable_trial
                if reusable_trial is not None
                and shot.shot_id == trial_plan.representative_shot_id
                and reusable_trial.semantic_hash == semantic
                else None
            )
            batch_shot = ProductionBatchShot(
                project_id=project.id,
                batch_id=batch.id,
                logical_shot_id=shot.shot_id,
                shot_id=shot_row.id,
                status="accepted" if reuse is not None else "materializing",
                semantic_hash=semantic,
                accepted_artifact_id=(
                    reuse.accepted_artifact_id if reuse is not None else None
                ),
                accepted_node_run_id=(
                    reuse.accepted_node_run_id if reuse is not None else None
                ),
            )
            self._session.add(batch_shot)
            await self._session.flush()
            if reuse is None:
                shot_runs = await self._materialize_shot_graph(
                    project=project,
                    actor=actor,
                    batch=batch,
                    reservation=reservation,
                    batch_shot=batch_shot,
                    storyboard=storyboard,
                    shot=shot,
                    character=character,
                    visual=visual,
                    voice=voice,
                    selection=selection,
                )
                batch_shot.status = "queued"
                runs.extend(shot_runs)

        batch.status = "running"
        batch.started_at = datetime.now(UTC)
        self._session.add(
            WorkflowStepRun(
                project_id=project.id,
                workflow_run_id=workflow.id,
                step_key="materialize_production",
                skill_id="production_preflight",
                skill_version="1.0.0",
                execution_kind="domain_service",
                idempotency_key=f"{idempotency_key}:materialize",
                status="succeeded",
                input_version_refs=list(locked_refs.values()),
                output_version_refs=[],
                service_run_ref=f"production-batch:{batch.id}",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
        )
        for run in runs:
            await self._events.append_with_outbox(
                project_id=project.id,
                aggregate_type="production_batch",
                aggregate_id=batch.id,
                event_type="director.node_run.queued",
                topic="node_run.enqueue",
                payload={
                    "node_run_id": str(run.id),
                    "production_batch_id": str(batch.id),
                    "logical_shot_id": str(
                        (run.input_snapshot or {}).get("logical_shot_id") or ""
                    ),
                },
                actor_id=actor.id,
            )
        await self._session.commit()
        await self._session.refresh(batch)
        return batch, runs

    async def export_production(
        self,
        *,
        project_id: UUID,
        batch_id: UUID,
        actor: User,
        store: ObjectStore | None = None,
        try_ffmpeg: bool = True,
    ) -> ExportResult:
        """Export only explicitly accepted composites in locked storyboard order."""
        from app.delivery.export_service import build_project_export
        await self._projects.get_project_for_owner(project_id=project_id, actor=actor)
        workflow = await self._director.get_workflow(project_id=project_id, actor=actor)
        if workflow.status != WorkflowStatus.ASSEMBLING.value:
            raise ValidationAppError(
                "production must be fully accepted before export",
                details={"code": "PRODUCTION_EXPORT_NOT_READY"},
            )
        batch = await self._session.get(ProductionBatch, batch_id)
        if (
            batch is None
            or batch.project_id != project_id
            or batch.workflow_run_id != workflow.id
            or batch.batch_kind != "production"
            or batch.status != "accepted"
        ):
            raise ValidationAppError("accepted production batch not found")
        storyboard_ref = batch.locked_version_refs.get(ArtifactKind.STORYBOARD_PLAN.value)
        if storyboard_ref is None:
            raise ConflictError("production batch lacks a locked storyboard reference")
        storyboard_row = await self._session.get(
            CreativeArtifactVersion, UUID(storyboard_ref)
        )
        if storyboard_row is None or storyboard_row.project_id != project_id:
            raise ConflictError("production batch locked storyboard is missing")
        storyboard = StoryboardPlanPayload.model_validate(storyboard_row.payload)
        batch_shots = list(
            (
                await self._session.execute(
                    select(ProductionBatchShot).where(
                        ProductionBatchShot.batch_id == batch.id
                    )
                )
            ).scalars()
        )
        shot_by_logical_id = {row.logical_shot_id: row for row in batch_shots}
        expected_ids = [shot.shot_id for shot in storyboard.shots]
        if set(shot_by_logical_id) != set(expected_ids):
            raise ConflictError("production batch shots differ from the locked storyboard")
        artifact_ids: list[UUID] = []
        run_ids: list[UUID] = []
        subtitles: list[tuple[str, str]] = []
        for shot in storyboard.shots:
            batch_shot = shot_by_logical_id[shot.shot_id]
            if (
                batch_shot.status != "accepted"
                or batch_shot.accepted_artifact_id is None
                or batch_shot.accepted_node_run_id is None
            ):
                raise ValidationAppError(
                    "every production shot requires explicit creator acceptance",
                    details={
                        "code": "PRODUCTION_REVIEW_INCOMPLETE",
                        "logical_shot_id": shot.shot_id,
                    },
                )
            run, artifact = await self._accepted_composite_lineage(
                project_id=project_id,
                workflow_id=workflow.id,
                production_batch=batch,
                batch_shot=batch_shot,
            )
            run_ids.append(run.id)
            artifact_ids.append(artifact.id)
            subtitles.append(
                (
                    shot.shot_id,
                    "\n".join(
                        f"{line.speaker}: {line.text}" for line in shot.dialogue
                    )
                    or " ",
                )
            )
        result = await build_project_export(
            self._session,
            project_id=project_id,
            requested_by=actor.id,
            shot_subtitles=subtitles,
            store=store,
            try_ffmpeg=try_ffmpeg,
            require_approved=False,
            exact_artifact_ids=artifact_ids,
            exact_node_run_ids=run_ids,
        )
        if result.export_status != "completed":
            raise ConflictError(
                "exact production export failed",
                details={
                    "code": "PRODUCTION_EXPORT_FAILED",
                    "export_id": str(result.export_id),
                    "mp4_error": result.mp4_error,
                },
            )
        from app.delivery.models import Export

        export_row = await self._session.get(Export, result.export_id)
        if export_row is None:
            raise ConflictError("completed production export record is missing")
        export_row.manifest = {
            **dict(export_row.manifest or {}),
            "production_batch_id": str(batch.id),
            "workflow_run_id": str(workflow.id),
        }
        batch.status = "completed"
        batch.finished_at = datetime.now(UTC)
        workflow.status = WorkflowStatus.COMPLETED.value
        workflow.current_stage = "production"
        workflow.version += 1
        await self._session.commit()
        return result

    async def _accepted_composite_lineage(
        self,
        *,
        project_id: UUID,
        workflow_id: UUID,
        production_batch: ProductionBatch,
        batch_shot: ProductionBatchShot,
    ) -> tuple[NodeRun, Artifact]:
        assert batch_shot.accepted_node_run_id is not None
        assert batch_shot.accepted_artifact_id is not None
        run = await self._session.get(NodeRun, batch_shot.accepted_node_run_id)
        artifact = await self._session.get(Artifact, batch_shot.accepted_artifact_id)
        if (
            run is None
            or run.project_id != project_id
            or run.status not in {"completed", "cached", "completed_after_cancel"}
            or run.result_artifact_id != batch_shot.accepted_artifact_id
            or str((run.input_snapshot or {}).get("node_key") or "") != "composite"
            or artifact is None
            or artifact.project_id != project_id
            or artifact.storage_state != "available"
            or artifact.deleted_at is not None
            or artifact.produced_by_run_id != run.id
            or not artifact.mime_type.startswith("video/")
        ):
            raise ConflictError("accepted composite lineage is incomplete or invalid")
        if run.production_batch_id == production_batch.id:
            return run, artifact
        source_batch = await self._session.get(ProductionBatch, run.production_batch_id)
        source_shot = await self._session.scalar(
            select(ProductionBatchShot).where(
                ProductionBatchShot.batch_id == run.production_batch_id,
                ProductionBatchShot.logical_shot_id == batch_shot.logical_shot_id,
                ProductionBatchShot.semantic_hash == batch_shot.semantic_hash,
                ProductionBatchShot.status == "accepted",
                ProductionBatchShot.accepted_node_run_id == run.id,
                ProductionBatchShot.accepted_artifact_id == artifact.id,
            )
        )
        if (
            source_batch is None
            or source_batch.project_id != project_id
            or source_batch.workflow_run_id != workflow_id
            or source_batch.batch_kind not in {"trial", "repair"}
            or source_batch.status != "accepted"
            or source_shot is None
        ):
            raise ConflictError("reused composite lineage is not accepted")
        if source_batch.batch_kind == "repair" and str(
            (source_batch.selection_snapshot or {}).get("root_source_batch_id") or ""
        ) != str(production_batch.id):
            raise ConflictError("accepted repair does not belong to this production batch")
        return run, artifact

    async def _materialize_shot_graph(
        self,
        *,
        project: Project,
        actor: User,
        batch: ProductionBatch,
        reservation: BudgetReservation,
        batch_shot: ProductionBatchShot,
        storyboard: StoryboardPlanPayload,
        shot: object,
        character: CharacterBiblePayload,
        visual: VisualBiblePayload,
        voice: VoiceBiblePayload,
        selection: SelectionPlanPayload,
    ) -> list[NodeRun]:
        from app.director.shooting import StoryboardShot

        if not isinstance(shot, StoryboardShot):
            raise TypeError("shot must be a StoryboardShot")
        character_by_name = {item.name: item for item in character.characters}
        voice_by_name = {item.character_name: item for item in voice.voices}
        unknown = [name for name in shot.characters if name not in character_by_name]
        if unknown:
            raise ConflictError("storyboard character anchors are incomplete")
        primary = character_by_name[shot.characters[0]]
        trial_character_names = set(shot.characters)
        ref_keys = [
            f"character_{item.character_id}"
            for item in character.characters
            if item.name in trial_character_names
        ]
        primary_ref_key = f"character_{primary.character_id}"
        definition = dialogue_post_dub_definition(
            character_reference_keys=ref_keys,
            primary_character_reference_key=primary_ref_key,
            context={
                "workflow_run_id": str(batch.workflow_run_id),
                "production_batch_id": str(batch.id),
                "logical_shot_id": shot.shot_id,
            },
        )
        _graph, graph_version = await self._create_shot_graph_version(
            project_id=project.id,
            shot_id=cast(UUID, batch_shot.shot_id),
            created_by=actor.id,
            definition=definition,
        )
        materialized = await self._graphs.materialize_definition(
            version_id=graph_version.id
        )
        await self._graphs.publish(version_id=graph_version.id, published_by=actor.id)
        batch_shot.graph_version_id = graph_version.id
        plans = {item.purpose: item.model_dump(mode="json") for item in selection.plans}
        reference_runs: dict[str, NodeRun] = {}
        runs: list[NodeRun] = []
        for item in character.characters:
            if item.name not in trial_character_names:
                continue
            key = f"character_{item.character_id}"
            prompt = self._reference_prompt(item.locked_prompt, visual)
            reference_runs[key] = self._new_run(
                project=project,
                actor=actor,
                batch=batch,
                reservation=reservation,
                batch_shot=batch_shot,
                graph_version_id=graph_version.id,
                graph_node_id=materialized.nodes[key].id,
                node_key=key,
                purpose="character_reference",
                prompt=prompt,
                shot=shot,
                storyboard=storyboard,
                selection_plan=plans["character_reference"],
                lead_identity_required=False,
            )
            self._session.add(reference_runs[key])
            runs.append(reference_runs[key])
        await self._session.flush()
        dialogue_text = "\n".join(f"{line.speaker}: {line.text}" for line in shot.dialogue)
        prompt_by_key = {
            "prompt": shot.image_prompt,
            "keyframe": shot.image_prompt,
            "face_review": shot.image_prompt,
            "video": shot.video_prompt,
            "video_drift_review": shot.video_prompt,
            "voice": dialogue_text or "无对白环境声",
            "subtitle": dialogue_text,
            "composite": shot.video_prompt,
            "continuity_review": shot.video_prompt,
        }
        purpose_by_key = {
            "keyframe": "keyframe",
            "video": "video",
            "voice": "voice",
        }
        for key in (
            "prompt",
            "keyframe",
            "face_review",
            "video",
            "video_drift_review",
            "voice",
            "subtitle",
            "composite",
            "continuity_review",
        ):
            purpose = purpose_by_key.get(key)
            run = self._new_run(
                project=project,
                actor=actor,
                batch=batch,
                reservation=reservation,
                batch_shot=batch_shot,
                graph_version_id=graph_version.id,
                graph_node_id=materialized.nodes[key].id,
                node_key=key,
                purpose=purpose,
                prompt=prompt_by_key[key],
                shot=shot,
                storyboard=storyboard,
                selection_plan=(
                    plans[
                        cast(
                            Literal["character_reference", "keyframe", "video", "voice"],
                            purpose,
                        )
                    ]
                    if purpose
                    else None
                ),
                lead_identity_required=key in {"keyframe", "face_review", "video_drift_review"},
                canonical_source_run_id=(
                    reference_runs[primary_ref_key].id
                    if key in {"keyframe", "face_review", "video_drift_review"}
                    else None
                ),
                voice_design=(
                    [
                        voice_by_name[line.speaker].model_dump(mode="json")
                        for line in shot.dialogue
                        if line.speaker in voice_by_name
                    ]
                    if key == "voice"
                    else None
                ),
            )
            self._session.add(run)
            runs.append(run)
        await self._session.flush()
        return runs

    def _new_run(
        self,
        *,
        project: Project,
        actor: User,
        batch: ProductionBatch,
        reservation: BudgetReservation,
        batch_shot: ProductionBatchShot,
        graph_version_id: UUID,
        graph_node_id: UUID,
        node_key: str,
        purpose: str | None,
        prompt: str,
        shot: object,
        storyboard: StoryboardPlanPayload,
        selection_plan: dict[str, object] | None,
        lead_identity_required: bool,
        canonical_source_run_id: UUID | None = None,
        voice_design: list[dict[str, object]] | None = None,
    ) -> NodeRun:
        from app.director.shooting import StoryboardShot

        if not isinstance(shot, StoryboardShot):
            raise TypeError("shot must be a StoryboardShot")
        snapshot: dict[str, object] = {
            "workflow_run_id": str(batch.workflow_run_id),
            "production_batch_id": str(batch.id),
            "budget_reservation_id": str(reservation.id),
            "logical_shot_id": shot.shot_id,
            "shot_id": str(batch_shot.shot_id),
            "node_key": node_key,
            "purpose": purpose,
            "prompt": prompt,
            "plan": {
                "prompt": prompt,
                "shot": shot.model_dump(mode="json"),
            },
            "dialogue": "\n".join(line.text for line in shot.dialogue),
            "subtitle": "\n".join(line.text for line in shot.dialogue),
            "aspect_ratio": storyboard.aspect_ratio,
            "duration_seconds": str(shot.duration_seconds),
            "lead_identity_required": lead_identity_required,
            "quality_policy_id": batch.quality_policy_id,
            "locked_version_refs": dict(batch.locked_version_refs),
        }
        if selection_plan is not None:
            snapshot["selection_plan"] = selection_plan
            snapshot["model_binding_id"] = selection_plan.get("model_binding_id")
            snapshot["capability_manifest_hash"] = selection_plan.get("manifest_hash")
        if canonical_source_run_id is not None:
            snapshot["canonical_source_run_id"] = str(canonical_source_run_id)
        if voice_design is not None:
            snapshot["voice_design"] = voice_design
        semantic = content_hash(
            {
                "batch": batch.semantic_hash,
                "node": node_key,
                "snapshot": snapshot,
            }
        )
        return NodeRun(
            project_id=project.id,
            graph_version_id=graph_version_id,
            graph_node_id=graph_node_id,
            production_batch_id=batch.id,
            budget_reservation_id=reservation.id,
            attempt_no=1,
            idempotency_key=f"director:{batch.id}:{shot.shot_id}:{node_key}:{semantic[:16]}",
            input_hash=semantic,
            status="queued",
            input_snapshot=snapshot,
            created_by=actor.id,
        )

    async def _project_storyboard_shot(
        self,
        *,
        project: Project,
        storyboard: StoryboardPlanPayload,
        logical_shot_id: str,
    ) -> Shot:
        episode = await self._session.scalar(
            select(Episode).where(Episode.project_id == project.id, Episode.episode_number == 1)
        )
        if episode is None:
            episode = Episode(
                project_id=project.id,
                episode_number=1,
                title=project.name,
                synopsis="Director-confirmed 15–30 second short drama",
            )
            self._session.add(episode)
            await self._session.flush()
        scene = await self._session.scalar(
            select(Scene).where(Scene.episode_id == episode.id, Scene.scene_number == 1)
        )
        first = storyboard.shots[0]
        if scene is None:
            scene = Scene(
                episode_id=episode.id,
                scene_number=1,
                location_name=first.location,
                time_of_day=first.time_of_day,
                synopsis="Director-confirmed storyboard projection",
            )
            self._session.add(scene)
            await self._session.flush()
        plan = next(item for item in storyboard.shots if item.shot_id == logical_shot_id)
        shot = await self._session.scalar(
            select(Shot).where(Shot.scene_id == scene.id, Shot.shot_number == plan.shot_number)
        )
        if shot is not None:
            if shot.visual_description != plan.action or shot.dialogue != "\n".join(
                item.text for item in plan.dialogue
            ):
                raise ConflictError(
                    "an existing shot projection conflicts with the locked storyboard",
                    details={"code": "DIRECTOR_SHOT_PROJECTION_CONFLICT"},
                )
            return shot
        shot = Shot(
            project_id=project.id,
            scene_id=scene.id,
            shot_number=plan.shot_number,
            shot_type=plan.shot_type,
            camera_move=plan.camera_move,
            visual_description=plan.action,
            dialogue="\n".join(item.text for item in plan.dialogue),
            duration_seconds=plan.duration_seconds,
            status="in_production",
            sort_order=plan.shot_number,
        )
        self._session.add(shot)
        await self._session.flush()
        return shot

    async def _locked_inputs(
        self, current: dict[str, str]
    ) -> dict[ArtifactKind, CreativeArtifactVersion]:
        required = {
            ArtifactKind.CHARACTER_BIBLE,
            ArtifactKind.VISUAL_BIBLE,
            ArtifactKind.VOICE_BIBLE,
            ArtifactKind.STORYBOARD_PLAN,
            ArtifactKind.RISK_REPORT,
            ArtifactKind.SELECTION_PLAN,
            ArtifactKind.COST_ESTIMATE,
            ArtifactKind.TRIAL_PLAN,
        }
        output: dict[ArtifactKind, CreativeArtifactVersion] = {}
        for kind in required:
            raw = current.get(kind.value)
            if raw is None:
                raise ValidationAppError(
                    "confirmed production input is missing",
                    details={"code": "PRODUCTION_INPUT_MISSING", "artifact_kind": kind.value},
                )
            row = await self._session.get(CreativeArtifactVersion, UUID(raw))
            if row is None or row.status != "locked":
                raise ValidationAppError(
                    "production input must be locked",
                    details={"code": "PRODUCTION_INPUT_NOT_LOCKED", "artifact_kind": kind.value},
                )
            output[kind] = row
        return output

    async def _accepted_trial_shot(
        self,
        *,
        project_id: UUID,
        workflow_id: UUID,
        batch_id: UUID,
        logical_shot_id: str,
    ) -> ProductionBatchShot | None:
        batch = await self._session.get(ProductionBatch, batch_id)
        if (
            batch is None
            or batch.project_id != project_id
            or batch.workflow_run_id != workflow_id
            or batch.batch_kind != "trial"
            or batch.status != "accepted"
        ):
            return None
        batch_shot = await self._session.scalar(
            select(ProductionBatchShot).where(
                ProductionBatchShot.batch_id == batch.id,
                ProductionBatchShot.logical_shot_id == logical_shot_id,
            )
        )
        if (
            batch_shot is None
            or batch_shot.status != "accepted"
            or batch_shot.accepted_artifact_id is None
            or batch_shot.accepted_node_run_id is None
        ):
            return None
        run = await self._session.get(NodeRun, batch_shot.accepted_node_run_id)
        artifact = await self._session.get(Artifact, batch_shot.accepted_artifact_id)
        if (
            run is None
            or run.project_id != project_id
            or run.production_batch_id != batch.id
            or run.result_artifact_id != batch_shot.accepted_artifact_id
            or run.status not in {"completed", "cached", "completed_after_cancel"}
            or artifact is None
            or artifact.project_id != project_id
            or artifact.storage_state != "available"
            or artifact.deleted_at is not None
            or artifact.produced_by_run_id != run.id
            or not artifact.mime_type.startswith("video/")
        ):
            return None
        return batch_shot

    async def _create_shot_graph_version(
        self,
        *,
        project_id: UUID,
        shot_id: UUID,
        created_by: UUID,
        definition: dict[str, object],
    ) -> tuple[ProductionGraph, GraphVersion]:
        """Create an immutable version when this projected Shot already has a graph."""
        graph = await self._session.scalar(
            select(ProductionGraph).where(
                ProductionGraph.project_id == project_id,
                ProductionGraph.scope_type == "shot",
                ProductionGraph.scope_entity_id == shot_id,
            )
        )
        if graph is None:
            graph = await self._graphs.create_graph(
                project_id=project_id,
                scope_type="shot",
                scope_entity_id=shot_id,
                template_key=DIALOGUE_POST_DUB_SHOT_V1,
                created_by=created_by,
                definition=definition,
            )
            assert graph.current_version_id is not None
            return graph, await self._graphs.get_version(graph.current_version_id)
        digest = definition_hash(definition)
        duplicate = await self._session.scalar(
            select(GraphVersion).where(
                GraphVersion.graph_id == graph.id,
                GraphVersion.definition_hash == digest,
            )
        )
        if duplicate is not None:
            if duplicate.status != GraphStatus.DRAFT.value:
                raise ConflictError(
                    "the exact shot graph version was already published",
                    details={"code": "SHOT_GRAPH_VERSION_ALREADY_PUBLISHED"},
                )
            return graph, duplicate
        latest = await self._session.scalar(
            select(func.max(GraphVersion.version_number)).where(
                GraphVersion.graph_id == graph.id
            )
        )
        version = GraphVersion(
            graph_id=graph.id,
            version_number=int(latest or 0) + 1,
            status=GraphStatus.DRAFT.value,
            definition_hash=digest,
            definition=definition,
        )
        self._session.add(version)
        await self._session.flush()
        graph.current_version_id = version.id
        graph.status = GraphStatus.DRAFT.value
        graph.version += 1
        await self._session.flush()
        return graph, version

    @staticmethod
    def _shot_semantic_hash(
        *,
        shot: dict[str, object],
        locked_refs: dict[str, str],
        selection_snapshot: dict[str, object],
    ) -> str:
        creative_keys = {
            ArtifactKind.CHARACTER_BIBLE.value,
            ArtifactKind.VISUAL_BIBLE.value,
            ArtifactKind.VOICE_BIBLE.value,
            ArtifactKind.STORYBOARD_PLAN.value,
            ArtifactKind.RISK_REPORT.value,
            ArtifactKind.SELECTION_PLAN.value,
            ArtifactKind.COST_ESTIMATE.value,
            ArtifactKind.TRIAL_PLAN.value,
        }
        return content_hash(
            {
                "shot": shot,
                "locked_version_refs": {
                    key: value
                    for key, value in locked_refs.items()
                    if key in creative_keys
                },
                "selection": selection_snapshot,
                "quality_policy_id": QUALITY_POLICY_V1,
            }
        )

    @staticmethod
    def _assert_media_preflight(
        *,
        selection: SelectionPlanPayload,
        cost: CostEstimatePayload,
        stage: Literal["trial", "production", "repair"],
    ) -> None:
        if selection.status != "ready":
            raise ValidationAppError(
                "selected media providers are not ready",
                details={
                    "code": "MEDIA_SELECTION_NOT_READY",
                    "selection_status": selection.status,
                    "blockers": [
                        blocker for plan in selection.plans for blocker in plan.blockers
                    ],
                },
            )
        lines = getattr(cost, stage)
        unknown = [line.purpose for line in lines if line.status != "known"]
        if unknown:
            raise ValidationAppError(
                "provider pricing is not verified; paid media calls remain blocked",
                details={"code": "PRICING_NOT_VERIFIED", "purposes": unknown},
            )

    async def _active_budget_approval(
        self,
        *,
        project_id: UUID,
        workflow_id: UUID,
        approval_kind: ApprovalKind,
    ) -> tuple[ApprovalRecord, BudgetAuthorization]:
        approval = await self._session.scalar(
            select(ApprovalRecord)
            .where(
                ApprovalRecord.project_id == project_id,
                ApprovalRecord.workflow_run_id == workflow_id,
                ApprovalRecord.approval_kind == approval_kind.value,
                ApprovalRecord.invalidated_at.is_(None),
            )
            .order_by(ApprovalRecord.approved_at.desc())
        )
        if approval is None or approval.budget_authorization_id is None:
            raise ValidationAppError(
                "an active budget approval is required",
                details={"code": "BUDGET_APPROVAL_REQUIRED"},
            )
        authorization = await self._session.get(
            BudgetAuthorization, approval.budget_authorization_id
        )
        if (
            authorization is None
            or authorization.project_id != project_id
            or authorization.workflow_run_id != workflow_id
            or authorization.authorization_kind != approval_kind.value
        ):
            raise ValidationAppError(
                "budget authorization is no longer active",
                details={"code": "BUDGET_AUTHORIZATION_INACTIVE"},
            )
        expires_at = authorization.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if authorization.status != "active" or expires_at <= datetime.now(UTC):
            raise ValidationAppError(
                "budget authorization is no longer active",
                details={"code": "BUDGET_AUTHORIZATION_INACTIVE"},
            )
        return approval, authorization

    async def _batch_by_key(
        self, project_id: UUID, idempotency_key: str
    ) -> ProductionBatch | None:
        batch = await self._session.scalar(
            select(ProductionBatch).where(
                ProductionBatch.project_id == project_id,
                ProductionBatch.idempotency_key == idempotency_key,
            )
        )
        return batch

    async def _batch_runs(self, batch_id: UUID) -> list[NodeRun]:
        return list(
            (
                await self._session.execute(
                    select(NodeRun)
                    .where(NodeRun.production_batch_id == batch_id)
                    .order_by(NodeRun.created_at)
                )
            ).scalars()
        )

    @staticmethod
    def _reference_prompt(locked_prompt: str, visual: VisualBiblePayload) -> str:
        return (
            f"fictional character reference portrait, {locked_prompt}; "
            f"{visual.era_and_setting}; {visual.color_palette}; {visual.lighting}; "
            "photorealistic live-action, neutral expression, single person, no real person"
        )
