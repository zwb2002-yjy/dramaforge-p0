"""A reviewed candidate never qualifies its different frozen executable revision."""

from uuid import uuid4

from app.providers.capability_inspection import inspect_catalog_model
from app.providers.capability_summary import summarize_model_capability
from app.providers.catalog_loader import ModelCatalogLoader
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_publication import catalog_new_create_blocker
from app.providers.eligibility import evaluate_candidate
from app.providers.manifest import read_catalog_manifest
from app.providers.model_resolution import ExecutionModelResolver, _ConcreteBinding
from app.providers.models import ProviderConnection, ProviderModelBinding


async def test_management_resolution_and_submit_permission_agree_without_fallback():
    item = next(
        item
        for item in ModelCatalogLoader().load()
        if item.identity[2:] == ("agnes-image-2.1-flash", "v3")
    )
    entry = ModelCatalogEntry(
        id=uuid4(),
        provider_type=item.identity[0],
        protocol_profile=item.identity[1],
        model_id=item.identity[2],
        model_revision=item.identity[3],
        media_kind="image",
        lifecycle="active",
        catalog_source="official_static",
        capability_manifest_json=item.as_dict(),
        contract_manifest_hash=item.manifest_hash,
    )
    connection = ProviderConnection(
        id=uuid4(),
        workspace_id=uuid4(),
        provider_type=entry.provider_type,
        protocol_profile=entry.protocol_profile,
        enabled=True,
    )
    binding = ProviderModelBinding(
        id=uuid4(),
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        catalog_entry_id=entry.id,
        model_id=entry.model_id,
        media_type="image",
        purpose="keyframe",
        invoke_model_value=entry.model_id,
        capability_manifest_hash=item.manifest_hash,
        enabled=True,
        documented=True,
        contract_tested=True,
        account_verified=True,
        quality_gated=True,
    )
    evaluation = await evaluate_candidate(
        object(),
        binding=binding,
        connection=connection,
        catalog_entry=entry,
        operation="image.generate",
    )
    assert not evaluation.eligible
    assert [issue.code for issue in evaluation.issues] == ["MODEL_OFFICIAL_EVIDENCE_GAP"]
    from app.providers.capabilities import Capability

    resolution = ExecutionModelResolver(object())._resolution_for(
        concrete=_ConcreteBinding(binding=binding, connection=connection, catalog_entry=entry),
        requested_model_id=f"{entry.provider_type}/{entry.model_id}",
        source="request_override",
        capability=Capability.IMAGE_GENERATE,
        mode_id=None,
        native_options={},
    )
    assert resolution.status == "UNAVAILABLE" and resolution.reason == "MODEL_OFFICIAL_EVIDENCE_GAP"
    assert resolution.provider_model_binding_id == binding.id
    assert (
        resolution.catalog_entry_id == entry.id and resolution.manifest_hash == item.manifest_hash
    )
    report = inspect_catalog_model(f"{entry.provider_type}/{entry.model_id}")
    assert report.knowledge.official_supported_fields > 0
    assert report.new_create_blocker == "MODEL_OFFICIAL_EVIDENCE_GAP"
    blocker = catalog_new_create_blocker(*item.identity, item.manifest_hash)
    summary = summarize_model_capability(
        read_catalog_manifest(item.as_dict()), new_create_blocker=blocker
    )
    assert not summary.product_text_only and not any(summary.product_open.values())
    assert entry.lifecycle == "active" and binding.enabled
    entry.contract_manifest_hash = binding.capability_manifest_hash = "b" * 64
    tampered = await evaluate_candidate(
        object(),
        binding=binding,
        connection=connection,
        catalog_entry=entry,
        operation="image.generate",
    )
    assert not tampered.eligible
    assert [issue.code for issue in tampered.issues] == ["CATALOG_MANIFEST_HASH_MISMATCH"]


def test_a_typed_candidate_or_unknown_schema_cannot_inherit_old_execution_qualification():
    assert (
        catalog_new_create_blocker(
            "example", "example_v1", "fictional", "r1", "a" * 64, schema_version="2"
        )
        == "MODEL_CONTRACT_NOT_TESTED"
    )
    assert (
        catalog_new_create_blocker(
            "example", "example_v1", "fictional", "r1", "a" * 64, schema_version="99"
        )
        == "MODEL_CONTRACT_SCHEMA_UNSUPPORTED"
    )


def test_retired_and_protocol_contracts_report_product_closed_without_changing_frozen_facts():
    loaded = ModelCatalogLoader().load()
    for model_id, reason in (
        ("agnes-video-v2.0", "MODEL_LIFECYCLE_INACTIVE"),
        ("@contract/agnes-video-openai-async-v2", "DYNAMIC_MODEL_CAPABILITY_UNVERIFIED"),
    ):
        item = next(
            item
            for item in loaded
            if item.identity[2] == model_id and item.as_dict().get("schema_version", "1") == "1"
        )
        raw = item.as_dict()
        assert raw["lifecycle"] == "active"
        blocker = catalog_new_create_blocker(
            *item.identity,
            item.manifest_hash,
            lifecycle=item.publication_lifecycle,
            catalog_source=raw["catalog_source"],
        )
        assert blocker == reason
        summary = summarize_model_capability(read_catalog_manifest(raw), new_create_blocker=blocker)
        assert not any(summary.product_open.values()) and not summary.product_text_only


async def test_plugin_api_projects_retirement_and_protocol_blocks(monkeypatch):
    from types import SimpleNamespace

    from app.api.v1.provider_connections import list_provider_plugins
    from app.providers.bootstrap import build_v3_registry
    from app.providers.catalog_service import ModelCatalogService

    build_v3_registry()
    entries = []
    for item in ModelCatalogLoader().load():
        raw = item.as_dict()
        if (
            item.identity[2] not in {"agnes-video-v2.0", "@contract/agnes-video-openai-async-v2"}
            or raw.get("schema_version", "1") != "1"
        ):
            continue
        entries.append(
            SimpleNamespace(
                id=uuid4(),
                provider_type=item.identity[0],
                protocol_profile=item.identity[1],
                model_id=item.identity[2],
                model_revision=item.identity[3],
                display_name=raw["display_name"],
                media_kind=raw["media_kind"],
                lifecycle=raw["lifecycle"],
                catalog_source=raw["catalog_source"],
                contract_manifest_hash=item.manifest_hash,
                capability_manifest_json=raw,
                option_schema_json={},
            )
        )

    async def list_entries(self):
        return entries

    monkeypatch.setattr(ModelCatalogService, "list_entries", list_entries)
    plugins = await list_provider_plugins(object())
    models = [model for plugin in plugins for model in plugin.models]
    assert len(models) == 2
    assert all(
        model.new_create_blocker and not any(model.capability_summary.product_open.values())
        for model in models
    )
    assert (
        next(model for model in models if model.model_id == "agnes-video-v2.0").lifecycle
        == "retired"
    )


async def test_model_list_keeps_connection_facts_but_blocks_activation_for_evidence_gap(
    monkeypatch,
):
    from types import SimpleNamespace

    from app.api.v1.generations import list_models
    from app.providers.litellm_gateway import workspace_registry
    from app.providers.manifest import to_v3_model_manifest
    from app.providers.registry import ModelRegistry

    item = next(
        item
        for item in ModelCatalogLoader().load()
        if item.identity[2:] == ("agnes-image-2.1-flash", "v3")
    )
    manifest = to_v3_model_manifest(
        read_catalog_manifest(item.as_dict()), transport_profile_id="inspection"
    )
    manifest.metadata.update(
        binding_id=str(uuid4()),
        account_verified=True,
        new_create_blocker=catalog_new_create_blocker(*item.identity, item.manifest_hash),
    )
    registry = ModelRegistry()
    registry.register(manifest)

    async def workspace_model_registry(*args, **kwargs):
        return registry

    monkeypatch.setattr(workspace_registry, "workspace_model_registry", workspace_model_registry)
    (model,) = await list_models(
        SimpleNamespace(id=uuid4()),
        object(),
        SimpleNamespace(litellm_gateway_url="", litellm_api_key=""),
    )
    assert model.configured and not model.available
    assert model.availability_reason == "MODEL_OFFICIAL_EVIDENCE_GAP"
