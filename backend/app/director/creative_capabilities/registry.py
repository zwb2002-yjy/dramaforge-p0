"""Creative capability registry (CC2).

Provider-neutral, deterministic, version-aware.  Holds registered
``CreativeSkillSpec``/``GenreProfileSpec``/``StylePackSpec`` instances in code.
It must never touch the network, read credentials, or fall back to another
provider/template (G-WF-04 for creative capabilities).
"""

from __future__ import annotations

from collections.abc import Iterable

from app.director.creative_capabilities.contracts import (
    CreativeSkillResolution,
    CreativeSkillSpec,
)


class CreativeSkillRegistry:
    """In-memory registration and eligibility lookup for creative skills."""

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, CreativeSkillSpec]] = {}
        self._keys: dict[str, CreativeSkillSpec] = {}

    def register(self, spec: CreativeSkillSpec) -> CreativeSkillSpec:
        """Register a skill version (idempotent; refuses a contract overwrite)."""
        versions = self._entries.setdefault(spec.skill_key, {})
        existing = versions.get(spec.skill_version)
        if existing is not None and existing.contract_hash != spec.contract_hash:
            raise ValueError(
                f"skill contract mismatch for {spec.identity}: refusing to overwrite"
            )
        versions[spec.skill_version] = spec
        # ``_keys`` points at the highest registered version.
        self._keys[spec.skill_key] = max(
            versions.values(), key=lambda s: s.skill_version
        )
        return spec

    def get(self, skill_key: str) -> CreativeSkillSpec | None:
        """Return the highest registered version for ``skill_key``."""
        return self._keys.get(skill_key)

    def get_versioned(
        self, skill_key: str, skill_version: str
    ) -> CreativeSkillSpec | None:
        return self._entries.get(skill_key, {}).get(skill_version)

    def all(self) -> list[CreativeSkillSpec]:
        """All registered skills (highest version per key, insertion order)."""
        return list(self._keys.values())

    def keys(self) -> list[str]:
        return list(self._keys)

    def contains(self, skill_key: str) -> bool:
        return skill_key in self._entries

    def resolve(self, skill_key: str) -> CreativeSkillResolution:
        """Resolve an explicitly requested skill, failing closed on absence.

        Never silently substitutes another skill or version (G-WF-04 for
        creative capabilities): an unregistered key returns ``UNAVAILABLE``.
        """
        spec = self.get(skill_key)
        if spec is None:
            return CreativeSkillResolution(
                requested_skill_key=skill_key,
                resolved_skill_key=None,
                status="UNAVAILABLE",
                reason=f"skill {skill_key!r} is not registered",
            )
        return CreativeSkillResolution(
            requested_skill_key=skill_key,
            resolved_skill_key=spec.skill_key,
            status="RESOLVED",
            contract_hash=spec.contract_hash,
            skill_version=spec.skill_version,
        )


def build_skill_registry(specs: Iterable[CreativeSkillSpec]) -> CreativeSkillRegistry:
    """Convenience builder that registers every spec in ``specs`` in order."""
    registry = CreativeSkillRegistry()
    for spec in specs:
        registry.register(spec)
    return registry
