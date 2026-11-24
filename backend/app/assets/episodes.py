"""Project-serialized admission shared by script import and typed Story Apply."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.assets.models import Episode
from app.shared.errors import ConflictError, NotFoundError


async def lock_episode_project(session: AsyncSession, project_id: UUID) -> Project:
    project = await session.scalar(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
        .with_for_update().execution_options(populate_existing=True)
    )
    if project is None:
        raise NotFoundError("project not found")
    return project


async def require_new_episode_capacity(session: AsyncSession, project: Project) -> None:
    """Caller holds the Project lock until the Episode insert and transaction commit."""
    limit = 1 if project.work_type == "single_comic" else project.planned_episode_count
    if limit is None:
        return
    count = int(await session.scalar(
        select(func.count()).select_from(Episode).where(Episode.project_id == project.id)
    ) or 0)
    if count >= limit:
        raise ConflictError(
            "新增分集超出当前作品计划，请先明确调整作品类型或计划集数。",
            details={"code": "PROJECT_STRUCTURE_CONFLICT", "episode_count": count,
                     "planned_episode_count": limit},
        )
