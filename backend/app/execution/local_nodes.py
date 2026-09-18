"""Complete local composite and review nodes without Provider submission."""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.consistency.identity_policy import (
    identity_evidence_policy_snapshot,
)
from app.consistency.identity_review import identity_review_images
from app.execution.artifact_inputs import _read_bound_artifact
from app.execution.artifact_lineage import get_or_create_artifact
from app.execution.models import GraphNode, NodeRun
from app.execution.run_state import ExecuteNodeResult, _commit_terminal_failure
from app.shared.errors import (
    ValidationAppError,
)
from app.storage.minio_store import ObjectStore


async def _complete_composite_node(
    session: AsyncSession,
    *,
    run: NodeRun,
    node: GraphNode,
    obj_store: ObjectStore,
) -> ExecuteNodeResult:
    """Compose local video, voice, and subtitles without a Provider operation."""
    from datetime import UTC, datetime

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
    if (run.input_snapshot or {}).get("execution_branch") == "formal" and (
        run.input_snapshot or {}
    ).get("experiment_id") is None:
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
        allow_cross_run_reuse=art_type == "audio",
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
