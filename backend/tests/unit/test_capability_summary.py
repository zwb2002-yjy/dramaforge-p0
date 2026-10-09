"""Provider truth and current Workbench openness are reported separately."""

from __future__ import annotations

from copy import deepcopy

from app.providers.capability_summary import summarize_model_capability
from app.providers.catalog_loader import CATALOG_MODELS
from app.providers.manifest import ModelCapabilityManifest


def _mark_tested(source: dict[str, object]) -> None:
    source["implementation_status"] = "contract_tested"
    source["evidence"] = {
        "contract": {
            "source_type": "contract_fixture",
            "source_url": "https://example.invalid/synthetic-contract-fixture",
            "checked_at": "2026-09-29",
        }
    }


def test_frozen_h3_reports_only_its_declared_first_frame() -> None:
    source = next(item for item in CATALOG_MODELS if item["model_id"] == "MiniMax-H3")
    summary = summarize_model_capability(ModelCapabilityManifest.model_validate(source))
    assert summary.accepts["first_frame"] is True
    assert summary.accepts["reference_video"] is False
    assert summary.product_open["first_frame"] is True
    assert summary.product_text_only is False


def test_new_h3_reference_capability_stays_closed_in_formal_mainchain() -> None:
    source = next(item for item in CATALOG_MODELS if item["model_id"] == "MiniMax-H3")
    revised = deepcopy(source)
    _mark_tested(revised)
    operation = revised["operations"]["video.generate"]
    operation["input_contracts"] = {
        "frame": {
            "input_slots": {"first_frame": {"minimum": 1, "maximum": 1}},
            "minimum_total_references": 1,
        },
        "reference": {
            "input_slots": {"reference_video": {"maximum": 3}},
            "minimum_total_references": 1,
        },
    }
    summary = summarize_model_capability(ModelCapabilityManifest.model_validate(revised))
    assert summary.accepts["reference_video"] is True
    assert summary.limits["reference_video"] == 3
    assert summary.product_open["reference_video"] is False
    assert summary.product_open["first_frame"] is True

    operation["input_contracts"]["duplicate_frame"] = operation["input_contracts"]["frame"]
    ambiguous = summarize_model_capability(ModelCapabilityManifest.model_validate(revised))
    assert ambiguous.accepts["first_frame"] is True
    assert ambiguous.product_open["first_frame"] is False


def test_image_text_and_reference_contracts_are_separate() -> None:
    source = next(item for item in CATALOG_MODELS if item["model_id"] == "image-01")
    revised = deepcopy(source)
    _mark_tested(revised)
    operation = revised["operations"]["image.generate"]
    operation["input_contracts"] = {
        "text": {"maximum_total_references": 0},
        "reference": {
            "input_slots": {"reference_image": {"minimum": 1, "maximum": 1}},
            "minimum_total_references": 1,
        },
    }
    summary = summarize_model_capability(ModelCapabilityManifest.model_validate(revised))
    assert summary.accepts_text_only is True
    assert summary.product_text_only is True
    assert summary.product_open["reference_image"] is True

    revised["lifecycle"] = "preview"
    revised["implementation_status"] = "documented"
    preview = summarize_model_capability(ModelCapabilityManifest.model_validate(revised))
    assert preview.accepts["reference_image"] is True
    assert preview.product_open["reference_image"] is False
    assert preview.product_text_only is False
