"""Four fixed-input creative contrasts captured at the actual Provider HTTP boundary.

Only Mock Transport is used. Its identical placeholder outputs cannot establish
visual quality; real output comparison remains an independent Owner acceptance.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import httpx
from app.assets.models import Shot
from app.config import Settings
from app.director.creative_capabilities.creative_compiler import CreativeCapabilityCompiler
from app.director.creative_capabilities.freeze import freeze_shot_capabilities
from app.director.creative_capabilities.packs_library import STYLE_PACKS
from app.director.creative_capabilities.skill_library import BASELINE_SKILLS
from app.execution.media_submission import prepare_media_submission
from app.production.workbench_execution import WorkbenchExecutionService
from app.providers.agnes import AgnesImageCompiler, AgnesRuntime
from app.providers.models import ProviderConnection
from app.providers.runtime import ProviderRuntimeResolver, ResolvedRuntime
from test_prompt_mentions_execution import _setup
from tests.unit.test_workbench_execution import session as session


async def test_four_creative_inputs_reach_distinct_frozen_provider_requests(
    session, monkeypatch, record_property
):
    project, user, original, binding, entry, base, _bindings, _assets, _blobs = await _setup(
        session, count=0
    )
    fixed_prompt = "A traveller pauses at a rainy station doorway, medium shot, readable expression"
    style = next(item for item in STYLE_PACKS if item.style_key == "cinematic_realism_v1")
    skill = next(item for item in BASELINE_SKILLS if item.skill_key == "emotional-performance-v1")
    compiler = CreativeCapabilityCompiler()
    contrasts = [
        ("baseline", compiler.compile()),
        ("style", compiler.compile(style=style)),
        ("skill", compiler.compile(skill_stack=[skill])),
        (
            "accepted_local_director",
            compiler.compile(
                accepted_proposal={
                    "lighting": "Only blue practical light from the platform, face kept readable"
                }
            ),
        ),
    ]
    captured: list[dict[str, object]] = []

    def receive(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200, json={"data": [{"url": "https://mock-output.invalid/placeholder.png"}]}
        )

    runtime = AgnesRuntime(
        settings=Settings(agnes_enabled=True, agnes_api_key="isolated-mock-key"),
        transport=httpx.MockTransport(receive),
    )
    connection = await session.get(ProviderConnection, binding.connection_id)
    resolved = ResolvedRuntime(
        runtime=runtime,
        image_compiler=AgnesImageCompiler(),
        video_compiler=None,
        connection=connection,
        binding=binding,
        catalog_entry=entry,
        model_id=binding.model_id,
        invoke_model_value=binding.invoke_model_value,
        manifest_hash=entry.contract_manifest_hash,
    )

    async def resolve(_self, **kwargs):
        assert kwargs["workspace_id"] == project.workspace_id
        return resolved

    monkeypatch.setattr(ProviderRuntimeResolver, "resolve_runtime_for_resolution", resolve)
    monkeypatch.setattr(ProviderRuntimeResolver, "resolve_runtime_for_identity", resolve)

    class NoReferences:
        async def get_bytes(self, *, object_key):
            raise AssertionError("The fixed comparison does not resolve any media references")

    evidence = []
    identities = []
    for index, (name, intent) in enumerate(contrasts):
        shot = Shot(
            project_id=project.id,
            scene_id=original.scene_id,
            shot_number=index + 10,
            sort_order=index,
            shot_type="medium",
            camera_move="static",
            visual_description=fixed_prompt,
            image_prompt=fixed_prompt,
            dialogue="",
            video_prompt="",
            status="draft",
            director_state={},
        )
        session.add(shot)
        await session.flush()
        await freeze_shot_capabilities(
            session, project_id=project.id, shot_id=shot.id, intent=intent, actor_id=user.id
        )
        command = base.model_copy(
            update={
                "shot_id": shot.id,
                "prompt": fixed_prompt,
                "expected_shot_version": shot.version,
            }
        )
        service = WorkbenchExecutionService(session, user_id=user.id)
        plan = await service.build_plan(project=project, execution_input=command)
        run = await service.create_and_dispatch(
            project=project, execution_input=command, prepared_plan=plan
        )
        # Edits after acceptance must not replace the creative intent the Worker consumes.
        shot.director_state = {
            "creative_capabilities": {"effective_values": {"lighting": "later mutation"}}
        }
        await session.flush()
        prepared = await prepare_media_submission(
            session,
            project=project,
            run=run,
            node_type="keyframe",
            snap=dict(run.input_snapshot),
            obj_store=NoReferences(),
            prompt=plan.prompt,
            canonical_image_bytes=None,
            has_canonical_binding=False,
            canonical_artifact=None,
            frozen_identity=None,
            workbench_plan=plan,
            op=None,
            now=datetime.now(UTC),
        )
        await prepared.runtime.submit_image(prepared.compiled)
        body = captured[-1]
        assert body["prompt"] == plan.prompt
        assert fixed_prompt in str(body["prompt"])
        assert "later mutation" not in str(body["prompt"])
        identities.append(prepared.identity_json)
        evidence.append(
            {
                "case": name,
                "prompt": body["prompt"],
                "body_sha256": hashlib.sha256(
                    json.dumps(body, sort_keys=True).encode()
                ).hexdigest(),
                "plan_fingerprint": plan.plan_fingerprint,
                "creative_provenance": plan.semantic_intent.get("creative_snapshot_hashes"),
            }
        )
    prompts = [str(body["prompt"]) for body in captured]
    assert len(captured) == 4 and len(set(prompts)) == 4
    assert style.lighting in prompts[1] and style.lighting not in prompts[0]
    assert skill.strategy in prompts[2] and skill.strategy not in prompts[0]
    assert "Only blue practical light" in prompts[3]
    stripped = [{key: value for key, value in body.items() if key != "prompt"} for body in captured]
    assert stripped == [stripped[0]] * 4
    stable_model_fields = (
        "provider_model_binding_id",
        "resolved_model",
        "invoke_model_value",
        "manifest_hash",
        "connection_id",
        "connection_revision_id",
        "credential_revision_id",
    )
    assert [{key: identity[key] for key in stable_model_fields} for identity in identities] == [
        {key: identities[0][key] for key in stable_model_fields}
    ] * 4
    record_property(
        "creative_request_contrasts",
        json.dumps(
            {
                "fixed_input": fixed_prompt,
                "cases": evidence,
                "mock_http_calls": 4,
                "paid_provider_creates": 0,
                "visual_quality": "not evaluated; placeholder output is identical",
            },
            ensure_ascii=False,
        ),
    )
