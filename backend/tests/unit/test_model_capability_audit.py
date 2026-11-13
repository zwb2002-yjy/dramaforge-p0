"""The offline audit must freeze facts without promoting URLs to capabilities."""

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from app.providers.catalog_loader import hash_manifest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "capability_audit", ROOT / "scripts/audit_model_capabilities.py"
)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


@pytest.fixture
def repository(tmp_path):
    target = tmp_path / "repo"
    catalog = target / "backend/app/providers/model_catalog/agnes"
    fixtures = target / "fixtures/providers/contracts"
    catalog.mkdir(parents=True)
    fixtures.mkdir(parents=True)
    source = ROOT / "fixtures/providers/contracts/agnes-image-2.1-flash.json"
    fixture = json.loads(source.read_text(encoding="utf-8"))
    (catalog / "01-image.json").write_text(json.dumps(fixture["manifest"]), encoding="utf-8")
    (fixtures / "image.json").write_text(json.dumps(fixture), encoding="utf-8")
    return target


def report(repository, date="2026-10-12", **kwargs):
    return audit.build_audit(repository, source_sha="a" * 40, checked_at=date, **kwargs)


def test_audit_does_not_promote_fixtures_or_official_urls(repository):
    result = report(repository)
    assert result["inventory"][0]["fixture_status"] == "exact_match"
    assert result["metrics"]["compiler_contracts"]["passed_by_this_audit"] is None
    assert result["metrics"]["official_evidence"]["reviewed_supported_claims"] == 0
    assert result["official_claims"] == []
    assert result["metrics"]["declared_value_mapping"]["overall_ratio"] is None
    assert {c["claim_status"] for c in result["catalog_declarations"]} == {"unknown"}
    assert all(c["source_snapshot_ref"] is None for c in result["catalog_declarations"])
    assert "implementation" not in result["catalog_declarations"][0]
    assert "compiler_fixture" not in result["catalog_declarations"][0]


def test_recheck_does_not_change_frozen_inventory_or_manifest(repository):
    first, later = report(repository), report(repository, "2026-10-13")
    assert first["inventory_sha256"] == later["inventory_sha256"]
    assert first["inventory"] == later["inventory"]
    assert first["checked_at"] != later["checked_at"]
    assert audit.compare_inventory(first, later) == {
        "added": [],
        "removed": [],
        "changed_existing_revision": [],
    }


def test_changed_frozen_revision_is_detected(repository):
    first = report(repository)
    path = repository / first["inventory"][0]["path"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["operations"]["image.generate"]["output_constraints"]["size"] = "2K"
    path.write_text(json.dumps(raw), encoding="utf-8")
    later = report(repository)
    assert later["inventory"][0]["fixture_status"] == "missing_or_ambiguous"
    assert audit.compare_inventory(first, later)["changed_existing_revision"] == [
        first["inventory"][0]["identity"]
    ]


def test_new_revision_does_not_overwrite_existing_identity(repository):
    first = report(repository)
    raw = json.loads((repository / first["inventory"][0]["path"]).read_text(encoding="utf-8"))
    raw.update(model_revision="candidate", lifecycle="preview", implementation_status="documented")
    path = repository / "backend/app/providers/model_catalog/agnes/preview/new.json"
    path.parent.mkdir()
    path.write_text(json.dumps(raw), encoding="utf-8")
    delta = audit.compare_inventory(first, report(repository))
    assert len(delta["added"]) == 1
    assert delta["changed_existing_revision"] == []


def test_null_limit_and_string_feature_are_preserved_without_unlimited_claim(repository):
    before = report(repository)
    path = repository / before["inventory"][0]["path"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["documented_features"] = ["image.edit"]
    raw["operations"]["image.generate"]["input_contracts"] = {
        "reference": {
            "input_slots": {"reference_image": {"maximum": None}},
            "maximum_total_references": None,
        }
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    result = report(repository)
    nulls = [
        c
        for c in result["catalog_declarations"]
        if c["claim_path"].endswith(("/maximum", "/maximum_total_references"))
    ]
    assert len(nulls) == 2
    assert all("unknown_unlimited_not_distinguished" in c["blocker"] for c in nulls)
    feature = next(
        c for c in result["catalog_declarations"] if c["claim_path"] == "/documented_features/0"
    )
    assert feature["schema_path"] is None and feature["representation"] == "string_feature"
    assert list(audit.leaves({"video.generate": {"@contract/a": []}}, "")) == [
        ("/video.generate/@contract~1a", [])
    ]


def test_fixture_for_another_revision_is_not_counted(repository):
    fixture = repository / "fixtures/providers/contracts/image.json"
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    raw["manifest"]["model_revision"] = "other"
    raw["manifest_hash"] = hash_manifest(raw["manifest"])
    fixture.write_text(json.dumps(raw), encoding="utf-8")
    assert report(repository)["inventory"][0]["fixture_status"] == "missing_or_ambiguous"


def test_empty_legacy_container_is_not_counted_as_typed(repository):
    first = report(repository)
    path = repository / first["inventory"][0]["path"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["operations"]["image.generate"]["output_constraints"] = {}
    path.write_text(json.dumps(raw), encoding="utf-8")
    result = report(repository)
    empty = next(
        c for c in result["catalog_declarations"] if c["claim_path"].endswith("/output_constraints")
    )
    assert empty["representation"] == "legacy_json"
    assert result["metrics"]["catalog_field_retention"]["legacy_json"] == 1


def test_ignored_raw_field_does_not_claim_a_schema_mapping(repository):
    first = report(repository)
    path = repository / first["inventory"][0]["path"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["operations"]["image.generate"]["future_capability"] = {"enabled": True}
    path.write_text(json.dumps(raw), encoding="utf-8")
    item = next(
        c
        for c in report(repository)["catalog_declarations"]
        if "/future_capability/" in c["claim_path"]
    )
    assert item["representation"] == "unmapped_schema_field"
    assert item["schema_path"] is None
    assert "typed_contract_mapping_pending" in item["blocker"]


def test_output_is_local_evidence_and_cannot_overwrite_frozen_reports(repository):
    result = report(repository)
    original = deepcopy(result)
    with pytest.raises(ValueError, match="tmp/"):
        audit.write_reports(repository, repository / "docs/reviews", result)
    observations = {"claim_status": "documented_supported"}
    output = repository / "tmp/audit"
    result = report(repository, observations=observations)
    original = deepcopy(result)
    audit.write_reports(repository, output, result)
    written = json.loads((output / audit.REPORT_NAMES[0]).read_text(encoding="utf-8"))
    assert written["metrics"] == result["metrics"]
    assert written["manual_observations"] == result["manual_observations"]
    assert result == original
    with pytest.raises(ValueError, match="already exists"):
        audit.write_reports(repository, output, result)
    assert sorted(p.name for p in output.iterdir()) == sorted(audit.REPORT_NAMES)


def test_annotation_reader_does_not_execute_python(tmp_path):
    path = tmp_path / "source.py"
    path.write_text(
        '_VIDEO = "https://official.example/video"\n'
        '_SOURCES = {"a/id": _VIDEO}\n'
        'raise RuntimeError("must never execute")\n',
        encoding="utf-8",
    )
    assert audit.annotation_urls(path) == {"a/id": "https://official.example/video"}


def _observations(repository):
    model_identity = report(repository)["inventory"][0]["identity"]
    return {
        "identified_official_claims": [
            {
                "id": "official-output",
                "identity": model_identity,
                "source_ref": "official-doc",
                "claim_status": "documented_supported",
                "value": {"size": "1K", "fps": 60, "formats": ["url", "base64"]},
                "schema_mapping": ["/operations/image.generate/output_constraints"],
                "mapping_by_value_path": {
                    "/size": ["/operations/image.generate/output_constraints/size"],
                    "/fps": ["/operations/image.generate/output_constraints/frame_rate"],
                },
            }
        ]
    }


def test_document_assertion_does_not_become_cn_contract_support(repository):
    observations = _observations(repository)
    before = deepcopy(observations)
    result = report(repository, observations=observations)
    group = result["manual_observations"]["identified_official_claims"][0]
    assert "claim_status" not in group
    assert group["source_text_status"] == "documented_supported"
    assert group["applicability_status"] == "unknown"
    assert group["contract_evidence_status"] == "unknown"
    assert {c["implementation_verification"] for c in result["official_claims"]} == {
        "not_verified_per_capability"
    }
    assert observations == before


def test_official_unmapped_facts_enter_denominator_and_enum_is_one_fact(repository):
    result = report(repository, observations=_observations(repository))
    mapping = result["metrics"]["declared_value_mapping"]
    assert mapping["total"] == 3
    assert mapping["mapped_exact_value"] == 1
    assert mapping["value_mismatch"] == 1
    assert mapping["not_assessed"] == 1
    assert mapping["overall_ratio"] is None
    assert result["metrics"]["catalog_field_retention"]["total_raw_leaves"] > 3
    assert not any("namespace" in claim["id"] for claim in result["official_claims"])


def test_new_fact_does_not_inherit_group_supported_status(repository):
    observations = _observations(repository)
    group = observations["identified_official_claims"][0]
    group["source_fact_statuses"] = {"/size": "documented_supported"}
    group["value"]["new_parameter"] = True
    result = report(repository, observations=observations)
    statuses = {
        item["value_path"]: item["source_text_status"] for item in result["official_claims"]
    }
    assert statuses["/size"] == "documented_supported"
    assert statuses["/new_parameter"] == "unknown"


def test_value_mismatch_does_not_count_as_mapped(repository):
    observations = _observations(repository)
    observations["identified_official_claims"][0]["value"]["size"] = "4K"
    result = report(repository, observations=observations)
    assert result["metrics"]["declared_value_mapping"]["mapped_exact_value"] == 0
    assert result["metrics"]["official_evidence"]["reviewed_supported_claims"] == 0


def _cached_source(tmp_path, body):
    url = "https://docs.official.example/model-list"
    candidate = hashlib.sha256(url.encode()).hexdigest()
    raw = body.encode()
    path = tmp_path / f"{candidate}.html"
    path.write_bytes(raw)
    return path, {
        "candidate_id": candidate,
        "url": url,
        "body_sha256": hashlib.sha256(raw).hexdigest(),
        "checked_at": "2026-10-12",
    }


def test_router_markdown_is_extracted_even_when_html_has_js_fallback(tmp_path):
    markdown = "# Model\nA reviewed source still needs scope and capability review."
    router = {"loaderData": {"page": {"curDoc": {"DocumentID": 1330310, "MDContent": markdown}}}}
    body = "<html><noscript>You need to enable JavaScript</noscript><script>"
    body += "window._ROUTER_DATA = " + json.dumps(router) + ";</script></html>"
    path, check = _cached_source(tmp_path, body)
    records, texts = audit.inspect_cached_sources([check], tmp_path)
    assert records[0]["extraction_status"] == "extracted_unreviewed"
    assert records[0]["locator"]["document_id"] == 1330310
    assert records[0]["review_status"] == "unreviewed"
    assert texts[check["candidate_id"]] == markdown
    assert hashlib.sha256(path.read_bytes()).hexdigest() == check["body_sha256"]


def test_script_expressions_are_never_evaluated_as_router_json(tmp_path):
    body = "<html><script>window._ROUTER_DATA = evil();</script></html>"
    _path, check = _cached_source(tmp_path, body)
    records, texts = audit.inspect_cached_sources([check], tmp_path)
    assert records[0]["extraction_status"] == "extraction_pending"
    assert records[0]["extracted_text_sha256"] is None
    assert texts == {}


def test_cached_body_hash_mismatch_is_rejected(tmp_path):
    path, check = _cached_source(tmp_path, "# Official source")
    path.write_text("different body", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        audit.inspect_cached_sources([check], tmp_path)


def test_cache_missing_body_is_unavailable_not_a_fabricated_hash(tmp_path):
    path, check = _cached_source(tmp_path, "# Official source")
    path.unlink()
    records, _ = audit.inspect_cached_sources([check], tmp_path)
    assert records[0]["extraction_status"] == "source_unavailable"
    assert records[0]["extracted_text_sha256"] is None


def test_bad_observations_do_not_leave_partial_frozen_output(repository):
    result = report(repository, observations={"invariants": [{"missing_required_fields": True}]})
    output = repository / "tmp/bad-audit"
    with pytest.raises(KeyError):
        audit.write_reports(repository, output, result)
    assert not output.exists()


def test_unassessed_mapping_is_not_reported_as_missing_or_zero_coverage(repository):
    observations = _observations(repository)
    observations["identified_official_claims"][0].pop("mapping_by_value_path")
    result = report(repository, observations=observations)
    mapping = result["metrics"]["declared_value_mapping"]
    assert mapping["not_assessed"] == 3
    assert mapping["explicitly_missing"] == mapping["value_mismatch"] == 0
    assert mapping["overall_ratio"] is None


def test_source_annotation_is_outside_capability_denominator(repository):
    observations = _observations(repository)
    group = deepcopy(observations["identified_official_claims"][0])
    group.update(
        id="guide-note",
        record_kind="source_annotation",
        value={"guide_name": "another-version", "applicability": "unknown"},
    )
    observations["identified_official_claims"].append(group)
    result = report(repository, observations=observations)
    assert len(result["source_annotations"]) == 1
    assert result["metrics"]["claim_classification"]["total"] == 3


def test_cache_extraction_supersedes_old_unavailable_note(repository):
    observations = _observations(repository)
    observations["baseline"] = {"来源与时间范围": "web reader only returned JavaScript shell"}
    observations["source_observations"] = [{"id": "official-doc", "source_candidate_ref": "a" * 64}]
    group = observations["identified_official_claims"][0]
    group.update(locator="web returned JavaScript shell", blocker="source_unavailable")
    cached = [
        {
            "candidate_id": "a" * 64,
            "extraction_status": "extracted_unreviewed",
            "extracted_text_sha256": "b" * 64,
            "locator": {"document_id": 123},
        }
    ]
    result = report(repository, observations=observations, cached_sources=cached)
    current = result["manual_observations"]["identified_official_claims"][0]
    assert current["source_extraction_status"] == "extracted_unreviewed"
    assert "source_unavailable" not in str(current)
    assert "JavaScript shell" not in str(result["manual_observations"]["baseline"])
    assert (
        result["manual_observations"]["historical_source_observations"][0]["note"]
        == "source_unavailable"
    )
