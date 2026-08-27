"""Generic version-aware registry for all creative capability packs (CC2/CC5-CC8).

Every capability spec here has a stable ``identity`` (key@version) and a
``contract_hash`` over the semantic contract.  The registry is provider-neutral
and deterministic; it never touches a Provider or falls back to another pack.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class _Versioned:
    """Protocol mixin for a versioned, hashable capability contract."""

    _key_field: str

    @property
    def identity(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError


class PackRegistry(Generic[T]):
    """Register/get/all by a pack's key attribute, keeping the highest version."""

    def __init__(self, *, key_field: str) -> None:
        self._key_field = key_field
        self._entries: dict[str, dict[str, T]] = {}
        self._keys: dict[str, T] = {}

    def _key(self, spec: T) -> str:
        return str(getattr(spec, self._key_field))

    def _version(self, spec: T) -> str:
        return str(getattr(spec, "version" if hasattr(spec, "version") else "pack_version"))

    def register(self, spec: T) -> T:
        key = self._key(spec)
        version = self._version(spec)
        versions = self._entries.setdefault(key, {})
        existing = versions.get(version)
        if existing is not None:
            existing_hash = getattr(existing, "contract_hash", None)
            new_hash = getattr(spec, "contract_hash", None)
            if existing_hash is not None and new_hash is not None and existing_hash != new_hash:
                raise ValueError(f"contract mismatch for {key}@{version}: refusing overwrite")
        versions[version] = spec
        # ``_keys`` points at the highest registered version.
        self._keys[key] = max(versions.values(), key=lambda s: self._version(s))
        return spec

    def get(self, key: str) -> T | None:
        return self._keys.get(key)

    def contains(self, key: str) -> bool:
        return key in self._entries

    def all(self) -> list[T]:
        return list(self._keys.values())

    def keys(self) -> list[str]:
        return list(self._keys)


def build_pack_registry(specs: Iterable[BaseModel], *, key_field: str) -> PackRegistry[BaseModel]:
    registry: PackRegistry[BaseModel] = PackRegistry(key_field=key_field)
    for spec in specs:
        registry.register(spec)
    return registry
