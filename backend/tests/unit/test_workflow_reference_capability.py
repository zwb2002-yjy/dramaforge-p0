"""WF6 — multi-character reference / capability gate."""

from __future__ import annotations

from uuid import uuid4

from app.director.workflows.character_participation import (
    ScreenRole,
    ShotCharacterParticipation,
    ShotParticipationPlan,
)
from app.director.workflows.reference_capability import (
    MultiCharacterCapabilityStatus,
    assess_multi_character_capability,
)
from app.production.reference_intents import ShotReferenceIntent, compile_references
from app.providers.capabilities import Capability
from app.providers.manifest import (
    CapabilitySpec,
    ConstraintSpec,
    InputSlotSpec,
    ModelManifest,
    SubmissionSemantics,
)


def _manifest(*, max_reference_images: int) -> ModelManifest:
    return ModelManifest(
        manifest_version="1",
        id="agnes/image-model",
        provider_id="agnes",
        model_name="image-model",
        display_name="Image Model",
        capability_specs={
            Capability.IMAGE_GENERATE: CapabilitySpec(
                capability=Capability.IMAGE_GENERATE,
                transport_profile_id="t1",
                input_slots={
                    "reference_image": InputSlotSpec(
                        minimum=0,
                        maximum=max_reference_images,
                        media_types=["image/*"],
                    ),
                },
                constraints=ConstraintSpec(),
            ),
        },
        execution_mode="sync",
        submission_semantics=SubmissionSemantics(),
    )


def _plan(n: int) -> ShotParticipationPlan:
    chars = [uuid4() for _ in range(n)]
    return ShotParticipationPlan(
        participations=[
            ShotCharacterParticipation(
                character_id=char,
                asset_version_id=uuid4(),
                screen_role=ScreenRole.PRIMARY if i == 0 else ScreenRole.SECONDARY,
            )
            for i, char in enumerate(chars)
        ]
    )


def test_two_character_exact_when_model_supports_two() -> None:
    assessment = assess_multi_character_capability(
        manifest=_manifest(max_reference_images=2),
        capability=Capability.IMAGE_GENERATE,
        mode_id=None,
        plan=_plan(2),
    )
    assert assessment.status == MultiCharacterCapabilityStatus.EXACT
    assert assessment.required_subject_references == 2
    assert assessment.max_subject_references == 2


def test_two_character_unsupported_when_model_supports_one() -> None:
    assessment = assess_multi_character_capability(
        manifest=_manifest(max_reference_images=1),
        capability=Capability.IMAGE_GENERATE,
        mode_id=None,
        plan=_plan(2),
    )
    assert assessment.status == MultiCharacterCapabilityStatus.UNSUPPORTED
    assert assessment.max_subject_references == 1
    assert "cannot be preserved" in assessment.reason


def test_two_character_approximate_only_with_accepted_strategy() -> None:
    assessment = assess_multi_character_capability(
        manifest=_manifest(max_reference_images=1),
        capability=Capability.IMAGE_GENERATE,
        mode_id=None,
        plan=_plan(2),
        accept_approximations=True,
        staged_strategy_id="two-pass-i2i-stabilize-v1",
    )
    assert assessment.status == MultiCharacterCapabilityStatus.APPROXIMATE
    assert assessment.approximate_strategy_id == "two-pass-i2i-stabilize-v1"


def test_two_character_not_approximate_without_accepted_strategy() -> None:
    assessment = assess_multi_character_capability(
        manifest=_manifest(max_reference_images=1),
        capability=Capability.IMAGE_GENERATE,
        mode_id=None,
        plan=_plan(2),
    )
    assert assessment.status == MultiCharacterCapabilityStatus.UNSUPPORTED


def test_reference_compiler_no_silent_primary_collapse() -> None:
    """A model that supports only one reference_image must not silently drop B."""
    manifest = _manifest(max_reference_images=1)
    references = [
        ShotReferenceIntent(purpose="identity", artifact_id=uuid4()),
        ShotReferenceIntent(purpose="identity", artifact_id=uuid4()),
    ]
    result = compile_references(
        manifest=manifest,
        capability=Capability.IMAGE_GENERATE,
        references=references,
        mode_id=None,
    )
    assert len(result.planned_references) == 2
    # The second identity reference exceeds cardinality -> unsupported, not dropped.
    deliveries = [ref.delivery for ref in result.planned_references]
    assert "unsupported" in deliveries
    assert len(result.planned_references) == 2


def test_quality_report_one_char_fail_cannot_silently_pass() -> None:
    from app.director.workflows.quality_report import (
        IdentityResultStatus,
        MultiCharacterIdentityReport,
        PerCharacterIdentityResult,
    )

    report = MultiCharacterIdentityReport(
        results=[
            PerCharacterIdentityResult(
                character_id=uuid4(),
                status=IdentityResultStatus.PASSED,
                evidence="A matches",
                rule="two-source",
            ),
            PerCharacterIdentityResult(
                character_id=uuid4(),
                status=IdentityResultStatus.FAILED,
                evidence="B drifted",
                rule="two-source",
            ),
        ],
        overall_status="blocked",
    )
    assert report.all_passed is False
    assert report.overall_status == "blocked"


def test_quality_report_forces_blocked_when_fail_and_asked_pass() -> None:
    import pytest
    from app.director.workflows.quality_report import (
        IdentityResultStatus,
        MultiCharacterIdentityReport,
        PerCharacterIdentityResult,
    )

    with pytest.raises(ValueError):
        MultiCharacterIdentityReport(
            results=[
                PerCharacterIdentityResult(
                    character_id=uuid4(),
                    status=IdentityResultStatus.FAILED,
                    evidence="B drifted",
                ),
            ],
            overall_status="passed",
        )
