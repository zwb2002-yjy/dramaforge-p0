"""Policy revision publication never rewrites or implicitly revokes history."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.production.policy_models import ProductPolicyEvent, ProductPolicyState
from app.production.policy_revisions import (
    ProductPolicyContent,
    publish_product_policy_revision,
    revoke_product_policy_revision,
)
from app.shared.base import Base
from app.shared.model_registry import load_all_models
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_revision_and_revocation_are_independent() -> None:
    load_all_models()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with factory() as session:
            policy_id = uuid4()
            content = ProductPolicyContent(
                product_path="formal_video",
                allowed_operations=frozenset({"video.generate"}),
                allowed_contracts={"video.generate": frozenset({"first_frame"})},
                allowed_options={"video.generate": frozenset({"duration_seconds"})},
            )
            r1 = await publish_product_policy_revision(
                session,
                policy_id=policy_id,
                policy_revision=1,
                content=content,
                reason="initial formal video policy",
            )
            r2 = await publish_product_policy_revision(
                session,
                policy_id=policy_id,
                policy_revision=2,
                content=content.model_copy(
                    update={"allowed_options": {"video.generate": frozenset()}}
                ),
                reason="close optional duration",
            )
            assert r1.policy_hash == content.policy_hash()
            assert r2.policy_hash != r1.policy_hash
            assert (await session.get(ProductPolicyState, r1.id)).status == "active"
            assert (await session.get(ProductPolicyState, r2.id)).status == "active"

            await revoke_product_policy_revision(
                session, policy_revision_id=r1.id, reason="explicitly revoked"
            )
            assert (await session.get(ProductPolicyState, r1.id)).status == "revoked"
            assert (await session.get(ProductPolicyState, r2.id)).status == "active"
            events = list((await session.scalars(select(ProductPolicyEvent))).all())
            assert len(events) == 3
            assert (
                sum(
                    event.from_status == "active" and event.to_status == "revoked"
                    for event in events
                )
                == 1
            )
            with pytest.raises(ValueError, match="already revoked"):
                await revoke_product_policy_revision(
                    session, policy_revision_id=r1.id, reason="duplicate revoke"
                )
    finally:
        await engine.dispose()


def test_policy_hash_is_order_independent_and_rejects_unknown_operations() -> None:
    first = ProductPolicyContent(
        product_path="formal_video",
        allowed_operations=frozenset({"video.generate", "image.generate"}),
        allowed_contracts={"video.generate": frozenset({"frame", "text"})},
        allowed_options={"video.generate": frozenset({"resolution", "duration_seconds"})},
    )
    second = ProductPolicyContent(
        product_path="formal_video",
        allowed_operations=frozenset({"image.generate", "video.generate"}),
        allowed_contracts={"video.generate": frozenset({"text", "frame"})},
        allowed_options={"video.generate": frozenset({"duration_seconds", "resolution"})},
    )
    assert first.policy_hash() == second.policy_hash()
    with pytest.raises(ValueError, match="contracts reference an operation"):
        ProductPolicyContent(
            product_path="formal_video",
            allowed_operations=frozenset({"video.generate"}),
            allowed_contracts={"image.generate": frozenset({"text"})},
            allowed_options={},
        )
