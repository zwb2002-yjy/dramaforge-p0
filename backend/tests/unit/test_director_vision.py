"""Owner-selected media travels through acceptance, the worker journal and the Proxy."""

import base64
import hashlib
import io
import json
import subprocess
from uuid import uuid4

import httpx
import pytest
from app.access.egress_models import ProviderDestinationRevision
from app.access.models import Project, User
from app.access.project_data_policy import ProjectDataPolicy
from app.assets.source_use import SourceUseService
from app.config import Settings
from app.director.agent_service import AgentRequest, AgentThreadCreate
from app.director.invocation_models import DirectorInvocation
from app.director.text_model import CapabilityTextModel
from app.director.text_transport import ResolvedAgentTextModel
from app.execution.models import Artifact
from app.providers.litellm_adapter import LiteLLMModelAdapter
from app.providers.litellm_gateway.management import GatewayReference
from app.providers.litellm_gateway.model_catalog import litellm_logical_manifest
from app.providers.models import ProviderConnection
from app.providers.registry import ModelRegistry
from app.security.models import EncryptedProviderCredential
from app.shared.errors import ValidationAppError
from app.storage.minio_store import reset_object_store_for_tests
from PIL import Image
from sqlalchemy import select
from test_director_agent_service import agent_world as agent_world
from test_director_agent_service import execute


@pytest.mark.parametrize(
    "case", ["still", "video", "text_only", "local_only", "revoked", "wrong_bytes"]
)
async def test_selected_media_reaches_only_an_admitted_vision_turn(
    agent_world, case, monkeypatch, tmp_path
):
    w = agent_world
    store = reset_object_store_for_tests()
    incoming = []
    if case == "video":
        path = tmp_path / "scene.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=96x64:r=24:d=1",
                "-c:v",
                "libx264",
                str(path),
            ],
            check=True,
        )
        raw, mime = path.read_bytes(), "video/mp4"
    else:
        source = io.BytesIO()
        Image.new("RGB", (1500, 750), "red").save(source, "PNG")
        raw, mime = source.getvalue(), "image/png"
    stored = await store.put_bytes(object_key="test/scene", data=raw, mime_type=mime)
    conn_id, deploy = uuid4(), uuid4()
    alias = f"df-{deploy.hex}"
    ref = GatewayReference(
        deployment_id=deploy,
        workspace_id=w.service.workspace_id,
        connection_id=conn_id,
        alias=alias,
        remote_model_id="fixture",
        config_hash="a" * 64,
        request_id=uuid4(),
        request_fingerprint="b" * 64,
        state="ready",
        contract_profile="chat_tools_vision_v1",
    )
    manifest = litellm_logical_manifest(alias).model_copy(
        update={"id": f"litellm/{conn_id}/{alias}"}
    )
    manifest.metadata.update(
        contract_profile=ref.contract_profile, gateway_reference=ref.execution_reference()
    )

    async def response(request):
        incoming.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "已收到画面"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    registry = ModelRegistry()
    registry.register(
        manifest,
        LiteLLMModelAdapter(
            manifest,
            settings=Settings(
                app_env="test",
                litellm_gateway_url="https://synthetic.example",
                litellm_api_key="fixture",
            ),
            transport=httpx.MockTransport(response),
        ),
    )
    model = ResolvedAgentTextModel(
        manifest.id,
        {
            "model_id": manifest.id,
            "gateway_reference": ref.execution_reference(),
            "text_capabilities": {"image_input": case != "text_only"},
        },
        CapabilityTextModel(registry),
        {},
    )

    async def resolve(*_, **__):
        return model

    monkeypatch.setattr("app.director.text_transport.resolve_agent_text_model", resolve)
    async with w.factory() as session:
        project = await session.get(Project, w.service.project_id)
        actor = await session.get(User, w.service.actor_id)
        cred = EncryptedProviderCredential(
            workspace_id=project.workspace_id,
            provider="litellm",
            revision_no=1,
            ciphertext="fixture",
            key_version="v1",
        )
        session.add(cred)
        await session.flush()
        connection = ProviderConnection(
            id=conn_id,
            workspace_id=project.workspace_id,
            provider_type="litellm",
            protocol_profile="openai_chat_v1",
            display_name="fixture",
            base_url="http://proxy:4000",
            credential_id=cred.id,
            enabled=True,
            verification_status="gateway_registered",
            gateway_ref=ref.model_dump(mode="json"),
            created_by=actor.id,
            updated_by=actor.id,
        )
        dest = ProviderDestinationRevision(
            workspace_id=project.workspace_id,
            binding_ref=manifest.id,
            revision=1,
            origin_expected_revision=0,
            upstream_origin="https://upstream.example:443",
            processing_location="external",
            purposes=["director_text", "vision_input"],
            declaration_hash="e" * 64,
            configuration_hash="f" * 64,
            route_manifest={"gateway_reference": ref.execution_reference()},
            location_evidence={},
            created_by=actor.id,
        )
        art = Artifact(
            project_id=project.id,
            artifact_type="video" if case == "video" else "image",
            storage_state="available",
            object_key=stored.object_key,
            content_hash=stored.content_hash,
            mime_type=mime,
            byte_size=len(raw),
        )
        session.add_all([connection, dest, art])
        await session.flush()
        grant = await SourceUseService(session, actor=actor, project=project).declare(
            artifact_id=art.id,
            allowed_uses=["external_processing"],
            statement="本地合成样例",
            request_key="source",
        )
        if case == "local_only":
            await ProjectDataPolicy(session, actor=actor, project=project).put(
                expected_revision=0,
                mode="local_only",
                allowed_destination_revision_ids=[],
                allowed_purposes=[],
            )
        await session.commit()
    thread = await w.service.open_thread(AgentThreadCreate())
    part = {
        "kind": "artifact",
        "artifact_id": str(art.id),
        "expected_content_hash": art.content_hash,
        "transform": {"max_edge": 64, "frame_time_ms": 500}
        if case == "video"
        else {"max_edge": 64},
    }
    request = AgentRequest.model_validate(
        {"content": "请描述", "request_key": "vision-turn", "media_parts": [part]}
    )
    if case in ("text_only", "local_only"):
        with pytest.raises(ValidationAppError) as err:
            await w.service.accept(thread.id, request, model=model)
        assert err.value.details["code"] == (
            "VISION_MODEL_UNSUPPORTED" if case == "text_only" else "EGRESS_LOCAL_ONLY"
        )
        assert err.value.details["request_accepted"] is False and not incoming
        return
    receipt, new = await w.service.accept(thread.id, request, model=model)
    assert new and not incoming
    if case == "revoked":
        async with w.factory() as session:
            await SourceUseService(session, actor=actor, project=project).declare(
                artifact_id=art.id,
                state="revoked",
                allowed_uses=[],
                statement="",
                request_key="withdraw",
                expected_version=grant.result_version,
            )
            await session.commit()
    if case == "wrong_bytes":
        await store.put_bytes(object_key=stored.object_key, data=b"0" * len(raw), mime_type=mime)
    result = await execute(w, receipt, model=model)
    async with w.factory() as session:
        inv = await session.scalar(
            select(DirectorInvocation).where(DirectorInvocation.turn_id == receipt.turn_id)
        )
    if case in ("revoked", "wrong_bytes"):
        assert result.status == "failed" and not incoming and inv is None
        return
    assert result.status == "completed" and len(incoming) == 1
    content = incoming[0]["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "请描述"}
    encoded = content[1]["image_url"]["url"].split(",", 1)[1]
    png = base64.b64decode(encoded, validate=True)
    assert Image.open(io.BytesIO(png)).size == ((64, 43) if case == "video" else (64, 32))
    evidence = inv.request_snapshot["media_parts"][0]
    assert evidence["content_hash"] == hashlib.sha256(png).hexdigest()
    assert evidence["expected_content_hash"] == stored.content_hash
    assert inv.request_snapshot["source_revisions"] == [str(grant.id)]
    assert inv.request_snapshot["egress_admission"]["required_purposes"] == [
        "director_text",
        "vision_input",
    ]
    history = await w.service.read_thread(thread.id)
    assert all(row["media_parts"][0]["artifact_id"] == str(art.id) for row in history["messages"])
    assert encoded not in json.dumps(inv.request_snapshot) and encoded not in str(history)
    same, new = await w.service.accept(thread.id, request, model=model)
    assert not new and same == receipt and len(incoming) == 1
