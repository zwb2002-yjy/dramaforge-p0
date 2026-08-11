"""Production Model Profile service (spec §11, §30, §54–§57, §62).

Owns the two-level profile model (Workspace default + Project profile), versioned
updates with optimistic locking, simple-mode batch mapping, and strict save-time
validation against the :class:`ModelRegistry` (spec §64–§66). The service only
*selects* models — execution always flows through the CapabilityRouter
(spec §17, §134 rules 3–4).
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any, cast
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.providers.capabilities import Capability
from app.providers.model_profiles.errors import (
    profile_not_found,
    profile_slot_unknown,
    profile_version_conflict,
)
from app.providers.model_profiles.models import (
    ModelProfileSnapshot,
    ModelSlotBinding,
    ResolvedModelBinding,
    SimpleModeSelection,
)
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.model_profiles.schemas import (
    BindingRead,
    ProfileRead,
    ProfileValidationIssue,
)
from app.providers.model_profiles.slots import (
    MODEL_SLOT_DEFINITIONS,
    SIMPLE_MODE_SLOT_GROUPS,
    ModelSlot,
    slot_definition,
)
from app.providers.registry import ModelRegistry, RegisteredModel
from app.providers.validator import validate_parameter
from app.shared.errors import ValidationAppError


@lru_cache(maxsize=1)
def default_model_registry() -> ModelRegistry:
    """Module-cached default V3 model registry (includes M7 text models)."""
    from app.providers.bootstrap import default_v3_registry

    return default_v3_registry()[0]


def parse_binding_json(raw: object) -> ModelSlotBinding:
    """Parse one stored binding dict (``{"model_id", "native_options", "enabled"}``)
    into the domain model. Unknown fields are rejected (strict)."""
    if not isinstance(raw, dict):
        raise ValidationAppError(
            "profile binding must be an object",
            details={"code": "MODEL_PROFILE_BINDING_INVALID"},
        )
    slot_value = raw.get("slot")
    if not isinstance(slot_value, str):
        raise ValidationAppError(
            "profile binding is missing slot",
            details={"code": "MODEL_PROFILE_BINDING_INVALID"},
        )
    try:
        slot = ModelSlot(slot_value)
    except ValueError as exc:
        raise profile_slot_unknown(slot_value) from exc
    try:
        return ModelSlotBinding(
            slot=slot,
            model_id=str(raw.get("model_id") or ""),
            native_options=dict(raw.get("native_options") or {}),
            generation_policy=raw.get("generation_policy"),
            enabled=bool(raw.get("enabled", True)),
        )
    except PydanticValidationError as exc:
        raise ValidationAppError(
            "profile binding is invalid",
            details={"code": "MODEL_PROFILE_BINDING_INVALID", "error": str(exc)[:300]},
        ) from exc


def parse_bindings(raw: object) -> dict[ModelSlot, ModelSlotBinding]:
    """Parse the stored ``bindings`` JSON map into domain bindings."""
    if not isinstance(raw, dict):
        return {}
    bindings: dict[ModelSlot, ModelSlotBinding] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            value = {**value, "slot": value.get("slot", key)}
        binding = parse_binding_json(value)
        bindings[binding.slot] = binding
    return bindings


def bindings_to_json(bindings: dict[ModelSlot, ModelSlotBinding]) -> dict[str, object]:
    """Serialize domain bindings for the DB JSON column (keys are slot ids)."""
    return {
        str(binding.slot): {
            "model_id": binding.model_id,
            "native_options": binding.native_options,
            "enabled": binding.enabled,
        }
        for binding in bindings.values()
    }


class ProfileValidationReport:
    def __init__(self, issues: list[ProfileValidationIssue]) -> None:
        self.issues = issues

    @property
    def valid(self) -> bool:
        return not self.issues

    def raise_if_invalid(self) -> None:
        if not self.valid:
            first = self.issues[0]
            raise ValidationAppError(
                first.message,
                details={"code": first.code, "slot": first.slot, "model_id": first.model_id},
            )


class ProductionModelProfileService:
    """CRUD + validation + snapshot helpers for production model profiles."""

    def __init__(
        self,
        session: AsyncSession,
        registry: ModelRegistry | None = None,
    ) -> None:
        self._session = session
        if registry is None:
            self._registry = default_model_registry()
        else:
            self._registry = registry

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get(self, *, profile_id: UUID) -> ProductionModelProfile:
        profile = await self._session.get(ProductionModelProfile, profile_id)
        if profile is None:
            raise profile_not_found()
        return profile

    async def _get_for_update(self, *, profile_id: UUID) -> ProductionModelProfile:
        """Row-locked read for version-check-then-write (optimistic lock, spec
        §72–§73). Serializes concurrent updates so two writers with the same
        ``expected_version`` cannot both pass the check (PG FOR UPDATE; SQLite
        ignores the lock but the partial default index still fails closed)."""
        from typing import cast

        profile = cast(
            "ProductionModelProfile | None",
            await self._session.scalar(
                select(ProductionModelProfile)
                .where(ProductionModelProfile.id == profile_id)
                .with_for_update()
            ),
        )
        if profile is None:
            raise profile_not_found()
        return profile

    async def list_workspace_profiles(
        self, *, workspace_id: UUID
    ) -> list[ProductionModelProfile]:
        rows = list(
            (
                await self._session.execute(
                    select(ProductionModelProfile)
                    .where(
                        ProductionModelProfile.workspace_id == workspace_id,
                        ProductionModelProfile.project_id.is_(None),
                    )
                    .order_by(ProductionModelProfile.is_default.desc())
                )
            )
            .scalars()
            .all()
        )
        return rows

    async def get_workspace_default(
        self, *, workspace_id: UUID
    ) -> ProductionModelProfile | None:
        return cast(
            "ProductionModelProfile | None",
            await self._session.scalar(
                select(ProductionModelProfile).where(
                    ProductionModelProfile.workspace_id == workspace_id,
                    ProductionModelProfile.project_id.is_(None),
                    ProductionModelProfile.is_default.is_(True),
                )
            ),
        )

    async def get_project_profile(
        self, *, project_id: UUID
    ) -> ProductionModelProfile | None:
        return cast(
            "ProductionModelProfile | None",
            await self._session.scalar(
                select(ProductionModelProfile).where(
                    ProductionModelProfile.project_id == project_id,
                )
            ),
        )

    async def get_effective_for_project(
        self, *, project: Project
    ) -> ProductionModelProfile | None:
        """Project profile, else the workspace default (spec §14/§54)."""
        profile = await self.get_project_profile(project_id=project.id)
        if profile is None:
            profile = await self.get_workspace_default(
                workspace_id=project.workspace_id
            )
        return profile

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        name: str,
        bindings: dict[ModelSlot, ModelSlotBinding],
        is_default: bool = False,
        project_id: UUID | None = None,
        copy_from: UUID | None = None,
    ) -> ProductionModelProfile:
        """Create a profile. ``copy_from`` snapshots another profile's bindings
        into this one (spec §54 Snapshot — creating a project copies the
        workspace default rather than live-inheriting)."""
        if copy_from is not None:
            source = await self.get(profile_id=copy_from)
            if source.workspace_id != workspace_id:
                raise ValidationAppError(
                    "copy_from profile belongs to a different workspace",
                    details={"code": "MODEL_PROFILE_COPY_SCOPE"},
                )
            bindings = parse_bindings(source.bindings)
        report = self.validate_bindings(bindings)
        report.raise_if_invalid()
        if is_default and project_id is None:
            await self._clear_workspace_default(workspace_id=workspace_id, actor_id=actor_id)
        if project_id is not None:
            existing = await self.get_project_profile(project_id=project_id)
            if existing is not None:
                raise ValidationAppError(
                    "project already has a model profile",
                    details={"code": "MODEL_PROFILE_EXISTS"},
                )
        profile = ProductionModelProfile(
            workspace_id=workspace_id,
            project_id=project_id,
            name=name,
            version=1,
            is_default=is_default and project_id is None,
            bindings=bindings_to_json(bindings),
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(profile)
        await self._session.flush()
        return profile

    async def update(
        self,
        *,
        profile_id: UUID,
        actor_id: UUID,
        name: str | None = None,
        bindings: dict[ModelSlot, ModelSlotBinding] | None = None,
        is_default: bool | None = None,
        expected_version: int | None = None,
    ) -> ProductionModelProfile:
        profile = await self._get_for_update(profile_id=profile_id)
        if expected_version is not None and profile.version != expected_version:
            raise profile_version_conflict(expected_version, profile.version)
        if name is not None:
            profile.name = name
        if bindings is not None:
            report = self.validate_bindings(bindings)
            report.raise_if_invalid()
            profile.bindings = bindings_to_json(bindings)
        if is_default is not None and profile.project_id is None:
            if is_default and not profile.is_default:
                await self._clear_workspace_default(
                    workspace_id=profile.workspace_id,
                    actor_id=actor_id,
                    exclude_id=profile.id,
                )
            profile.is_default = is_default
        profile.updated_by = actor_id
        profile.version += 1
        profile.updated_at = _now()
        await self._session.flush()
        return profile

    async def apply_simple_mode(
        self,
        *,
        profile_id: UUID,
        selection: SimpleModeSelection,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> ProductionModelProfile:
        """Simple-mode batch patch (spec §30/§77/§78): LLM / Image / Video map to
        slot groups. ``bindings`` stays the single source of truth."""
        profile = await self._get_for_update(profile_id=profile_id)
        if expected_version is not None and profile.version != expected_version:
            raise profile_version_conflict(expected_version, profile.version)
        bindings = parse_bindings(profile.bindings)
        patches: dict[str, str | None] = {
            "llm": selection.llm_model_id,
            "image": selection.image_model_id,
            "video": selection.video_model_id,
        }
        for group, model_id in patches.items():
            if model_id is None:
                continue
            for slot in SIMPLE_MODE_SLOT_GROUPS[group]:
                bindings[slot] = ModelSlotBinding(slot=slot, model_id=model_id)
        report = self.validate_bindings(bindings)
        report.raise_if_invalid()
        profile.bindings = bindings_to_json(bindings)
        profile.updated_by = actor_id
        profile.version += 1
        profile.updated_at = _now()
        await self._session.flush()
        return profile

    async def delete(self, *, profile_id: UUID, actor_id: UUID) -> None:
        profile = await self.get(profile_id=profile_id)
        if profile.project_id is None and profile.is_default:
            raise ValidationAppError(
                "cannot delete the workspace default model profile",
                details={"code": "MODEL_PROFILE_DEFAULT_PROTECTED"},
            )
        await self._session.delete(profile)
        await self._session.flush()

    async def _clear_workspace_default(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        exclude_id: UUID | None = None,
    ) -> None:
        stmt = (
            select(ProductionModelProfile)
            .where(
                ProductionModelProfile.workspace_id == workspace_id,
                ProductionModelProfile.project_id.is_(None),
                ProductionModelProfile.is_default.is_(True),
            )
            .with_for_update()
        )
        if exclude_id is not None:
            stmt = stmt.where(ProductionModelProfile.id != exclude_id)
        current = (await self._session.execute(stmt)).scalars().all()
        for profile in current:
            profile.is_default = False
            profile.updated_by = actor_id
            profile.updated_at = _now()

    # ------------------------------------------------------------------
    # Validation (spec §64–§66, §36)
    # ------------------------------------------------------------------

    def model_supports(self, model: RegisteredModel, capability: Capability) -> bool:
        return capability in model.manifest.capability_specs

    def validate_bindings(
        self, bindings: dict[ModelSlot, ModelSlotBinding]
    ) -> ProfileValidationReport:
        """Strict save-time validation: model exists, slot accepts capability,
        model supports capability, native options valid. Does NOT require a
        currently-healthy credential (spec §66 — a temporarily disabled key must
        not block editing)."""
        issues: list[ProfileValidationIssue] = []
        for slot, binding in bindings.items():
            if not binding.enabled:
                continue
            definition = MODEL_SLOT_DEFINITIONS.get(slot)
            if definition is None:
                issues.append(
                    ProfileValidationIssue(
                        code="MODEL_PROFILE_SLOT_UNKNOWN",
                        slot=str(slot),
                        model_id=binding.model_id,
                        message=f"unknown model slot: {slot}",
                    )
                )
                continue
            model = self._registry.get_or_none(binding.model_id)
            if model is None:
                issues.append(
                    ProfileValidationIssue(
                        code="MODEL_PROFILE_MODEL_NOT_FOUND",
                        slot=str(slot),
                        model_id=binding.model_id,
                        message=f"model profile references unknown model: {binding.model_id}",
                    )
                )
                continue
            manifest = model.manifest
            if manifest.metadata.get("lifecycle") == "retired":
                issues.append(
                    ProfileValidationIssue(
                        code="MODEL_PROFILE_MODEL_DISABLED",
                        slot=str(slot),
                        model_id=binding.model_id,
                        message=f"model is retired: {binding.model_id}",
                    )
                )
            supported = set(manifest.capability_specs)
            accepted = set(definition.required_capabilities)
            if not (supported & accepted):
                issues.append(
                    ProfileValidationIssue(
                        code="MODEL_PROFILE_CAPABILITY_MISMATCH",
                        slot=str(slot),
                        model_id=binding.model_id,
                        message=(
                            f"model {binding.model_id} does not support slot "
                            f"{slot} requirements {sorted(str(c) for c in accepted)}"
                        ),
                    )
                )
            for option, value in binding.native_options.items():
                self._validate_native_option(
                    model, option, value, slot, binding, issues
                )
        return ProfileValidationReport(issues)

    def _validate_native_option(
        self,
        model: RegisteredModel,
        option: str,
        value: Any,
        slot: ModelSlot,
        binding: ModelSlotBinding,
        issues: list[ProfileValidationIssue],
    ) -> None:
        declared: bool = False
        for spec in model.manifest.capability_specs.values():
            parameter = spec.native_options.get(option)
            if parameter is None:
                continue
            declared = True
            try:
                validate_parameter(option, value, parameter)
            except Exception as exc:  # noqa: BLE001 - surfaced as a validation issue
                issues.append(
                    ProfileValidationIssue(
                        code="MODEL_PROFILE_NATIVE_OPTION_INVALID",
                        slot=str(slot),
                        model_id=binding.model_id,
                        message=f"native option {option} is invalid: {exc}",
                    )
                )
            break
        if not declared:
            issues.append(
                ProfileValidationIssue(
                    code="MODEL_PROFILE_NATIVE_OPTION_INVALID",
                    slot=str(slot),
                    model_id=binding.model_id,
                    message=f"model {binding.model_id} does not declare native option {option}",
                )
            )

    async def validate_bindings_api(
        self, bindings: dict[ModelSlot, ModelSlotBinding]
    ) -> ProfileValidationReport:
        return self.validate_bindings(bindings)

    # ------------------------------------------------------------------
    # Reads / mapping
    # ------------------------------------------------------------------

    async def binding_reads(
        self,
        *,
        workspace_id: UUID,
        bindings: dict[ModelSlot, ModelSlotBinding],
    ) -> dict[str, BindingRead]:
        from app.providers.models import ProviderConnection

        rows = list(
            (
                await self._session.execute(
                    select(ProviderConnection.provider_type).where(
                        ProviderConnection.workspace_id == workspace_id,
                        ProviderConnection.enabled.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        configured: set[str] = set(rows)
        # The LiteLLM gateway is configured via settings, not a ProviderConnection
        # (spec §113), so its text model must not display as unconfigured.
        from app.config import get_settings

        settings = get_settings()
        litellm_configured = bool(
            settings.litellm_gateway_url.strip() and settings.litellm_api_key.strip()
        )
        result: dict[str, BindingRead] = {}
        for slot, binding in bindings.items():
            model = self._registry.get_or_none(binding.model_id)
            provider_id = model.manifest.provider_id if model is not None else ""
            display_name = model.manifest.display_name if model is not None else binding.model_id
            is_configured = (
                litellm_configured if provider_id == "litellm" else provider_id in configured
            )
            result[str(slot)] = BindingRead(
                slot=str(slot),
                model_id=binding.model_id,
                native_options=binding.native_options,
                enabled=binding.enabled,
                provider_id=provider_id,
                display_name=display_name,
                configured=is_configured,
            )
        return result

    async def profile_read(
        self, profile: ProductionModelProfile
    ) -> ProfileRead:
        bindings = parse_bindings(profile.bindings)
        reads = await self.binding_reads(
            workspace_id=profile.workspace_id,
            bindings=bindings,
        )
        return ProfileRead(
            id=profile.id,
            workspace_id=profile.workspace_id,
            project_id=profile.project_id,
            name=profile.name,
            version=profile.version,
            is_default=profile.is_default,
            bindings=reads,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    async def snapshot_for_project(
        self, *, project: Project
    ) -> ModelProfileSnapshot:
        """Resolve the effective profile for a project and freeze its bindings
        into an immutable snapshot (spec §21/§92). The snapshot uses the *current*
        bindings at graph start; a running graph keeps them even if the profile
        changes."""
        profile = await self.get_effective_for_project(project=project)
        if profile is None:
            return ModelProfileSnapshot(
                profile_id=None, profile_version=None, bindings={}
            )
        snapshot: dict[ModelSlot, ResolvedModelBinding] = {}
        for slot, binding in parse_bindings(profile.bindings).items():
            if not binding.enabled:
                continue
            definition = slot_definition(slot)
            model = self._registry.get_or_none(binding.model_id)
            if model is None:
                continue
            # Pick the first slot capability this model supports for the snapshot.
            supported = [
                capability
                for capability in definition.required_capabilities
                if self.model_supports(model, capability)
            ]
            if not supported:
                continue
            snapshot[slot] = ResolvedModelBinding(
                slot=slot,
                capability=supported[0],
                model_id=binding.model_id,
                source=(
                    "project_profile"
                    if profile.project_id is not None
                    else "workspace_profile"
                ),
                profile_id=profile.id,
                profile_version=profile.version,
                native_options=binding.native_options,
            )
        return ModelProfileSnapshot(
            profile_id=profile.id,
            profile_version=profile.version,
            bindings=snapshot,
        )


def _now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)


def build_snapshot_json(snapshot: ModelProfileSnapshot) -> dict[str, object]:
    """Serialize a :class:`ModelProfileSnapshot` for ``GraphVersion.definition``
    / ``NodeRun.input_snapshot``."""
    return {
        "profile_id": str(snapshot.profile_id) if snapshot.profile_id is not None else None,
        "profile_version": snapshot.profile_version,
        "bindings": {
            str(slot): binding.model_dump(mode="json")
            for slot, binding in snapshot.bindings.items()
        },
    }
