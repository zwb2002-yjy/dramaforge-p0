"""Atomic "generated Artifact becomes an Asset card" creation chain.

The HTTP layer only authenticates and forwards. Ownership, artifact validity,
type/role compatibility and transport-retry identity are decided here so the
same rules apply to every caller.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.assets.models import Asset, AssetVersion, AssetVersionReference
from app.execution.models import Artifact
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

# Reference roles per asset kind, using the repository's canonical vocabulary
# (`assets/asset_card_service.py`, migration 20260826_0044). "Other" means the
# kind is outside that table: the role set is then unconstrained, while the
# artifact-type compatibility check below still decides.
_GENERIC_ROLES: frozenset[str] = frozenset({"primary"})
_CANONICAL_KIND_ROLES: dict[str, frozenset[str]] = {
    "character": frozenset(
        {
            "front_face",
            "three_quarter",
            "profile",
            "half_body",
            "full_body",
            "expression",
            "outfit",
        }
    ),
    "scene": frozenset(
        {"layout_reference", "lighting_reference", "style_reference", "scene_reference"}
    ),
}
_OTHER = "other"

# Asset kind -> artifact type that may back it. `other` artifacts are accepted
# anywhere because a delivered non-standard type is still explicit user input.
ARTIFACT_KIND_MATCH: dict[str, frozenset[str]] = {
    "character": frozenset({"image"}),
    "scene": frozenset({"image"}),
    "prop": frozenset({"image"}),
    "image": frozenset({"image"}),
    "video": frozenset({"video"}),
    "audio": frozenset({"audio"}),
    "subtitle": frozenset({"subtitle"}),
}

# Artifact kinds that may be referenced while still `quarantined` (not yet
# promoted to storage) are intentionally empty: unreviewed bytes must not become
# an asset card.
_USABLE_STORAGE_STATES = frozenset({"available", "stored"})


@dataclass(frozen=True)
class AssetFromArtifactRequest:
    kind: str
    name: str
    artifact_id: UUID
    description: str = ""
    metadata: dict[str, object] | None = None
    reference_role: str = "primary"


def asset_creation_request_hash(
    *, artifact_id: UUID, kind: str, name: str, description: str,
    reference_role: str, metadata: dict[str, object] | None,
) -> str:
    """Canonical identity of one creation submission.

    Malformed metadata is still hashed deterministically so two retries of the
    same broken input cannot create two cards.
    """
    try:
        metadata_payload: object = json.dumps(
            metadata or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
    except (TypeError, ValueError):
        metadata_payload = repr(sorted((metadata or {}).items(), key=lambda item: item[0]))
    canonical = json.dumps(
        {
            "artifact_id": str(artifact_id),
            "kind": kind,
            "name": name,
            "description": description,
            "reference_role": reference_role,
            "metadata": metadata_payload,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AssetFromArtifactService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: UUID,
        actor: User,
        request: AssetFromArtifactRequest,
        request_key: str | None = None,
    ) -> Asset:
        """Create the Asset/Version/Reference set, or return the original one."""
        await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        request_hash = asset_creation_request_hash(
            artifact_id=request.artifact_id,
            kind=request.kind,
            name=request.name,
            description=request.description,
            reference_role=request.reference_role,
            metadata=request.metadata,
        )
        key = request_key.strip() if request_key else None
        if key == "":
            raise ValidationAppError("Idempotency-Key must not be blank")

        if key is not None:
            existing = await self._by_request_key(project_id=project_id, request_key=key)
            if existing is not None:
                if existing.creation_request_hash != request_hash:
                    raise ConflictError(
                        "This creation request key was already used with a different request",
                        details={
                            "code": "ASSET_CREATION_REQUEST_REUSED",
                            "asset_id": str(existing.id),
                        },
                    )
                return existing

        artifact = await self._load_artifact(
            project_id=project_id, artifact_id=request.artifact_id
        )
        self._validate_kind_and_role(kind=request.kind, reference_role=request.reference_role)
        self._validate_artifact_kind(artifact=artifact, kind=request.kind)

        # Unique (project_id, kind, name) is a real product rule: report it as a
        # conflict instead of surfacing a raw integrity error.
        duplicate = (
            await self._session.execute(
                select(Asset).where(
                    Asset.project_id == project_id,
                    Asset.kind == request.kind,
                    Asset.name == request.name,
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise ConflictError(
                "an asset with this kind and name already exists",
                details={"code": "ASSET_NAME_TAKEN", "asset_id": str(duplicate.id)},
            )

        metadata_json = dict(request.metadata or {})
        asset = Asset(
            project_id=project_id,
            kind=request.kind,
            name=request.name,
            description=request.description,
            metadata_json=metadata_json,
            status="active",
            version=1,
            creation_request_key=key,
            creation_request_hash=request_hash if key is not None else None,
        )
        self._session.add(asset)
        await self._session.flush()
        version = AssetVersion(
            project_id=project_id,
            asset_id=asset.id,
            version_number=1,
            kind=request.kind,
            name=request.name,
            description=request.description,
            metadata_json=metadata_json,
            status="formal",
            created_by=actor.id,
        )
        self._session.add(version)
        await self._session.flush()
        asset.current_version_id = version.id
        self._session.add(
            AssetVersionReference(
                project_id=project_id,
                asset_version_id=version.id,
                artifact_id=artifact.id,
                reference_role=request.reference_role,
                label=request.name,
                sort_order=0,
                metadata_json={},
            )
        )
        await self._session.flush()
        return asset

    async def _by_request_key(self, *, project_id: UUID, request_key: str) -> Asset | None:
        return (
            await self._session.execute(
                select(Asset).where(
                    Asset.project_id == project_id,
                    Asset.creation_request_key == request_key,
                )
            )
        ).scalar_one_or_none()

    async def _load_artifact(self, *, project_id: UUID, artifact_id: UUID) -> Artifact:
        artifact = (
            await self._session.execute(
                select(Artifact).where(
                    Artifact.id == artifact_id, Artifact.project_id == project_id
                )
            )
        ).scalar_one_or_none()
        if artifact is None:
            raise NotFoundError("artifact not found")
        if artifact.deleted_at is not None:
            raise ValidationAppError(
                "artifact was deleted and cannot become an asset",
                details={"code": "ARTIFACT_DELETED"},
            )
        if artifact.storage_state not in _USABLE_STORAGE_STATES:
            raise ValidationAppError(
                f"artifact is not stored yet (storage_state={artifact.storage_state})",
                details={"code": "ARTIFACT_NOT_STORED"},
            )
        return artifact

    def _validate_kind_and_role(self, *, kind: str, reference_role: str) -> None:
        roles = _CANONICAL_KIND_ROLES.get(kind)
        if roles is None:
            # Kinds outside the canonical table (for example "prop") keep their
            # existing freedom; the artifact-type check below is the real guard.
            if reference_role not in _GENERIC_ROLES:
                raise ValidationAppError(
                    f"reference role {reference_role} needs an asset kind with a "
                    "canonical role table",
                    details={
                        "code": "ASSET_REFERENCE_ROLE_UNSUPPORTED",
                        "kind": kind,
                        "supported": sorted(_GENERIC_ROLES),
                    },
                )
            return
        if reference_role not in roles:
            raise ValidationAppError(
                f"reference role {reference_role} does not apply to a {kind} asset",
                details={
                    "code": "ASSET_REFERENCE_ROLE_UNSUPPORTED",
                    "kind": kind,
                    "supported": sorted(roles),
                },
            )

    def _validate_artifact_kind(self, *, artifact: Artifact, kind: str) -> None:
        expected = ARTIFACT_KIND_MATCH.get(kind)
        if expected is None:
            # Unknown asset kind: any stored artifact type is acceptable.
            return
        if artifact.artifact_type in expected or artifact.artifact_type == _OTHER:
            return
        raise ValidationAppError(
            f"artifact type {artifact.artifact_type} cannot become a {kind} asset",
            details={
                "code": "ARTIFACT_KIND_MISMATCH",
                "artifact_type": artifact.artifact_type,
                "expected": sorted(expected),
            },
        )
