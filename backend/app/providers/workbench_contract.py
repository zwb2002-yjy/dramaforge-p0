"""Select the product-open input contract for the existing shot Workbench.

The product path requires a Formal first frame for video. Provider reference
contracts remain visible in the catalog but are not opened by this path.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatch

from app.providers.capability_resolver import ProductCapabilityPolicy
from app.providers.manifest import InputContractSpec, OperationManifest


@dataclass(frozen=True)
class WorkbenchContractSelection:
    contract_id: str
    policy: ProductCapabilityPolicy


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
        if mime_type is not None and slot.media_types and not any(
            fnmatch(mime_type.lower(), pattern.lower()) for pattern in slot.media_types
        ):
            return False
    return True


def select_workbench_contract(
    *,
    operation: OperationManifest,
    media_kind: str,
    references: Sequence[tuple[str, str | None]],
) -> WorkbenchContractSelection:
    """Fail closed on non-mainchain roles or ambiguous provider contracts."""
    roles = [role for role, _ in references]
    if media_kind == "video":
        if "first_frame" not in roles:
            raise ValueError("当前视频主链缺少 Formal 首帧")
        if roles != ["first_frame"]:
            raise ValueError(
                "当前视频主链必须使用 Formal 首帧；其他参考素材与首帧合同冲突，"
                "请先移除这些参考素材"
            )
        allowed_options = frozenset({"aspect_ratio", "duration_seconds"})
    elif media_kind == "image":
        if any(role != "reference_image" for role in roles):
            raise ValueError("当前关键帧主链仅接受合同声明的参考图片")
        allowed_options = frozenset({"aspect_ratio"})
    else:
        raise ValueError(f"unsupported Workbench media kind: {media_kind}")
    matches = [
        contract_id
        for contract_id, contract in operation.input_contracts.items()
        if _accepts_references(contract, references)
    ]
    if len(matches) != 1:
        raise ValueError(
            "Workbench inputs must match exactly one model input contract "
            f"(matched {len(matches)})"
        )
    return WorkbenchContractSelection(
        contract_id=matches[0],
        policy=ProductCapabilityPolicy(
            allowed_contracts=frozenset(matches), allowed_options=allowed_options
        ),
    )
