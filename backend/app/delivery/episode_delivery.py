"""Per-episode delivery orchestration (I9-02).

A serial project delivers one film per episode. This service reports, per episode,
whether a delivery can start (an episode-scoped edit session must exist) and then
freezes an export plus its render run for each ready episode. It never creates an
implicit session: an episode without one is reported as blocked instead of being
silently shipped as a project-wide film.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.assets.models import Episode
from app.delivery.export_service import ExportService
from app.delivery.render_execution import create_edit_session_render
from app.editing.models import EditSession

DeliveryStatus = Literal["planned", "blocked", "started"]


@dataclass(frozen=True)
class EpisodeDeliveryItem:
    episode_id: UUID
    episode_number: int
    session_id: UUID | None
    session_version: int | None
    export_id: UUID | None
    node_run_id: UUID | None
    status: DeliveryStatus
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "episode_id": str(self.episode_id),
            "episode_number": self.episode_number,
            "session_id": str(self.session_id) if self.session_id else None,
            "session_version": self.session_version,
            "export_id": str(self.export_id) if self.export_id else None,
            "node_run_id": str(self.node_run_id) if self.node_run_id else None,
            "status": self.status,
            "blockers": list(self.blockers),
        }


class EpisodeDeliveryService:
    """Caller owns the transaction and has already verified project ownership."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _episodes(self, project_id: UUID) -> list[Episode]:
        return list(
            (
                await self._session.scalars(
                    select(Episode)
                    .where(Episode.project_id == project_id)
                    .order_by(Episode.episode_number, Episode.id)
                )
            ).all()
        )

    async def _session_for_episode(
        self, *, project_id: UUID, episode_id: UUID
    ) -> EditSession | None:
        session_row = await self._session.scalar(
            select(EditSession)
            .where(
                EditSession.project_id == project_id,
                EditSession.episode_id == episode_id,
            )
            .order_by(EditSession.updated_at.desc(), EditSession.id.desc())
            .limit(1)
        )
        return session_row if isinstance(session_row, EditSession) else None

    async def plan(self, *, project_id: UUID) -> list[EpisodeDeliveryItem]:
        """Report what can be delivered per episode, without writing anything."""
        items: list[EpisodeDeliveryItem] = []
        for episode in await self._episodes(project_id):
            session_row = await self._session_for_episode(
                project_id=project_id, episode_id=episode.id
            )
            if session_row is None:
                items.append(
                    EpisodeDeliveryItem(
                        episode_id=episode.id,
                        episode_number=episode.episode_number,
                        session_id=None,
                        session_version=None,
                        export_id=None,
                        node_run_id=None,
                        status="blocked",
                        blockers=("DELIVERY_SESSION_MISSING",),
                    )
                )
                continue
            items.append(
                EpisodeDeliveryItem(
                    episode_id=episode.id,
                    episode_number=episode.episode_number,
                    session_id=session_row.id,
                    session_version=session_row.version,
                    export_id=None,
                    node_run_id=None,
                    status="planned",
                    blockers=(),
                )
            )
        return items

    async def start(
        self,
        *,
        project: Project,
        actor_id: UUID,
        format: str = "mp4",
    ) -> list[EpisodeDeliveryItem]:
        """Freeze one export and one render run for every ready episode."""
        exports = ExportService(self._session)
        started: list[EpisodeDeliveryItem] = []
        for item in await self.plan(project_id=project.id):
            if item.status == "blocked" or item.session_id is None:
                started.append(item)
                continue
            export, _created = await exports.create_session_export(
                project_id=project.id,
                session_id=item.session_id,
                requested_by=actor_id,
                format=format,
                # One receipt per (episode, session version): a rerun after an
                # already-started delivery returns the same export.
                idempotency_key=(
                    f"episode-delivery:{item.episode_id}:{item.session_id}:{item.session_version}"
                ),
            )
            if export.timeline_version != item.session_version:
                started.append(
                    EpisodeDeliveryItem(
                        episode_id=item.episode_id,
                        episode_number=item.episode_number,
                        session_id=item.session_id,
                        session_version=item.session_version,
                        export_id=export.id,
                        node_run_id=None,
                        status="blocked",
                        blockers=("DELIVERY_RECEIPT_STALE",),
                    )
                )
                continue
            run = await create_edit_session_render(
                self._session,
                project_id=project.id,
                session_id=item.session_id,
                export_id=export.id,
                actor_id=actor_id,
            )
            started.append(
                EpisodeDeliveryItem(
                    episode_id=item.episode_id,
                    episode_number=item.episode_number,
                    session_id=item.session_id,
                    session_version=item.session_version,
                    export_id=export.id,
                    node_run_id=run.id,
                    status="started",
                    blockers=(),
                )
            )
        return started


__all__ = ["EpisodeDeliveryItem", "EpisodeDeliveryService"]
