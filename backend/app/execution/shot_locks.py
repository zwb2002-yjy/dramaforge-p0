"""Durable human locks for canonical Shot workbench edits."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.models import ShotHumanLock


async def is_shot_locked(session: AsyncSession, *, project_id: UUID, shot_id: UUID) -> bool:
    row = (
        await session.execute(
            select(ShotHumanLock).where(
                ShotHumanLock.project_id == project_id,
                ShotHumanLock.shot_id == shot_id,
                ShotHumanLock.locked.is_(True),
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def set_shot_lock(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    user_id: UUID,
    locked: bool,
) -> ShotHumanLock:
    existing = (
        await session.execute(
            select(ShotHumanLock).where(
                ShotHumanLock.project_id == project_id,
                ShotHumanLock.shot_id == shot_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        try:
            async with session.begin_nested():
                existing = ShotHumanLock(
                    project_id=project_id,
                    shot_id=shot_id,
                    locked=locked,
                    locked_by=user_id if locked else None,
                )
                session.add(existing)
                await session.flush()
        except IntegrityError:
            # A concurrent set created the same (project, shot) row after our
            # read. Only the persisted winner explains the race; unrelated
            # constraint failures must propagate.
            existing = (
                await session.execute(
                    select(ShotHumanLock).where(
                        ShotHumanLock.project_id == project_id,
                        ShotHumanLock.shot_id == shot_id,
                    )
                )
            ).scalar_one()
            existing.locked = locked
            existing.locked_by = user_id if locked else None
            await session.flush()
    else:
        existing.locked = locked
        existing.locked_by = user_id if locked else None
        await session.flush()
    return existing
