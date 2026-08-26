"""Canonical Provider reference-slot vocabulary.

Request containers may remain plural for API ergonomics, but every manifest,
validator and bridge boundary uses these singular role identities.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal


class ReferenceRole(StrEnum):
    FIRST_FRAME = "first_frame"
    LAST_FRAME = "last_frame"
    REFERENCE_IMAGE = "reference_image"
    REFERENCE_VIDEO = "reference_video"
    REFERENCE_AUDIO = "reference_audio"


ReferenceRoleValue = Literal[
    "first_frame",
    "last_frame",
    "reference_image",
    "reference_video",
    "reference_audio",
]


CANONICAL_REFERENCE_ROLES: Final[frozenset[str]] = frozenset(
    role.value for role in ReferenceRole
)

ROLE_MEDIA_TYPES: Final[dict[str, str]] = {
    ReferenceRole.FIRST_FRAME.value: "image/*",
    ReferenceRole.LAST_FRAME.value: "image/*",
    ReferenceRole.REFERENCE_IMAGE.value: "image/*",
    ReferenceRole.REFERENCE_VIDEO.value: "video/*",
    ReferenceRole.REFERENCE_AUDIO.value: "audio/*",
}

REQUEST_FIELD_TO_ROLE: Final[dict[str, str]] = {
    "reference_images": ReferenceRole.REFERENCE_IMAGE.value,
    "reference_videos": ReferenceRole.REFERENCE_VIDEO.value,
    "reference_audio": ReferenceRole.REFERENCE_AUDIO.value,
}


def canonical_reference_role(value: str) -> str | None:
    """Return the canonical singular role for a manifest/request role name."""
    if value in CANONICAL_REFERENCE_ROLES:
        return value
    return REQUEST_FIELD_TO_ROLE.get(value)
