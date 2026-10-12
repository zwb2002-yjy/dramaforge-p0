"""The offline audit must freeze facts without promoting URLs to capabilities."""

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


def report(repository, date="2026-10-12"):
    return audit.build_audit(repository, source_sha="a" * 40, checked_at=date)


def test_audit_does_not_promote_fixtures_or_official_urls(repository):
    result = report(repository)
    assert result["inventory"][0]["fixture_status"] == "exact_match"
    assert result["metrics"]["compiler_contracts"]["passed_by_this_audit"] is None
    assert result["metrics"]["official_evidence"]["reviewed_supported_claims"] == 0
    assert {c["claim_status"] for c in result["claims"]} == {"unknown"}
    assert all(c["source_snapshot_ref"] is None for c in result["claims"])
    assert "source_url_candidates" not in result["claims"][0]


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
        for c in result["claims"]
        if c["claim_path"].endswith(("/maximum", "/maximum_total_references"))
    ]
    assert len(nulls) == 2
    assert all("unknown_unlimited_not_distinguished" in c["blocker"] for c in nulls)
    feature = next(c for c in result["claims"] if c["claim_path"] == "/documented_features/0")
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


def test_output_is_local_evidence_and_cannot_overwrite_frozen_reports(repository):
    result = report(repository)
    original = deepcopy(result)
    with pytest.raises(ValueError, match="tmp/"):
        audit.write_reports(repository, repository / "docs/reviews", result, {})
    observations = {"claim_status": "documented_supported"}
    output = repository / "tmp/audit"
    audit.write_reports(repository, output, result, observations)
    written = json.loads((output / audit.REPORT_NAMES[0]).read_text(encoding="utf-8"))
    assert written["metrics"] == result["metrics"]
    assert written["manual_observations"] == observations
    assert result == original
    with pytest.raises(ValueError, match="already exists"):
        audit.write_reports(repository, output, result, {})
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
