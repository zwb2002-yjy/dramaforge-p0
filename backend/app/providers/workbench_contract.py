"""Map the Workbench input mode to exactly one declared reference contract."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatch

from app.providers.capability_resolver import ProductCapabilityPolicy
from app.providers.intents import IMAGE_INTENT_OPTION_FIELDS, VIDEO_INTENT_OPTION_FIELDS
from app.providers.manifest import InputContractSpec, ModelCapabilityManifest, OperationManifest


@dataclass(frozen=True)
class WorkbenchContractSelection:
    contract_id: str
    policy: ProductCapabilityPolicy


VIDEO_UI_MODES = frozenset(
    {"text_to_video", "first_frame", "last_frame", "first_last_frame", "omni_reference"}
)


def _workbench_compiler(manifest: ModelCapabilityManifest) -> object | None:
    from app.providers.registry import get_plugin

    plugin = get_plugin(manifest.provider_type, manifest.protocol_profile)
    if not plugin.implemented or plugin.compiler_factory is None:
        return None
    image, video = plugin.compiler_factory()
    compiler: object = image if manifest.media_kind == "image" else video
    return compiler


def implemented_workbench_options(manifest: ModelCapabilityManifest) -> frozenset[str]:
    """Compiler-owned writable subset; catalog declarations cannot enable fields."""
    compiler = _workbench_compiler(manifest)
    fields: frozenset[str] = getattr(compiler, "workbench_option_fields", frozenset())
    return frozenset(fields)


def workbench_fixed_duration(manifest: ModelCapabilityManifest) -> int | None:
    """Only a legacy Compiler's explicit product default may fill a duration gap."""
    operation = manifest.operations.get("video.generate")
    if manifest.media_kind != "video" or operation is None or operation.input_contracts:
        return None
    value = getattr(_workbench_compiler(manifest), "workbench_fixed_duration_seconds", None)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def workbench_ui_mode(*, media_kind: str, mode_id: str) -> str:
    """Only explicit, established legacy entry names may map to a UI mode."""
    if media_kind == "image" and mode_id in {"explicit_binding", "text_to_image"}:
        return "text_to_image"
    if media_kind == "video":
        if mode_id in {"explicit_binding", "image_to_video"}:
            return "first_frame"
        if mode_id in VIDEO_UI_MODES:
            return mode_id
    raise ValueError(f"Workbench input mode is not supported: {mode_id}")


def validate_mode_roles(*, media_kind: str, ui_mode_id: str, roles: Sequence[str]) -> None:
    if media_kind == "image":
        valid = all(role == "reference_image" for role in roles)
    else:
        expected = {
            "text_to_video": [],
            "first_frame": ["first_frame"],
            "last_frame": ["last_frame"],
            "first_last_frame": ["first_frame", "last_frame"],
        }
        valid = (
            bool(roles)
            and all(
                role in {"reference_image", "reference_video", "reference_audio"} for role in roles
            )
            if ui_mode_id == "omni_reference"
            else list(roles) == expected.get(ui_mode_id)
        )
    if not valid:
        raise ValueError(
            f"输入素材与 {ui_mode_id} 模式不匹配；需要首帧的模式必须使用 Formal 首帧，"
            "请核对素材角色和顺序"
        )


def _accepts_references(
    contract: InputContractSpec, references: Sequence[tuple[str, str | None]]
) -> bool:
    counts = Counter(role for role, _ in references)
    if len(references) < contract.minimum_total_references:
        return False
    if (
        contract.maximum_total_references is not None
        and len(references) > contract.maximum_total_references
    ):
        return False
    for role, count in counts.items():
        slot = contract.input_slots.get(role)
        if slot is None or (slot.maximum is not None and count > slot.maximum):
            return False
    for role, slot in contract.input_slots.items():
        if counts.get(role, 0) < max(slot.minimum, int(slot.required)):
            return False
    for role, mime_type in references:
        slot = contract.input_slots[role]
        if (
            mime_type is not None
            and slot.media_types
            and not any(fnmatch(mime_type.lower(), pattern.lower()) for pattern in slot.media_types)
        ):
            return False
    return True


def select_workbench_contract(
    *,
    operation: OperationManifest,
    media_kind: str,
    references: Sequence[tuple[str, str | None]],
    ui_mode_id: str | None = None,
) -> WorkbenchContractSelection:
    """Fail closed on non-mainchain roles or ambiguous provider contracts."""
    roles = [role for role, _ in references]
    if media_kind == "video":
        selected_mode = workbench_ui_mode(media_kind="video", mode_id=ui_mode_id or "first_frame")
        validate_mode_roles(media_kind="video", ui_mode_id=selected_mode, roles=roles)
        allowed_options = VIDEO_INTENT_OPTION_FIELDS
    elif media_kind == "image":
        if any(role != "reference_image" for role in roles):
            raise ValueError("当前关键帧主链仅接受合同声明的参考图片")
        allowed_options = IMAGE_INTENT_OPTION_FIELDS
    else:
        raise ValueError(f"unsupported Workbench media kind: {media_kind}")
    matches = [
        contract_id
        for contract_id, contract in operation.input_contracts.items()
        if _accepts_references(contract, references)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Workbench inputs must match exactly one model input contract (matched {len(matches)})"
        )
    return WorkbenchContractSelection(
        contract_id=matches[0],
        policy=ProductCapabilityPolicy(
            allowed_contracts=frozenset(matches), allowed_options=allowed_options
        ),
    )
