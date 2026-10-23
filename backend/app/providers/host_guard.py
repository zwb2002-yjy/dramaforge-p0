"""Provider base_url destination guard (backend-review §1.7 / V6).

A workspace-supplied ``base_url`` decides where the platform sends its
encrypted provider credentials (probe carries ``Authorization: Bearer``).
The guard fails closed on credential-unsafe destinations at write time:

- non-HTTPS schemes (plaintext credential transit);
- IP literals in loopback/link-local/multicast/unspecified/reserved ranges;
- cloud metadata endpoints (169.254.169.254 and friends);

Private deployment is a supported product feature (joint review §6-4), so an
explicit operator opt-in (``PROVIDER_BASE_URL_ALLOW_PRIVATE=true``) admits
private and loopback literals for authenticated self-hosted networks. The
opt-in never admits link-local or metadata addresses: those are not private
deployments, they are credential-exfiltration primitives.

Hostname (non-literal) targets are statically checked only: validation-time
DNS resolution would couple connection writes to resolver availability (and
could diverge from runtime resolution anyway). Runtime clients keep their
own connection handling; this gate is the earliest credential egress
decision for connection create/patch and probes.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.config import Settings
from app.shared.errors import ValidationAppError

# Cloud metadata endpoints by convention; all link-local is blocked anyway.
_METADATA_HOSTNAMES = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
    }
)


@dataclass(frozen=True, slots=True)
class HostVerdict:
    host: str
    port: int
    addresses: frozenset[str]


def _classify(address: str) -> tuple[bool, bool]:
    """Return (private_deployment, hard_blocked) for one IP literal.

    Loopback counts as a private deployment (it is authorizable for local
    self-hosted setups), including the IPv6 loopback whose ``is_reserved``
    flag is an ipaddress implementation detail, not an exfiltration signal.
    """

    ip = ipaddress.ip_address(address)
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return False, True
    if ip.is_loopback or ip.is_private:
        return True, False
    if ip.is_reserved:
        return False, True
    return False, False


def validate_provider_base_url(
    value: str,
    *,
    settings: Settings,
) -> HostVerdict:
    """Validate one workspace-supplied provider base_url (fail-closed)."""

    raw = value.strip().rstrip("/")
    if not raw:
        raise ValidationAppError("base_url must not be empty")
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValidationAppError(
            "provider base_url must be an HTTPS origin without credentials",
            details={"code": "PROVIDER_BASE_URL_INVALID"},
        )
    host = parsed.hostname.rstrip(".").lower()
    if host in _METADATA_HOSTNAMES:
        raise ValidationAppError(
            "provider base_url must not target a metadata endpoint",
            details={"code": "PROVIDER_BASE_URL_METADATA"},
        )
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise ValidationAppError(
            "provider base_url port is invalid",
            details={"code": "PROVIDER_BASE_URL_INVALID"},
        ) from exc
    try:
        addresses = frozenset({str(ipaddress.ip_address(host))})
    except ValueError:
        # Hostname targets are statically checked; runtime clients own
        # connection-time resolution.
        return HostVerdict(host=host, port=port, addresses=frozenset())
    allow_private = settings.provider_base_url_allow_private
    for address in addresses:
        private, hard_blocked = _classify(address)
        if hard_blocked:
            raise ValidationAppError(
                "provider base_url must not target link-local, metadata or "
                "reserved addresses",
                details={"code": "PROVIDER_BASE_URL_BLOCKED_TARGET"},
            )
        if private and not allow_private:
            raise ValidationAppError(
                "provider base_url targets a private address; set "
                "PROVIDER_BASE_URL_ALLOW_PRIVATE=true to authorize a "
                "self-hosted private deployment",
                details={"code": "PROVIDER_BASE_URL_PRIVATE_NOT_AUTHORIZED"},
            )
    return HostVerdict(host=host, port=port, addresses=addresses)


__all__ = ["HostVerdict", "validate_provider_base_url"]
