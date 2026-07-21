"""P0-AGENT-1: Agent Brief/Plan generation with Fake text adapter (APP_ENV=test)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.access.models import Organization, OrganizationMember, User
from app.creation import models as _cm  # noqa: F401
from app.creation.models import AgentRun
from app.creation.service import CreationService
from app.execution import models as _xm  # noqa: F401
from app.execution.models import ProviderOperation
from app.shared.base import Base
from app.shared.enums import MemberRole
from app.shared.security import hash_password


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_generate_brief_and_plan_agent_records_ops(session: AsyncSession) -> None:
    suffix = uuid4().hex[:8]
    user = User(
        email=f"agent-{suffix}@example.com",
        display_name="A",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    org = Organization(name=f"O-{suffix}")
    session.add(org)
    await session.flush()
    session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user.id, role=MemberRole.OWNER.value
        )
    )
    await session.commit()

    svc = CreationService(session)
    started = await svc.start_project(
        organization_id=org.id,
        name=f"P-{suffix}",
        aspect_ratio="9:16",
        actor=user,
        idea="neon rain short",
    )
    rev = await svc.generate_brief_agent(
        project_id=started.project_id,
        actor=user,
        idea="霓虹雨夜女主被跟踪",
        authorize=True,
    )
    assert rev.source_kind == "agent"
    assert rev.brief.get("logline")
    assert rev.status == "draft"

    confirmed = await svc.confirm_brief(
        project_id=started.project_id, revision_id=rev.id, actor=user
    )
    assert confirmed.status == "confirmed"

    plan = await svc.generate_plan_agent(
        project_id=started.project_id,
        actor=user,
        brief_revision_id=confirmed.id,
        authorize=True,
    )
    assert plan.plan.get("prompt")
    assert plan.source_agent_run_id is not None

    runs = (
        await session.execute(select(AgentRun).where(AgentRun.project_id == started.project_id))
    ).scalars().all()
    assert len(runs) >= 2
    assert all(r.status == "completed" for r in runs)

    ops = (
        await session.execute(
            select(ProviderOperation).where(
                ProviderOperation.agent_run_id.in_([r.id for r in runs])
            )
        )
    ).scalars().all()
    assert len(ops) >= 2
    assert all(o.status == "succeeded" for o in ops)
