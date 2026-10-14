"""Whole frozen model inventory is represented, with reviewed negative facts."""

from app.providers.capability_inspection import inspect_catalog_model
from app.providers.catalog_loader import ModelCatalogLoader
from app.providers.knowledge_projection import project_model_knowledge
from app.providers.manifest import read_catalog_manifest


def candidates():
    return {
        item.identity[:3]: item.as_dict()
        for item in ModelCatalogLoader().load()
        if item.as_dict().get("schema_version") == "2"
    }


def candidate(provider, model):
    return next(
        value for key, value in candidates().items() if key[0] == provider and key[2] == model
    )


def test_every_initial_scope_model_has_one_typed_candidate_and_no_new_execution():
    loaded = ModelCatalogLoader().load()
    old = {
        item.identity[:3]
        for item in loaded
        if item.identity[0] in {"agnes", "minimax", "volcengine"}
        and item.as_dict().get("schema_version", "1") == "1"
    }
    assert old == set(candidates())
    assert len(old) == 20
    for raw in candidates().values():
        report = project_model_knowledge(raw)
        assert report.implementation_status == "not_implemented"
        assert report.product_open is False and report.account_status == "not_checked"
        assert raw["lifecycle"] == "preview"
        assert "MODEL_CONTRACT_NOT_TESTED" in report.blockers


def test_minimax_modes_limits_and_model_differences_are_structured():
    h3 = read_catalog_manifest(candidate("minimax", "MiniMax-H3"))
    maximum = read_catalog_manifest(candidate("minimax", "MiniMax-H3-Max"))
    first = h3.operations["video.generate"]
    second = maximum.operations["video.generate"]
    assert first.output_options["resolution"].enum == ("768P", "2K")
    assert second.output_options["resolution"].enum == ("480P", "768P")
    assert second.output_options["prompt_expansion_mode"].enum == (
        "disabled",
        "balanced",
        "quality",
    )
    assert first.input_contracts["reference"].maximum_total_references.kind == "unknown"
    assert first.input_contracts["reference"].input_slots["reference_video"].min_fps.value == 23.976
    image = read_catalog_manifest(candidate("minimax", "image-01")).operations["image.generate"]
    assert image.prompt_spec.max_length.value == 1500
    assert (
        image.input_contracts["character"].input_slots["reference_image"].max_bytes.value
        == 10000000
    )
    assert len(image.constraints) == 2


def test_agnes_unknown_limits_and_aggregate_audio_do_not_become_unlimited():
    image = read_catalog_manifest(candidate("agnes", "agnes-image-2.5-flash")).operations[
        "image.generate"
    ]
    assert (
        image.input_contracts["reference"].input_slots["reference_image"].maximum.kind == "unknown"
    )
    assert "return_base64" not in image.output_options
    assert "return_base64" in image.input_contracts["text"].output_options
    video = read_catalog_manifest(candidate("agnes", "agnes-video-2.5")).operations[
        "video.generate"
    ]
    refs = video.input_contracts["reference"]
    assert refs.min_total_duration_seconds["reference_audio"].value == 2
    assert refs.input_slots["reference_audio"].min_duration_seconds.kind == "unknown"
    assert video.output_options["fps"].claim_status == "documented_unsupported"
    assert video.protocol_facts["1K_dimensions"].default == [1024, 1024]


def test_ark_explicit_negatives_operations_and_conditions_are_preserved():
    pro = read_catalog_manifest(candidate("volcengine", "doubao-seedream-5-0-pro-260628"))
    op = pro.operations["image.generate"]
    assert op.output_options["stream"].claim_status == "documented_unsupported"
    assert op.output_options["sequential_image_generation"].claim_status == "documented_unsupported"
    assert (
        "image.layer_decomposition" in pro.operations and "image.interactive_edit" in pro.operations
    )
    lite = read_catalog_manifest(candidate("volcengine", "doubao-seedream-5-0-lite-260128"))
    assert "3K" in lite.operations["image.generate"].output_options["size"].enum
    mini = read_catalog_manifest(candidate("volcengine", "doubao-seedance-2-0-mini-260615"))
    assert (
        mini.operations["video.generate"].input_contracts["reference"].constraints[0].kind
        == "requires_any"
    )
    assert mini.operations["video.generate"].output_options["seed"].claim_status == "conflicting"


def test_knowledge_query_does_not_replace_frozen_executable_revision():
    report = inspect_catalog_model("agnes/agnes-image-2.1-flash")
    assert report.model_revision == "v3"
    assert report.knowledge.model_revision == "knowledge-2026-10-13-r1"
    assert report.manifest_hash != report.knowledge.manifest_hash
    assert report.knowledge.product_open is False
    assert len(report.knowledge.sources) == 1
    assert report.knowledge.sources[0].status == "source_snapshot_reviewed"
    assert report.knowledge.sources[0].url.startswith("https://wiki.agnes-ai.cn/")


def test_object_protocol_literals_do_not_add_fake_claims_or_unknown_bounds():
    raw = candidate("minimax", "image-01")
    before = project_model_knowledge(raw)
    raw["operations"]["image.generate"]["protocol_facts"]["literal"] = {
        "type": "object",
        "claim_status": "unknown",
        "control": "unsupported",
        "required": False,
        "default": {"claim_status": "documented_supported", "kind": "unknown"},
        "default_status": "unknown",
    }
    after = project_model_knowledge(raw)
    assert len(after.fields) == len(before.fields) + 1
    assert after.unknown_bounds == before.unknown_bounds
    assert not any("/default" in field.path for field in after.fields)


def test_known_prompt_requirements_are_present_without_guessed_limits():
    for model in ("MiniMax-H3", "MiniMax-H3-Max"):
        prompt = (
            read_catalog_manifest(candidate("minimax", model))
            .operations["video.generate"]
            .prompt_spec
        )
        assert prompt.required is True and prompt.min_length.value == 1
        assert prompt.max_length.kind == "unknown"
    for model in (
        "agnes-image-2.1-flash",
        "agnes-image-2.5-flash",
        "agnes-video-2.5",
        "agnes-video-2.5-flash",
    ):
        for operation in read_catalog_manifest(candidate("agnes", model)).operations.values():
            assert operation.prompt_spec.required is True
            assert operation.prompt_spec.min_length.kind == "unknown"
            assert operation.prompt_spec.max_length.kind == "unknown"


def test_seedance_draft_only_allows_documented_480p_resolution():
    manifest = read_catalog_manifest(candidate("volcengine", "doubao-seedance-2-5-260628"))
    assert all(
        any(
            rule.kind == "conditional"
            and rule.when == {"draft": True}
            and rule.allowed == {"resolution": ("480p",)}
            for rule in operation.constraints
        )
        for operation in manifest.operations.values()
    )
