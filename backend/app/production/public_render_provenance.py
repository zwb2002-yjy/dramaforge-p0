"""Bind each newly rendered public input to the license revision used for its admission."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.public_edit_media import read_public_edit_media
from app.assets.render_lineage import render_origins_available
from app.assets.source_use_models import ArtifactSourceUse, SourceUseRevision, SourceUseSubject
from app.execution.models import Artifact, NodeRun
from app.shared.errors import ValidationAppError

if TYPE_CHECKING:
    from app.editing.timeline_schema import PublicRenderInput


class _Basis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    public_asset_link_id: UUID
    publication_id: UUID
    publication_item_id: UUID
    source_artifact_id: UUID


class _Grant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    access_basis: _Basis
    source_project_id: UUID
    source_subject_id: UUID
    source_revision_id: UUID
    clip_index: int = Field(ge=0)
    media_kind: Literal["video", "audio"]
    artifact_hash: str

    @property
    def input_role(self) -> str:
        return f"{self.media_kind}:{self.clip_index}"


def _denied() -> ValidationAppError:
    return ValidationAppError(
        "公共素材缺少可核对的冻结来源依据", details={"code": "RENDER_PROVENANCE_UNAVAILABLE"}
    )


async def freeze_public_render_grants(
    session: AsyncSession, project_id: UUID, public_inputs: list[PublicRenderInput]
) -> list[dict[str, object]]:
    frozen = []
    for item in sorted(
        public_inputs, key=lambda v: (str(v.artifact_id), v.clip_index, v.media_kind)
    ):
        src = item.source
        if not (src.public_asset_link_id and src.publication_id and src.publication_item_id):
            raise _denied()
        basis = _Basis(
            public_asset_link_id=src.public_asset_link_id,
            publication_id=src.publication_id,
            publication_item_id=src.publication_item_id,
            source_artifact_id=item.artifact_id,
        )
        if session.get_bind().dialect.name == "postgresql":
            row = (
                await session.execute(
                    text(
                        "SELECT * FROM app.public_render_grant("
                        ":project,:link,:publication,:item,:artifact,:hash,:kind)"
                    ),
                    {
                        "project": project_id,
                        "link": basis.public_asset_link_id,
                        "publication": basis.publication_id,
                        "item": basis.publication_item_id,
                        "artifact": item.artifact_id,
                        "hash": item.artifact_hash,
                        "kind": item.media_kind,
                    },
                )
            ).one_or_none()
        else:
            source = await read_public_edit_media(
                session,
                project_id=project_id,
                link_id=basis.public_asset_link_id,
                publication_id=basis.publication_id,
                item_id=basis.publication_item_id,
                purpose="export",
            )
            if source is None or (source.id, source.artifact_type, source.content_hash) != (
                item.artifact_id,
                item.media_kind,
                item.artifact_hash,
            ):
                raise _denied()
            row = (
                await session.execute(
                    select(SourceUseSubject.project_id, SourceUseSubject.id, SourceUseRevision.id)
                    .join(
                        SourceUseRevision,
                        SourceUseSubject.current_revision_id == SourceUseRevision.id,
                    )
                    .where(
                        SourceUseSubject.artifact_id == source.id,
                        SourceUseSubject.project_id == source.project_id,
                        SourceUseRevision.subject_id == SourceUseSubject.id,
                        SourceUseRevision.state == "declared",
                    )
                )
            ).one_or_none()
        if row is None:
            raise _denied()
        grant = _Grant(
            access_basis=basis,
            source_project_id=row[0],
            source_subject_id=row[1],
            source_revision_id=row[2],
            clip_index=item.clip_index,
            media_kind=item.media_kind,
            artifact_hash=item.artifact_hash,
        )
        frozen.append(grant.model_dump(mode="json"))
    return frozen


def _frozen_grants(snapshot: dict[str, object]) -> list[_Grant]:
    inputs = snapshot.get("public_inputs", [])
    raw = snapshot.get("public_source_grants", [])
    if not isinstance(inputs, list) or not isinstance(raw, list) or len(raw) != len(inputs):
        raise _denied()
    try:
        grants = [_Grant.model_validate(v) for v in raw]
        required = Counter(
            (
                i["clip_index"],
                i["media_kind"],
                i["artifact_id"],
                i["artifact_hash"],
                i["source"]["public_asset_link_id"],
                i["source"]["publication_id"],
                i["source"]["publication_item_id"],
            )
            for i in inputs
            if i["source"]["kind"] == "public_material"
        )
    except (ValidationError, KeyError, TypeError):
        raise _denied() from None
    actual = Counter(
        (
            g.clip_index,
            g.media_kind,
            str(g.access_basis.source_artifact_id),
            g.artifact_hash,
            str(g.access_basis.public_asset_link_id),
            str(g.access_basis.publication_id),
            str(g.access_basis.publication_item_id),
        )
        for g in grants
    )
    if required != actual or len(actual) != len(grants):
        raise _denied()
    return grants


def _origin(g: _Grant) -> tuple[object, ...]:
    return (g.input_role, g.source_project_id, g.source_subject_id, g.access_basis, g.artifact_hash)


async def complete_public_render_grants(
    session: AsyncSession, run: NodeRun, artifact: Artifact
) -> None:
    """Never manufacture missing historical authorization from today's source head."""
    snapshot = run.input_snapshot or {}
    grants = _frozen_grants(snapshot)
    if artifact.project_id != run.project_id:
        raise _denied()
    if (
        snapshot.get("subtitle_input_kind") == "saved_text_and_timing"
        and snapshot.get("node_key") in {"edit_session_render", "final_film_assembly"}
        and artifact.artifact_type == "subtitle"
        and artifact.mime_type == "application/x-subrip"
    ):
        # The verified run's MP4 consumes public media. Its separate SRT consumes
        # the saved caption text and timings only. Byte reuse must not rewrite
        # the older subtitle's producer or any genuine pre-existing lineage.
        return
    # A content-addressed output may already belong to another run. Reuse it only
    # when the existing immutable public origins describe the same inputs.
    await session.scalar(
        select(Artifact.id)
        .where(Artifact.id == artifact.id, Artifact.project_id == run.project_id)
        .with_for_update()
    )
    previous = list(
        await session.scalars(
            select(ArtifactSourceUse).where(
                ArtifactSourceUse.project_id == run.project_id,
                ArtifactSourceUse.artifact_id == artifact.id,
                ArtifactSourceUse.source_access_kind == "public_asset",
            )
        )
    )
    if previous or artifact.produced_by_run_id != run.id:
        if not previous and not grants:
            if not await render_origins_available(session, run.project_id, artifact.id):
                raise _denied()
            return
        producer = await session.scalar(
            select(NodeRun).where(
                NodeRun.id == artifact.produced_by_run_id, NodeRun.project_id == artifact.project_id
            )
        )
        if producer is None:
            raise _denied()
        original = _frozen_grants(producer.input_snapshot or {})
        if Counter(map(_origin, original)) != Counter(map(_origin, grants)):
            raise _denied()
        # Verify every immutable edge against the original producer's own frozen declaration,
        # independent of the different revision that can legitimately authorize today's render.
        expected = {
            (
                g.input_role,
                g.source_project_id,
                g.source_subject_id,
                g.source_revision_id,
                tuple(sorted(g.access_basis.model_dump(mode="json").items())),
            )
            for g in original
        }
        actual_edges = {
            (
                r.input_role,
                r.source_project_id,
                r.source_subject_id,
                r.source_revision_id,
                tuple(sorted(r.access_basis.items())),
            )
            for r in previous
            if r.consumer_node_run_id == producer.id
        }
        if actual_edges != expected or len(actual_edges) != len(previous):
            raise _denied()
        return
    for g in grants:
        session.add(
            ArtifactSourceUse(
                project_id=run.project_id,
                artifact_id=artifact.id,
                source_subject_id=g.source_subject_id,
                source_project_id=g.source_project_id,
                source_revision_id=g.source_revision_id,
                consumer_node_run_id=run.id,
                input_role=g.input_role,
                source_access_kind="public_asset",
                access_basis=g.access_basis.model_dump(mode="json"),
            )
        )
    await session.flush()
