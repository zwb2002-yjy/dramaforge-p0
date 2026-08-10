"""Shared eligibility engine tests (single implementation for candidates + runtime)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.eligibility import (
    IMAGE_GENERATE,
    VIDEO_GENERATE,
    evaluate_candidate,
)
from app.providers.models import ProviderConnection, ProviderModelBinding


def _connection(*, enabled: bool = True) -> ProviderConnection:
    return ProviderConnection(
        id=uuid4(),
        workspace_id=uuid4(),
        provider_type="agnes",
        display_name="Agnes",
        base_url="https://api.agnes-ai.cn",
        protocol_profile="agnes_cn_v1",
        credential_id=uuid4(),
        credential_revision=1,
        enabled=enabled,
        verification_status="verified",
        created_by=uuid4(),
        updated_by=uuid4(),
    )


def _binding(
    *,
    documented: bool = True,
    contract_tested: bool = True,
    account_verified: bool = True,
    quality_gated: bool = True,
    enabled: bool = True,
) -> ProviderModelBinding:
    return ProviderModelBinding(
        id=uuid4(),
        workspace_id=uuid4(),
        connection_id=uuid4(),
        media_type="video",
        model_id="agnes-video-v2.0",
        purpose="video",
        enabled=enabled,
        documented=documented,
        contract_tested=contract_tested,
        account_verified=account_verified,
        quality_gated=quality_gated,
        created_by=uuid4(),
        updated_by=uuid4(),
    )


def _agnes_video_entry() -> ModelCatalogEntry:
    return ModelCatalogEntry(
        id=uuid4(),
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-video-v2.0",
        model_revision="v1",
        display_name="Agnes Video",
        media_kind="video",
        lifecycle="active",
        catalog_source="official_static",
        capability_manifest_json={
            "operations": {
                VIDEO_GENERATE: {
                    "operation": VIDEO_GENERATE,
                    "capabilities": ["video.i2v"],
                    "output_constraints": {},
                    "reference_constraints": {
                        "first_frame": {"min": 1, "max": 1},
                        "last_frame": {"min": 0, "max": 0},
                    },
                    "exclusive_groups": [
                        {
                            "name": "frame_endpoints_vs_multimodal_references",
                            "members": [
                                ["first_frame", "last_frame"],
                                ["reference_image", "reference_video", "reference_audio"],
                            ],
                        }
                    ],
                }
            }
        },
        option_schema_json={},
        contract_manifest_hash="a" * 64,
    )


@pytest.mark.asyncio
async def test_fully_verified_candidate_is_eligible() -> None:
    binding = _binding()
    evaluation = await evaluate_candidate(
        object(),
        binding=binding,
        connection=_connection(),
        catalog_entry=_agnes_video_entry(),
        operation=VIDEO_GENERATE,
        required_capabilities=frozenset({"video.i2v"}),
        reference_roles=frozenset({"first_frame"}),
        preferred_capabilities=frozenset({"video.audio.generate"}),
    )
    assert evaluation.eligible is True
    assert evaluation.issues == []
    assert "video.i2v" in evaluation.supported_capabilities
    assert evaluation.unmet_preferences == ["video.audio.generate"]
    assert evaluation.evidence == {
        "documented": True,
        "contract_tested": True,
        "account_verified": True,
        "quality_gated": True,
    }


@pytest.mark.asyncio
async def test_unverified_model_is_ineligible_with_code() -> None:
    evaluation = await evaluate_candidate(
        object(),
        binding=_binding(account_verified=False, quality_gated=False),
        connection=_connection(),
        catalog_entry=_agnes_video_entry(),
        operation=VIDEO_GENERATE,
    )
    assert evaluation.eligible is False
    codes = {issue.code for issue in evaluation.issues}
    assert {"MODEL_NOT_ACCOUNT_VERIFIED", "MODEL_QUALITY_GATE_MISSING"} <= codes


@pytest.mark.asyncio
async def test_disabled_binding_and_connection_are_ineligible() -> None:
    evaluation = await evaluate_candidate(
        object(),
        binding=_binding(enabled=False),
        connection=_connection(enabled=False),
        catalog_entry=_agnes_video_entry(),
        operation=VIDEO_GENERATE,
    )
    assert evaluation.eligible is False
    codes = {issue.code for issue in evaluation.issues}
    assert {"MODEL_BINDING_DISABLED", "PROVIDER_CONNECTION_DISABLED"} <= codes


@pytest.mark.asyncio
async def test_required_capability_missing_is_ineligible() -> None:
    evaluation = await evaluate_candidate(
        object(),
        binding=_binding(),
        connection=_connection(),
        catalog_entry=_agnes_video_entry(),
        operation=VIDEO_GENERATE,
        required_capabilities=frozenset({"video.i2v.last_frame"}),
    )
    assert evaluation.eligible is False
    assert any(
        issue.code == "CAPABILITY_REQUIRED_MISSING"
        and issue.detail == "video.i2v.last_frame"
        for issue in evaluation.issues
    )


@pytest.mark.asyncio
async def test_reference_role_above_constraint_is_ineligible() -> None:
    evaluation = await evaluate_candidate(
        object(),
        binding=_binding(),
        connection=_connection(),
        catalog_entry=_agnes_video_entry(),
        operation=VIDEO_GENERATE,
        reference_roles=frozenset({"last_frame"}),
    )
    assert evaluation.eligible is False
    assert any(
        issue.code == "CAPABILITY_REQUIRED_MISSING"
        and "last_frame" in issue.detail
        for issue in evaluation.issues
    )


@pytest.mark.asyncio
async def test_exclusive_group_conflict_is_ineligible() -> None:
    evaluation = await evaluate_candidate(
        object(),
        binding=_binding(),
        connection=_connection(),
        catalog_entry=_agnes_video_entry(),
        operation=VIDEO_GENERATE,
        reference_roles=frozenset({"first_frame", "reference_image"}),
    )
    assert evaluation.eligible is False
    assert any(
        issue.code == "REFERENCE_MODE_CONFLICT"
        and issue.detail == "frame_endpoints_vs_multimodal_references"
        for issue in evaluation.issues
    )


@pytest.mark.asyncio
async def test_unknown_operation_is_ineligible() -> None:
    evaluation = await evaluate_candidate(
        object(),
        binding=_binding(),
        connection=_connection(),
        catalog_entry=_agnes_video_entry(),
        operation=IMAGE_GENERATE,
    )
    assert evaluation.eligible is False
    assert any(issue.code == "CAPABILITY_REQUIRED_MISSING" for issue in evaluation.issues)


@pytest.mark.asyncio
async def test_missing_catalog_entry_is_ineligible_fail_closed() -> None:
    evaluation = await evaluate_candidate(
        object(),
        binding=_binding(),
        connection=_connection(),
        catalog_entry=None,
        operation=VIDEO_GENERATE,
    )
    assert evaluation.eligible is False
    assert any(issue.code == "CAPABILITY_REQUIRED_MISSING" for issue in evaluation.issues)
