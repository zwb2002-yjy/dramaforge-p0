"""Versioned Fernet encryption for persisted user BYOK credentials.

Provider credentials are intentionally not written to events or application
logs. A stored ciphertext carries its key version so a new primary key can
decrypt old records during an explicit re-encryption pass.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken


class KeyringConfigurationError(ValueError):
    """Raised when a configured keyring is incomplete or malformed."""


class UnknownKeyVersionError(ValueError):
    """Raised when ciphertext refers to a key no longer retained for reads."""


class CredentialDecryptionError(ValueError):
    """Raised when ciphertext cannot be authenticated by its declared key."""


@dataclass(frozen=True)
class EncryptedCredential:
    ciphertext: str
    key_version: str


class ByokKeyring:
    """Encrypt with one primary Fernet key and decrypt retained key versions."""

    def __init__(self, *, primary_version: str, keys: dict[str, str]) -> None:
        primary = primary_version.strip()
        if not primary:
            raise KeyringConfigurationError("BYOK primary key version is required")
        if primary not in keys:
            raise KeyringConfigurationError(
                f"BYOK primary key version {primary!r} is absent from the keyring"
            )
        try:
            fernet_keys = {
                version: Fernet(material.encode("ascii"))
                for version, material in keys.items()
            }
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise KeyringConfigurationError(
                "BYOK keyring contains an invalid Fernet key"
            ) from exc
        self._primary_version = primary
        self._keys = fernet_keys

    @property
    def primary_version(self) -> str:
        return self._primary_version

    @property
    def readable_versions(self) -> tuple[str, ...]:
        return tuple(sorted(self._keys))

    def encrypt(self, plaintext: str) -> EncryptedCredential:
        if not plaintext:
            raise ValueError("credential plaintext must not be empty")
        token = self._keys[self._primary_version].encrypt(plaintext.encode("utf-8"))
        return EncryptedCredential(
            ciphertext=token.decode("ascii"),
            key_version=self._primary_version,
        )

    def decrypt(self, *, ciphertext: str, key_version: str) -> str:
        fernet = self._keys.get(key_version)
        if fernet is None:
            raise UnknownKeyVersionError(
                f"BYOK key version {key_version!r} is not retained for decryption"
            )
        try:
            return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
            raise CredentialDecryptionError(
                "credential ciphertext failed authentication"
            ) from exc


def parse_keyring(*, primary_version: str, encoded: str, legacy_key: str) -> ByokKeyring:
    """Parse ``version:key,version:key`` without returning key material."""
    pairs: dict[str, str] = {}
    raw = encoded.strip()
    if raw:
        for item in raw.split(","):
            version, sep, material = item.partition(":")
            version = version.strip()
            material = material.strip()
            if not sep or not version or not material or version in pairs:
                raise KeyringConfigurationError(
                    "BYOK_KEYRING must use unique version:key entries"
                )
            pairs[version] = material
    elif legacy_key.strip():
        pairs[primary_version.strip() or "legacy"] = legacy_key.strip()
    return ByokKeyring(primary_version=primary_version or "legacy", keys=pairs)
