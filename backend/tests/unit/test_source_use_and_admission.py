"""Source-use declarations and the single egress admission decision (T09)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.egress_admission import EgressAdmission
from app.access.egress_models import ProviderDestinationRevision
from app.access.models import User, Workspace
from app.access.project_data_policy import ProjectDataPolicy
from app.access.projects import ProjectService
from app.assets.source_use import SourceUseService
from app.assets.source_use_models import SourceUseRevision, SourceUseSubject
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed(session: AsyncSession):
    user = User(
        email=f"admission-{uuid4().hex}@example.com", display_name="Owner", password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        work_type="single_comic", workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:8]}", aspect_ratio="9:16", actor=user,
    )
    session.info["selected_workspace_id"] = workspace.id
    return user, workspace, project


def _destination(workspace: Workspace, user: User, *, location: str, purposes: list[str]):
    return ProviderDestinationRevision(
        workspace_id=workspace.id, binding_ref=str(uuid4()), revision=1,
        origin_expected_revision=0,
        upstream_origin="http://litellm-proxy:4000" if location == "local"
        else "https://api.example.cn:443",
        processing_location=location, purposes=purposes,
        declaration_hash="a" * 64, configuration_hash="b" * 64,
        route_manifest={"schema_version": 1}, location_evidence={}, created_by=user.id,
    )


async def test_source_use_declaration_replay_revocation_and_gate(session: AsyncSession):
    user, workspace, project = await _seed(session)
    service = SourceUseService(session, actor=user, project=project)
    file_revision = uuid4()
    with pytest.raises(ValidationAppError):
        await service.declare(
            file_revision_id=file_revision, allowed_uses=["research"],
            statement="", request_key="k1",
        )
    declared = await service.declare(
        file_revision_id=file_revision, allowed_uses=["research", "research"],
        statement="该资料由本人整理，可用于研究引用。", request_key="k1",
    )
    assert declared.state == "declared" and declared.allowed_uses == ["research"]
    assert declared.number == 1 and declared.result_version == 2
    assert (await service.declare(
        file_revision_id=file_revision, allowed_uses=["research"],
        statement="该资料由本人整理，可用于研究引用。", request_key="k1",
    )).id == declared.id
    with pytest.raises(ConflictError):
        await service.declare(
            file_revision_id=file_revision, allowed_uses=["external_processing"],
            statement="另一个声明", request_key="k1",
        )
    gate = await service.gate(file_revision_ids=[file_revision], required_uses=["research"])
    assert gate["allowed"] is True
    strict = await service.gate(
        file_revision_ids=[file_revision], required_uses=["research", "external_processing"],
    )
    assert strict["allowed"] is False
    assert strict["blocked"][0]["code"] == "USE_NOT_DECLARED"
    undeclared = await service.gate(file_revision_ids=[uuid4()], required_uses=["research"])
    assert undeclared["blocked"][0]["code"] == "UNDECLARED"
    revoked = await service.declare(
        file_revision_id=file_revision, allowed_uses=[], statement="来源请求撤回",
        request_key="k2", state="revoked",
    )
    assert revoked.state == "revoked" and revoked.allowed_uses == []
    assert revoked.number == 2
    after = await service.gate(file_revision_ids=[file_revision], required_uses=["research"])
    assert after["blocked"][0]["code"] == "REVOKED"
    with pytest.raises(ConflictError) as restore:
        await service.declare(
            file_revision_id=file_revision, allowed_uses=["research"],
            statement="恢复", request_key="k3",
        )
    assert restore.value.details["code"] == "SOURCE_USE_REVOKED"
    assert await session.scalar(select(func.count(SourceUseSubject.id))) == 1
    assert await session.scalar(select(func.count(SourceUseRevision.id))) == 2
    with pytest.raises(NotFoundError):
        await service.current(uuid4())


async def test_admission_modes_required_purposes_and_revocation_barrier(session: AsyncSession):
    user, workspace, project = await _seed(session)
    admission = EgressAdmission(session)
    policy = ProjectDataPolicy(session, actor=user, project=project)
    # No head: the historical path stays permitted and records that fact.
    legacy = await admission.decide(project, purpose="director_text", processing_location="local")
    assert legacy.allowed and legacy.reason_code == "legacy_current"
    assert legacy.policy_revision == 0 and legacy.evidence()["decision"] == "allowed"
    with pytest.raises(ValidationAppError):
        await admission.decide(
            project, purpose="director_text", required_purposes=["research"],
        )
    await policy.put(
        expected_revision=0, mode="local_only",
        allowed_destination_revision_ids=[], allowed_purposes=[],
    )
    assert (await admission.decide(
        project, purpose="director_text", processing_location="local",
    )).allowed
    external = await admission.decide(
        project, purpose="director_text", processing_location="external",
    )
    assert not external.allowed and external.reason_code == "EGRESS_LOCAL_ONLY"
    # Strict allowlist: destination and every required purpose must both be covered.
    local_destination = _destination(workspace, user, location="local", purposes=["research_text"])
    session.add(local_destination)
    await session.flush()
    await policy.put(
        expected_revision=1, mode="allowlisted",
        allowed_destination_revision_ids=[str(local_destination.id)],
        allowed_purposes=["research_text"],
    )
    missing = await admission.decide(project, purpose="research_text", processing_location="local")
    assert not missing.allowed and missing.reason_code == "EGRESS_DESTINATION_REQUIRED"
    allowed = await admission.decide(
        project, purpose="research_text", processing_location="local",
        destination_id=local_destination.id,
    )
    assert allowed.allowed and allowed.reason_code == "allowlisted_allowed"
    assert allowed.destination_revision_id == local_destination.id
    vision = await admission.decide(
        project, purpose="research_text", required_purposes=["research_text", "vision_input"],
        processing_location="local", destination_id=local_destination.id,
    )
    assert not vision.allowed and vision.reason_code == "EGRESS_PURPOSE_NOT_ALLOWED"
    # A source-use refusal wins over an otherwise permissive destination.
    blocked_source = await admission.decide(
        project, purpose="research_text", processing_location="local",
        destination_id=local_destination.id,
        source_use={"allowed": False, "blocked": [{"code": "REVOKED"}]},
    )
    assert not blocked_source.allowed and blocked_source.reason_code == "SOURCE_USE_BLOCKED"
    # Revocation barrier: the decision reads the head at send time, so a policy
    # change between preview and send is observed instead of cached.
    await policy.put(
        expected_revision=2, mode="local_only",
        allowed_destination_revision_ids=[], allowed_purposes=[],
    )
    after_revoke = await admission.decide(
        project, purpose="research_text", processing_location="local",
        destination_id=local_destination.id,
    )
    assert after_revoke.allowed and after_revoke.reason_code == "local_only_allowed"
    assert after_revoke.policy_revision == 3
    external_after = await admission.decide(
        project, purpose="research_text", processing_location="external",
        destination_id=local_destination.id,
    )
    assert not external_after.allowed


async def test_source_use_impact_lists_current_project_artifacts_with_cursor(session):
    from uuid import uuid4

    from app.access.models import User, Workspace
    from app.access.projects import ProjectService
    from app.assets.source_use import SourceUseService
    from app.assets.source_use_models import SourceUseSubject
    from sqlalchemy import select

    user = User(
        email=f"impact-{uuid4().hex}@example.com", display_name="Owner", password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        work_type="single_comic", workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:8]}", aspect_ratio="9:16", actor=user,
    )
    session.info["selected_workspace_id"] = workspace.id
    service = SourceUseService(session, actor=user, project=project)
    revision = await service.declare(
        file_revision_id=uuid4(), allowed_uses=["research"],
        statement="可用于研究", request_key="impact-1",
    )
    subject = await session.scalar(select(SourceUseSubject))
    assert subject is not None
    from app.execution.models import Artifact

    for index in range(3):
        artifact = Artifact(
            project_id=project.id,
            artifact_type="image",
            storage_state="available",
            object_key=f"projects/{project.id}/impact/{index}.png",
            content_hash=f"{index:064x}",
            mime_type="image/png",
            byte_size=1,
        )
        session.add(artifact)
        await session.flush()
        await service.record_artifact_source_use(
            artifact_id=artifact.id,
            source_subject_id=subject.id,
            source_project_id=project.id,
            source_revision_id=revision.id,
            consumer_node_run_id=uuid4(),
            input_role=f"role-{index}",
        )
    await session.commit()
    first, cursor = await service.impact(subject_id=subject.id, limit=2)
    assert len(first) == 2 and cursor is not None
    rest, next_cursor = await service.impact(subject_id=subject.id, limit=2, cursor=cursor)
    assert len(rest) == 1 and next_cursor is None
    assert {use.input_role for use in first + rest} == {"role-0", "role-1", "role-2"}
    with pytest.raises(NotFoundError):
        await service.impact(subject_id=uuid4())
