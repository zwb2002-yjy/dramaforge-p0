"""Saved Profile and Shot options must resolve before preview or queueing."""

import pytest
from app.providers.effective_options import resolve_generation_options
from app.providers.manifest import ParameterSpec
from app.shared.errors import ValidationAppError


def _declared() -> dict[str, ParameterSpec]:
    return {
        "seed": ParameterSpec(type="integer", default=7, minimum=0),
        "generate_audio": ParameterSpec(type="boolean", default=True),
        "resolution": ParameterSpec(type="string", enum=["720p", "1080p"]),
    }


def test_profile_then_shot_override_and_null_inheritance_preserve_zero_and_false() -> None:
    options = resolve_generation_options(
        declared=_declared(),
        profile_options={"seed": 42, "generate_audio": True, "resolution": "720p"},
        profile_source="project_profile",
        common_options={"seed": 0, "generate_audio": False},
        native_options={"resolution": None},
    )
    assert options.values == {"seed": 0, "generate_audio": False, "resolution": "720p"}
    assert options.sources == {
        "seed": "shot_common",
        "generate_audio": "shot_common",
        "resolution": "project_profile",
    }
    assert options.requested["project_profile"]["seed"] == 42
    inherited = resolve_generation_options(
        declared=_declared(),
        profile_options={"seed": 42},
        profile_source="workspace_profile",
        common_options={"seed": None},
        native_options={},
    )
    assert inherited.values["seed"] == 42
    assert inherited.sources["seed"] == "workspace_profile"
    assert inherited.values["generate_audio"] is True
    assert inherited.sources["generate_audio"] == "contract_default"


@pytest.mark.parametrize(
    "profile, common, native, code",
    [
        ({"unknown": 1}, {}, {}, "MODEL_OPTION_UNDECLARED"),
        ({"seed": -1}, {}, {}, "MODEL_OPTION_INVALID"),
        ({}, {"seed": 0}, {"seed": 1}, "MODEL_OPTION_CONFLICT"),
        ({}, {"seed": False}, {"seed": 0}, "MODEL_OPTION_CONFLICT"),
        ({}, {}, {"resolution": "4k"}, "MODEL_OPTION_INVALID"),
    ],
)
def test_invalid_or_conflicting_options_fail_closed(profile, common, native, code) -> None:
    with pytest.raises(ValidationAppError) as error:
        resolve_generation_options(
            declared=_declared(),
            profile_options=profile,
            profile_source="project_profile",
            common_options=common,
            native_options=native,
        )
    assert error.value.details["code"] == code


def test_duration_aliases_have_one_priority_and_conflict_within_a_layer() -> None:
    declared = {"duration_seconds": ParameterSpec(type="integer", enum=[4, 8], default=4)}
    selected = resolve_generation_options(
        declared=declared,
        profile_options={"duration_seconds": 4},
        profile_source="workspace_profile",
        common_options={"duration": 8},
        native_options={},
    )
    assert selected.values == {"duration_seconds": 8}
    assert selected.sources["duration_seconds"] == "shot_common"
    assert selected.requested["shot_common"] == {"duration": 8}
    with pytest.raises(ValidationAppError) as error:
        resolve_generation_options(
            declared=declared,
            profile_options={"duration_seconds": 4, "duration": 8},
            profile_source="project_profile",
            common_options={},
            native_options={},
        )
    assert error.value.details["code"] == "MODEL_OPTION_CONFLICT"
