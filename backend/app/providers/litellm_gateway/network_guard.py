"""Network-namespace ACL for the separate LiteLLM process, never a model router.

The Proxy shares this container's network namespace without NET_ADMIN. Rules
pin approved DNS answers and ports before Proxy startup; a new DNS answer is
denied until this guard is deliberately recreated. No Provider HTTP is sent.
"""

from __future__ import annotations

import ipaddress
import json
import os
import signal
import socket
import subprocess
from collections.abc import Callable
from urllib.parse import urlsplit

AddressLookup = Callable[[str, int], list[str]]


def resolve_addresses(host: str, port: int) -> list[str]:
    answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(row[4][0]) for row in answers})


def approved_destinations(
    origins: list[str], trusted_cidrs: list[str], *, lookup: AddressLookup = resolve_addresses
) -> list[tuple[str, int]]:
    """Resolve exact approved origins; reject mixed, metadata and untrusted LAN answers."""
    trusted = [ipaddress.ip_network(value, strict=True) for value in trusted_cidrs]
    if any(network.prefixlen == 0 for network in trusted):
        raise ValueError("unrestricted trusted networks are forbidden")
    result: set[tuple[str, int]] = set()
    for origin in origins:
        url = urlsplit(origin)
        if (
            url.scheme not in {"https", "http"}
            or not url.hostname
            or url.hostname.lower().rstrip(".")
            in {"metadata.google.internal", "metadata.goog", "localhost"}
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError("egress grants must be HTTP(S) origins without credentials or paths")
        port = url.port or (443 if url.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise ValueError("invalid egress port")
        addresses = lookup(url.hostname, port)
        if not addresses:
            raise ValueError("approved origin has no DNS answers")
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                raise ValueError("metadata, loopback and reserved destinations are forbidden")
            if ip.is_unspecified or (not ip.is_global and not ip.is_private):
                raise ValueError("non-global shared destinations are forbidden")
            in_trusted_network = any(ip in network for network in trusted)
            if (ip.is_private or url.scheme == "http") and not in_trusted_network:
                raise ValueError("private or plaintext upstream requires explicit trusted CIDR")
            result.add((str(ip), port))
    return sorted(result)


def firewall_commands(destinations: list[tuple[str, int]]) -> list[list[str]]:
    """Default deny even while constructing rules; never change the host firewall."""
    commands: list[list[str]] = []
    for binary, version in (("iptables", 4), ("ip6tables", 6)):
        commands.extend(
            [
                [binary, "-w", "-P", "OUTPUT", "DROP"],
                [binary, "-w", "-F", "OUTPUT"],
                [
                    binary,
                    "-w",
                    "-A",
                    "OUTPUT",
                    "-m",
                    "conntrack",
                    "--ctstate",
                    "ESTABLISHED,RELATED",
                    "-j",
                    "ACCEPT",
                ],
            ]
        )
        if version == 4:
            for protocol in ("udp", "tcp"):
                commands.append(
                    [
                        binary,
                        "-w",
                        "-A",
                        "OUTPUT",
                        "-d",
                        "127.0.0.11",
                        "-p",
                        protocol,
                        "-m",
                        "conntrack",
                        "--ctorigdstport",
                        "53",
                        "-j",
                        "ACCEPT",
                    ]
                )
            # The unauthenticated liveliness check is the only local exception.
            for port in (4000, 4001):
                commands.append(
                    [
                        binary,
                        "-w",
                        "-A",
                        "OUTPUT",
                        "-o",
                        "lo",
                        "-d",
                        "127.0.0.1",
                        "-p",
                        "tcp",
                        "--dport",
                        str(port),
                        "-j",
                        "ACCEPT",
                    ]
                )
        for address, port in destinations:
            if ipaddress.ip_address(address).version == version:
                commands.append(
                    [
                        binary,
                        "-w",
                        "-A",
                        "OUTPUT",
                        "-d",
                        address,
                        "-p",
                        "tcp",
                        "--dport",
                        str(port),
                        "-j",
                        "ACCEPT",
                    ]
                )
        commands.append([binary, "-w", "-A", "OUTPUT", "-j", "REJECT"])
    return commands


def main() -> None:
    from pathlib import Path

    ready = Path("/tmp/egress-ready")
    ready.unlink(missing_ok=True)
    origins = json.loads(os.environ.get("LITELLM_EGRESS_ALLOWED_ORIGINS", "[]"))
    networks = json.loads(os.environ.get("LITELLM_EGRESS_TRUSTED_NETWORKS", "[]"))
    if not isinstance(origins, list) or not all(isinstance(item, str) for item in origins):
        raise ValueError("LITELLM_EGRESS_ALLOWED_ORIGINS must be a JSON string list")
    if not isinstance(networks, list) or not all(isinstance(item, str) for item in networks):
        raise ValueError("LITELLM_EGRESS_TRUSTED_NETWORKS must be a JSON string list")
    destinations = approved_destinations(origins, networks)
    # Control-plane DB access is separate from upstream model egress grants.
    database_host = os.environ.get("LITELLM_DB_HOST", "litellm-db")
    database_port = int(os.environ.get("LITELLM_DB_PORT", "5432"))
    destinations.extend(
        (address, database_port) for address in resolve_addresses(database_host, database_port)
    )
    for command in firewall_commands(destinations):
        subprocess.run(command, check=True, capture_output=True)
    ready.write_text("ready\n", encoding="utf-8")
    print("LiteLLM network namespace policy installed", flush=True)
    signal.pause()


if __name__ == "__main__":
    main()
