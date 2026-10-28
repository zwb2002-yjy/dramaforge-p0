"""Profile defaults must reach the same frozen plan as saved Shot settings."""

import pytest
from app.production.workbench_execution import WorkbenchExecutionService
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.model_profiles.slots import ModelSlot
from tests.unit.test_workbench_execution import (
    _input,
    _seed,
    _seed_video_shot,
    _video_manifest_with_contract,
    session,
)

__all__ = ["session"]


@pytest.mark.parametrize(
    "options,mode,code",
    [
        ({"fps": 24}, "first_frame", "MODEL_OPTION_NOT_IMPLEMENTED"),
        ({}, "first_fram", "MODEL_INPUT_MODE_UNSUPPORTED"),
    ],
)
async def test_uncompilable_saved_option_or_unknown_mode_is_rejected_before_queue(
    session,
    options,
    mode,
    code,
):
    from app.production.workbench_execution import WorkbenchExecutionError

    project, binding, user = await _seed(session, manifest_override=_video_manifest_with_contract())
    shot, _ = await _seed_video_shot(session, project=project, user=user)
    shot.director_state = {"generation_settings": {"video": {"native_options": options}}}
    await session.flush()
    with pytest.raises(WorkbenchExecutionError) as error:
        await WorkbenchExecutionService(session, user_id=user.id).build_plan(
            project=project,
            execution_input=_input(
                project_id=project.id,
                shot_id=shot.id,
                requested_binding_id=binding.id,
                mode_id=mode,
            ),
        )
    assert error.value.details["code"] == code


async def test_contract_without_legal_default_never_guesses_five_seconds(session):
    from app.production.workbench_execution import WorkbenchExecutionError

    manifest = _video_manifest_with_contract()
    manifest["operations"]["video.generate"]["input_contracts"]["image_to_video"]["common_options"][
        "duration_seconds"
    ].pop("default")
    project, binding, user = await _seed(session, manifest_override=manifest)
    shot, _ = await _seed_video_shot(session, project=project, user=user)
    with pytest.raises(WorkbenchExecutionError) as error:
        await WorkbenchExecutionService(session, user_id=user.id).build_plan(
            project=project,
            execution_input=_input(
                project_id=project.id,
                shot_id=shot.id,
                requested_binding_id=binding.id,
            ),
        )
    assert error.value.details["code"] == "MODEL_DURATION_REQUIRED"


@pytest.mark.parametrize("project_default", [False, True])
async def test_saved_profile_duration_enters_plan_and_shot_can_override_or_clear(
    session,
    project_default,
):
    project, binding, user = await _seed(session, manifest_override=_video_manifest_with_contract())
    shot, _ = await _seed_video_shot(session, project=project, user=user)
    profile = ProductionModelProfile(
        workspace_id=project.workspace_id,
        project_id=project.id if project_default else None,
        name="saved generation defaults",
        version=1,
        is_default=not project_default,
        bindings={
            ModelSlot.VIDEO_SHOT.value: {
                "slot": ModelSlot.VIDEO_SHOT.value,
                "model_id": "agnes/unit-agnes-video",
                "native_options": {"duration_seconds": 4},
                "enabled": True,
            }
        },
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(profile)
    await session.flush()
    service = WorkbenchExecutionService(session, user_id=user.id)
    request = _input(project_id=project.id, shot_id=shot.id, requested_binding_id=None)
    inherited = await service.build_plan(project=project, execution_input=request)
    assert inherited.duration_seconds == 4
    assert inherited.effective_options["duration_seconds"] == 4
    assert inherited.option_sources["duration_seconds"] == (
        "project_profile" if project_default else "workspace_profile"
    )
    shot.director_state = {
        "generation_settings": {
            "video": {
                "common_options": {"duration_seconds": 5},
            }
        }
    }
    await session.flush()
    overridden = await service.build_plan(project=project, execution_input=request)
    assert overridden.duration_seconds == 5
    assert overridden.option_sources["duration_seconds"] == "shot_common"
    assert overridden.plan_fingerprint != inherited.plan_fingerprint
    shot.director_state = {
        "generation_settings": {
            "video": {
                "common_options": {"duration_seconds": None},
            }
        }
    }
    await session.flush()
    cleared = await service.build_plan(project=project, execution_input=request)
    assert cleared.duration_seconds == 4
    assert profile.bindings[ModelSlot.VIDEO_SHOT.value]["native_options"] == {"duration_seconds": 4}


async def test_diagnostic_and_execution_preview_compile_identical_saved_eight_second_profile(
    session,
):
    from app.production.model_inspection import ModelInspectionService

    manifest = _video_manifest_with_contract()
    contract = manifest["operations"]["video.generate"]["input_contracts"]["image_to_video"]
    contract["common_options"]["duration_seconds"] = {"type": "integer", "enum": [8], "default": 8}
    project, binding, user = await _seed(session, manifest_override=manifest)
    shot, _ = await _seed_video_shot(session, project=project, user=user)
    session.add(
        ProductionModelProfile(
            workspace_id=project.workspace_id,
            project_id=project.id,
            name="eight second profile",
            version=1,
            is_default=False,
            bindings={
                ModelSlot.VIDEO_SHOT.value: {
                    "slot": ModelSlot.VIDEO_SHOT.value,
                    "model_id": f"binding:{binding.id}",
                    "native_options": {"duration_seconds": 8, "resolution": "720p"},
                    "enabled": True,
                }
            },
            created_by=user.id,
            updated_by=user.id,
        )
    )
    await session.commit()
    request = _input(
        project_id=project.id,
        shot_id=shot.id,
        requested_binding_id=None,
        expected_shot_version=shot.version,
        mode_id="first_frame",
    )
    service = WorkbenchExecutionService(session, user_id=user.id)
    plan = await service.build_plan(project=project, execution_input=request)
    execution = await service.preview_compiler_contract(project=project, plan=plan)
    diagnostic = await ModelInspectionService(session, actor=user).preview_generation_compile(
        project_id=project.id,
        request=request,
    )
    assert execution is not None
    assert execution.readiness == "contract_validated"
    assert diagnostic.plan_fingerprint == plan.plan_fingerprint
    assert diagnostic.compilation.model_dump(exclude={"redacted_wire"}) == execution.model_dump(
        exclude={"redacted_wire"}
    )
    assert execution.redacted_wire["wire_request"]["seconds"] == "8"
    assert execution.redacted_wire["wire_request"]["size"] == "720p"
