"""Provider base_url destination guard (backend-review §1.7 / V6, joint-review P1).

A workspace-supplied ``base_url`` decides where the platform sends its
encrypted provider credentials (requests carry ``Authorization: Bearer``).
Defense is layered:

1. **Write-time static gate** (:func:`validate_provider_base_url`) — the
   earliest credential egress decision for connection create/patch. Offline
   and deterministic: scheme, embedded credentials, metadata hostnames, and
   IP-literal classification. Hostnames are never resolved here.
2. **Connection-time egress gate** (``app.providers.egress``) — every TCP
   connection resolves the hostname, classifies every resolved address, and
   opens the socket against one validated address. This closes DNS
   rebinding and hostname-to-private-address redirects that a static gate
   cannot see.

Classification order matters (joint-review P1): hard-blocked categories are
decided BEFORE the private-deployment allowance, because Python's
``ipaddress`` flags are not mutually exclusive — 240.0.0.1 is both
``is_private`` and ``is_reserved``, and must stay unreachable even when
private deployments are authorized. Loopback is the deliberate exception:
it is a local self-hosted deployment primitive, carved out before the
reserved check (the IPv6 loopback's ``is_reserved`` flag is an ipaddress
implementation detail, not an exfiltration signal).

Private deployment is a supported product feature (joint review §6-4):
``PROVIDER_BASE_URL_ALLOW_PRIVATE=true`` admits private and loopback
targets for authenticated self-hosted networks. Plaintext HTTP is a
separate, narrower trust: ``PROVIDER_TRUSTED_HTTP_NETWORKS`` names the
exact CIDRs (never the whole address space) that may receive ``http://``
base_urls; everything else stays HTTPS-only. Neither opt-in ever admits
link-local, multicast, unspecified, shared (CGNAT) or reserved addresses:
those are not private deployments, they are credential-exfiltration
primitives.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Literal
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

EgressCategory = Literal["hard_blocked", "private_deployment", "shared_non_global", "public"]


@dataclass(frozen=True, slots=True)
class HostVerdict:
    host: str
    port: int
    addresses: frozenset[str]


def classify_ip_address(address: str) -> EgressCategory:
    """Classify one IP literal for credential egress.

    Hard-blocked categories win over the private-deployment allowance, so a
    reserved address that Python also reports as private stays unreachable.
    """

    ip = ipaddress.ip_address(address)
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return "hard_blocked"
    if ip.is_loopback:
        return "private_deployment"
    if ip.is_reserved:
        return "hard_blocked"
    if ip.is_private:
        return "private_deployment"
    if not ip.is_global:
        # Shared/CGNAT (100.64.0.0/10) and other non-global unicast.
        return "shared_non_global"
    return "public"


def _ip_in_trusted_networks(
    address: str,
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in networks)


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
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValidationAppError(
            "provider base_url must be an HTTPS or trusted-HTTP origin without credentials",
            details={"code": "PROVIDER_BASE_URL_INVALID"},
        )
    host = parsed.hostname.rstrip(".").lower()
    if host in _METADATA_HOSTNAMES:
        raise ValidationAppError(
            "provider base_url must not target a metadata endpoint",
            details={"code": "PROVIDER_BASE_URL_METADATA"},
        )
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValidationAppError(
            "provider base_url port is invalid",
            details={"code": "PROVIDER_BASE_URL_INVALID"},
        ) from exc
    trusted = settings.provider_trusted_network_objects()
    if parsed.scheme == "http":
        # Scoped plaintext trust: only an IP literal inside an explicitly
        # declared network. Hostnames are rejected because write time cannot
        # bind them to a trusted address (connection-time egress validation
        # covers the runtime side of this policy).
        try:
            addresses = frozenset({str(ipaddress.ip_address(host))})
        except ValueError:
            raise ValidationAppError(
                "plaintext http base_url requires an IP literal inside "
                "PROVIDER_TRUSTED_HTTP_NETWORKS; use HTTPS or a TLS reverse "
                "proxy for named hosts",
                details={"code": "PROVIDER_BASE_URL_HTTP_UNTRUSTED"},
            ) from None
        for address in addresses:
            if classify_ip_address(address) in {"hard_blocked", "shared_non_global"}:
                raise ValidationAppError(
                    "provider base_url must not target link-local, metadata or "
                    "reserved addresses",
                    details={"code": "PROVIDER_BASE_URL_BLOCKED_TARGET"},
                )
            if not _ip_in_trusted_networks(address, trusted):
                raise ValidationAppError(
                    "plaintext http base_url target is not inside "
                    "PROVIDER_TRUSTED_HTTP_NETWORKS",
                    details={"code": "PROVIDER_BASE_URL_HTTP_UNTRUSTED"},
                )
        return HostVerdict(host=host, port=port, addresses=addresses)
    try:
        addresses = frozenset({str(ipaddress.ip_address(host))})
    except ValueError:
        # Hostname targets are statically checked; the connection-time
        # egress gate owns runtime resolution and validation.
        return HostVerdict(host=host, port=port, addresses=frozenset())
    allow_private = settings.provider_base_url_allow_private
    for address in addresses:
        category = classify_ip_address(address)
        if category in {"hard_blocked", "shared_non_global"}:
            raise ValidationAppError(
                "provider base_url must not target link-local, metadata, "
                "reserved or shared addresses",
                details={"code": "PROVIDER_BASE_URL_BLOCKED_TARGET"},
            )
        if category == "private_deployment" and not allow_private:
            raise ValidationAppError(
                "provider base_url targets a private address; set "
                "PROVIDER_BASE_URL_ALLOW_PRIVATE=true to authorize a "
                "self-hosted private deployment",
                details={"code": "PROVIDER_BASE_URL_PRIVATE_NOT_AUTHORIZED"},
            )
    return HostVerdict(host=host, port=port, addresses=addresses)


__all__ = ["EgressCategory", "HostVerdict", "classify_ip_address", "validate_provider_base_url"]
