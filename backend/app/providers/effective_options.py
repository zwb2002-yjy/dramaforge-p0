"""One pure merge of declared defaults, selected Profile and saved Shot values."""

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import JsonValue, TypeAdapter

from app.providers.errors import ProviderError
from app.providers.manifest import ParameterSpec
from app.providers.validator import validate_parameter
from app.shared.errors import ValidationAppError

_JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


@dataclass(frozen=True)
class EffectiveGenerationOptions:
    values: dict[str, JsonValue]
    sources: dict[str, str]
    requested: dict[str, dict[str, JsonValue]]


def resolve_generation_options(
    *,
    declared: Mapping[str, ParameterSpec],
    profile_options: Mapping[str, object],
    profile_source: str,
    common_options: Mapping[str, object],
    native_options: Mapping[str, object],
    allowed_options: frozenset[str] | None = None,
) -> EffectiveGenerationOptions:
    """Missing/null inherits; explicit zero/false never means missing.

    Every explicit layer is validated, including overridden stale Profile input.
    A common/native duplicate at Shot level must agree in both type and value.
    This validates declarations; actual compiler support is a separate gate.
    """
    raw_layers: dict[str, Mapping[str, object]] = {
        profile_source: dict(profile_options),
        "shot_common": dict(common_options),
        "shot_native": dict(native_options),
    }

    def normalize(layer: Mapping[str, object]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in layer.items():
            name = (
                "duration_seconds"
                if key == "duration" and ("duration" in declared or "duration_seconds" in declared)
                else key
            )
            previous = result.get(name)
            if (
                name in result
                and previous is not None
                and value is not None
                and (previous != value or type(previous) is not type(value))
            ):
                raise ValidationAppError(
                    "Conflicting duration aliases",
                    details={"code": "MODEL_OPTION_CONFLICT", "option": name},
                )
            if value is not None or name not in result:
                result[name] = value
        return result

    profile_options = normalize(profile_options)
    common_options = normalize(common_options)
    native_options = normalize(native_options)
    if "duration" in declared:
        declared = dict(declared)
        declared.setdefault("duration_seconds", declared["duration"])
        declared.pop("duration")
    for key in common_options.keys() & native_options.keys():
        common, native = common_options[key], native_options[key]
        if (
            common is not None
            and native is not None
            and (common != native or type(common) is not type(native))
        ):
            raise ValidationAppError(
                f"Option '{key}' has conflicting common/native values",
                details={"code": "MODEL_OPTION_CONFLICT", "option": key},
            )
    values: dict[str, JsonValue] = {}
    sources: dict[str, str] = {}
    requested: dict[str, dict[str, JsonValue]] = {}
    defaults = {key: spec.default for key, spec in declared.items() if spec.default is not None}
    raw_layers["contract_default"] = defaults
    for source, layer in (
        ("contract_default", defaults),
        (profile_source, profile_options),
        ("shot_common", common_options),
        ("shot_native", native_options),
    ):
        requested[source] = {
            name: _JSON.validate_python(value, strict=True)
            for name, value in raw_layers[source].items()
        }
        for key, value in layer.items():
            spec = declared.get(key)
            if spec is None:
                raise ValidationAppError(
                    f"Model contract does not declare option '{key}'",
                    details={"code": "MODEL_OPTION_UNDECLARED", "option": key, "source": source},
                )
            json_value = _JSON.validate_python(value, strict=True)
            if value is None:
                continue
            if allowed_options is not None and key not in allowed_options:
                if source == "contract_default":
                    continue
                raise ValidationAppError(
                    f"Model option '{key}' has no implemented intent field",
                    details={
                        "code": "MODEL_OPTION_NOT_IMPLEMENTED",
                        "option": key,
                        "source": source,
                    },
                )
            try:
                validate_parameter(key, value, spec)
            except ProviderError as exc:
                raise ValidationAppError(
                    f"Model option '{key}' is invalid",
                    details={
                        "code": "MODEL_DURATION_UNSUPPORTED"
                        if key in {"duration", "duration_seconds"}
                        else "MODEL_OPTION_INVALID",
                        "option": key,
                        "source": source,
                    },
                ) from exc
            values[key] = json_value
            sources[key] = source
    return EffectiveGenerationOptions(values=values, sources=sources, requested=requested)
