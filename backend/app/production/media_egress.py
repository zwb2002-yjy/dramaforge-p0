"""Shared preview and durable create admission for registered production bindings."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.egress_admission import EgressAdmission
from app.access.egress_models import ProviderDestinationRevision
from app.access.models import Project
from app.assets.from_artifact_service import read_media_source
from app.assets.render_lineage import render_origins_available
from app.assets.source_use import vision_source_revisions
from app.assets.source_use_models import ArtifactSourceUse,SourceUseSubject
from app.contracts.egress_preview import EgressPreview,PayloadSummary,SourceEligibility
from app.providers.destinations import destination_configuration_hash
from app.providers.models import ProviderConnection,ProviderModelBinding
from app.shared.errors import ValidationAppError

MediaPurpose=Literal["image_generation","video_generation","voice_generation"]


async def media_egress_preview(session:AsyncSession, *,project:Project,binding_id:UUID|None,
                             purpose:MediaPurpose,artifact_ids:Sequence[UUID]=(),text_count:int=1,
                             local:bool=False,lock:bool=False,legacy_current:bool=False)->EgressPreview:
    if lock:
        await session.scalar(select(Project.id).where(Project.id==project.id).with_for_update(read=True))
    target = None
    host = None
    config_hash = None
    blockers=[]
    if binding_id and not local:
        q=select(ProviderModelBinding,ProviderConnection).join(ProviderConnection,
                ProviderConnection.id==ProviderModelBinding.connection_id).where(
                ProviderModelBinding.id==binding_id,ProviderConnection.workspace_id==project.workspace_id
                ).execution_options(populate_existing=True)
        if lock:
            q=q.with_for_update(read=True)
        row=(await session.execute(q)).one_or_none()
        if row is None or not row[0].enabled or not row[1].enabled:
            blockers.append("MODEL_BINDING_UNAVAILABLE")
        else:
            binding,connection=row
            host=urlsplit(connection.base_url).hostname
            config_hash=destination_configuration_hash(binding,connection)
            target=await session.scalar(select(ProviderDestinationRevision).where(
                    ProviderDestinationRevision.workspace_id==project.workspace_id,
                    ProviderDestinationRevision.binding_ref==str(binding.id))
                    .order_by(ProviderDestinationRevision.revision.desc()).limit(1))
            if target and target.configuration_hash!=config_hash:
                blockers.append("DESTINATION_CONFIGURATION_CHANGED")
            elif target and purpose not in target.purposes:
                blockers.append("EGRESS_DESTINATION_PURPOSE_MISSING")
    location= "local" if local else target.processing_location if target else "unknown"
    decision=await EgressAdmission(session).decide(project,purpose=purpose,
            destination_id=target.id if target else None,processing_location=location)
    if not local and not decision.allowed:
        blockers.append(decision.reason_code)
    if not local and not target and not (legacy_current and decision.mode=="current"):
        blockers.append("EGRESS_DESTINATION_REQUIRED")
    grants={}
    undeclared=False
    denied=False
    for aid in sorted(set(artifact_ids)):
        media=await read_media_source(session,artifact_id=aid,lock=lock)
        if media is None or media.project_id!=project.id or media.storage_state!="available":
            denied=True
            continue
        if legacy_current and decision.mode=="current":
            # A previously undeclared private reference may use the existing O4 path.
            # Never reinterpret revoked, cross-project or incomplete render lineage as undeclared.
            subject=await session.scalar(select(SourceUseSubject.id).where(
                SourceUseSubject.project_id==project.id,SourceUseSubject.artifact_id==aid))
            edge=await session.scalar(select(ArtifactSourceUse.id).where(
                ArtifactSourceUse.project_id==project.id,ArtifactSourceUse.artifact_id==aid).limit(1))
            if subject is None and edge is None and await render_origins_available(session,project.id,aid):
                undeclared=True
                grants[str(aid)]=[media.content_hash]
                continue
        try:
            grants[str(aid)]=[media.content_hash,*await vision_source_revisions(session,project_id=project.id,artifact_ids=[aid],
                required_uses=frozenset({"external_processing","creation"}))]
        except ValidationAppError:
            denied=True
    if denied:
        blockers.append("SOURCE_USE_BLOCKED")
    stamp=hashlib.sha256(json.dumps({"binding":str(binding_id),"config":config_hash,"grants":grants},
                                  sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return EgressPreview(mode=decision.mode,policy_revision=decision.policy_revision,
        policy_revision_id=decision.policy_revision_id,destination_host=host,
        destination_revision_id=target.id if target else None,actual_processing_location=location,
        purpose=purpose,required_purposes=list(decision.required_purposes),
        payload_summary=PayloadSummary(text_count=text_count,reference_count=len(artifact_ids)),
        source_eligibility=SourceEligibility(allowed=not denied,
            status="blocked" if denied else "legacy_undeclared" if undeclared else "eligible" if grants else "no_source_inputs",
            eligibility_fingerprint=stamp),blockers=sorted(set(blockers)))

async def require_media_egress(session: AsyncSession, *, project: Project, binding_id: UUID | None,
        purpose: MediaPurpose, artifact_ids: Sequence[UUID], frozen: object,legacy_current: bool) -> EgressPreview:
    current=await media_egress_preview(session,project=project,binding_id=binding_id,purpose=purpose,
                  artifact_ids=artifact_ids,lock=True,legacy_current=legacy_current)
    if current.blockers or (frozen is not None and current.model_dump(mode="json")!=frozen) or (
        frozen is None and (not legacy_current or current.mode!="current")
    ):
        raise ValidationAppError("本次发送依据不可用，请重新预览",details={
            "code":current.blockers[0] if current.blockers else "EGRESS_PREVIEW_STALE"})
    return current
