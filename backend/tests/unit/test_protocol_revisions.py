"""Protocol and handler revisions keep exact independent identities."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.providers.protocol_revisions import (
    ProtocolContractContent,
    publish_protocol_contract_revision,
    publish_runtime_handler_revision,
)
from app.providers.transport import AuthSpec, PollSpec, TransportProfile
from app.shared.base import Base
from app.shared.model_registry import load_all_models
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_protocol_and_handler_revisions_keep_prior_facts() -> None:
    load_all_models()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with factory() as session:
            transport = TransportProfile(
                id="minimax-video",
                method="POST",
                path_template="/v1/video_generation",
                auth=AuthSpec(scheme="bearer"),
                content_type="application/json",
                request_encoding="json",
                response_mode="async_poll",
                poll=PollSpec(method="GET", path_template="/v1/query/video_generation"),
            )
            content = ProtocolContractContent(
                protocol_profile="minimax_cn_v1",
                operation_kind="video.generate",
                request_schema_version="r1",
                transport=transport,
            )
            family = uuid4()
            r1 = await publish_protocol_contract_revision(
                session, protocol_contract_id=family, protocol_revision=1, content=content
            )
            r2 = await publish_protocol_contract_revision(
                session,
                protocol_contract_id=family,
                protocol_revision=2,
                content=content.model_copy(update={"request_schema_version": "r2"}),
            )
            assert r1.protocol_hash == content.protocol_hash()
            assert r1.protocol_hash != r2.protocol_hash
            assert r1.contract_json["request_schema_version"] == "r1"
            assert r2.contract_json["request_schema_version"] == "r2"
            with pytest.raises(ValueError, match="operation_kind"):
                await publish_protocol_contract_revision(
                    session,
                    protocol_contract_id=family,
                    protocol_revision=3,
                    content=content.model_copy(update={"operation_kind": "invalid"}),
                )

            handler_family = uuid4()
            h1 = await publish_runtime_handler_revision(
                session,
                runtime_handler_id=handler_family,
                handler_revision=1,
                handler_key="minimax-video",
                implementation_digest="a" * 64,
            )
            h2 = await publish_runtime_handler_revision(
                session,
                runtime_handler_id=handler_family,
                handler_revision=2,
                handler_key="minimax-video",
                implementation_digest="b" * 64,
            )
            assert h1.implementation_digest == "a" * 64
            assert h2.implementation_digest == "b" * 64
            with pytest.raises(ValueError, match="SHA-256"):
                await publish_runtime_handler_revision(
                    session,
                    runtime_handler_id=handler_family,
                    handler_revision=3,
                    handler_key="minimax-video",
                    implementation_digest="not-a-digest",
                )
    finally:
        await engine.dispose()
