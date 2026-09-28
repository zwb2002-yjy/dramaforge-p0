"""Prepare a frozen media request and submission marker without submitting it."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.execution.models import Artifact, NodeRun, ProviderOperation
from app.execution.run_state import (
    UNIFIED_PATH_VERSION,
    _commit_terminal_failure,
)
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
from app.providers.request_summary import normalize_request_summary
from app.providers.runtime import (
    CompiledImageRequest,
    CompiledVideoRequest,
    ProviderRuntime,
    ProviderRuntimeResolver,
    ResolvedReference,
)
from app.providers.selection import ModelSelectionService, SelectionPlan
from app.providers.translation import RequestTransformation
from app.shared.db import set_node_run_rls_context
from app.shared.errors import (
    ValidationAppError,
)
from app.storage.minio_store import ObjectStore


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


@dataclass(frozen=True)
class PreparedMediaSubmission:
    """Compiled request and durably recorded identity, ready for one submission."""

    operation: ProviderOperation
    compiled: CompiledImageRequest | CompiledVideoRequest
    runtime: ProviderRuntime
    identity_json: dict[str, Any]


async def prepare_media_submission(
    session: AsyncSession,
    *,
    project: Project,
    run: NodeRun,
    node_type: str,
    snap: dict[str, object],
    obj_store: ObjectStore,
    prompt: str,
    canonical_image_bytes: bytes | None,
    has_canonical_binding: bool,
    canonical_artifact: Artifact | None,
    frozen_identity: ExecutionIdentitySnapshot | None,
    workbench_plan: WorkbenchExecutionPlan | None,
    op: ProviderOperation | None,
    now: datetime,
) -> PreparedMediaSubmission:
    """Resolve and compile before durably marking submission; never call submit/poll.

    The same frozen identity is revalidated on a rejected-operation retry. The
    transaction commit deliberately precedes the caller's paid network boundary.
    """
    workbench_planned_references = (
        list(workbench_plan.planned_references) if workbench_plan is not None else []
    )
    connection_revision: ProviderConnectionRevision | None = None
    plan: Any = None
    connection: Any = None
    binding: Any = None
    entry: Any = None
    invoke_model_value: str | None
    frozen_binding_id = (
        frozen_identity.provider_model_binding_id if frozen_identity is not None else None
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
                "UPSTREAM_ARTIFACT_MISSING: approved first-frame bytes unavailable for video I2V"
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
        if planned_first_frame is not None and planned_first_frame.artifact_id != first_frame.id:
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
            frozen_resolution.provider_model_binding_id != frozen_identity.provider_model_binding_id
            or frozen_resolution.resolved_model_id != frozen_identity.resolved_model
            or frozen_resolution.manifest_hash != frozen_identity.manifest_hash
            or frozen_resolution.invoke_model_value != frozen_identity.invoke_model_value
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
            or connection_revision.credential_revision_id != frozen_identity.credential_revision_id
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
                or workbench_plan.credential_revision_id != frozen_resolution.credential_revision_id
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
            entry = await session.get(ModelCatalogEntry, frozen_resolution.catalog_entry_id)
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
            resolved = await ProviderRuntimeResolver(session).resolve_runtime_for_resolution(
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
            selection_snapshot["execution_model_resolution"] = frozen_resolution.model_dump(
                mode="json"
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
            resolved = await ProviderRuntimeResolver(session).resolve_runtime_for_resolution(
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
            "execution_model_resolution": plan.execution_model_resolution.model_dump(mode="json"),
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
                    "workflow_participations": (shot_row.director_state or {}).get(
                        "workflow_participations"
                    )
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
                content_bytes = await obj_store.get_bytes(object_key=artifact.object_key)
            except Exception as exc:
                raise ValidationAppError(
                    "frozen Workbench reference bytes are unavailable",
                    details={"code": "REFERENCE_ARTIFACT_REQUIRED"},
                ) from exc
        if not content_bytes or hashlib.sha256(content_bytes).hexdigest() != artifact.content_hash:
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
                    existing_bytes=frame_bytes if reference.artifact_id == first_frame.id else None,
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
        "reference_artifact_ids": [str(value) for value in compiled.reference_artifact_ids],
        "reference_fingerprints": list(compiled.reference_fingerprints),
    }
    raw_transformations = compiled.safe_request_summary.get("translation_transformations")
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
            requested_model=(plan.execution_model_resolution.requested_model_id or plan.model_id),
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
        resolved = await ProviderRuntimeResolver(session).resolve_runtime_for_identity(
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
            request_summary=normalize_request_summary(
                {
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
                }
            ),
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

    return PreparedMediaSubmission(
        operation=op,
        compiled=compiled,
        runtime=runtime,
        identity_json=identity_json,
    )
