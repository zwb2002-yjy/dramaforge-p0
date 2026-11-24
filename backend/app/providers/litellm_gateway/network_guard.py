"""Network-namespace ACL for the separate LiteLLM process, never a model router.

The Proxy shares this container's network namespace without NET_ADMIN. Rules
pin approved DNS answers and ports before Proxy startup; a new DNS answer is
denied until this guard is deliberately recreated. No Provider HTTP is sent.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import signal
import socket
import subprocess
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

AddressLookup = Callable[[str, int], list[str]]


def resolve_addresses(host: str, port: int) -> list[str]:
    answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(row[4][0]) for row in answers})


def _hostname(raw: str) -> str:
    if "%" in raw:
        raise ValueError("scoped addresses are not supported by the egress policy")
    host = raw.removesuffix(".").encode("idna").decode("ascii").lower()
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        if len(host) > 253 or not all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.split(".")
        ):
            raise ValueError("invalid egress hostname") from None
        return host


def approved_origin_pins(
    origins: list[str], trusted_cidrs: list[str], *, lookup: AddressLookup = resolve_addresses
) -> dict[tuple[str, int], tuple[str, ...]]:
    """Resolve exact approved origins; reject mixed, metadata and untrusted LAN answers."""
    trusted = [ipaddress.ip_network(value, strict=True) for value in trusted_cidrs]
    if any(network.prefixlen == 0 for network in trusted):
        raise ValueError("unrestricted trusted networks are forbidden")
    pins: dict[tuple[str, int], tuple[str, ...]] = {}
    answers: dict[str, tuple[str, ...]] = {}
    for origin in origins:
        url = urlsplit(origin)
        if (
            url.scheme not in {"https", "http"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError("egress grants must be HTTP(S) origins without credentials or paths")
        port = url.port if url.port is not None else (443 if url.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise ValueError("invalid egress port")
        host = _hostname(url.hostname)
        if host in {"metadata.google.internal", "metadata.goog", "localhost"}:
            raise ValueError("metadata and loopback names are not supported")
        if host not in answers:
            answers[host] = tuple(
                sorted({str(ipaddress.ip_address(ip)) for ip in lookup(host, port)})
            )
        addresses = answers[host]
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
        pins[host, port] = addresses
    return pins


def approved_destinations(
    origins: list[str], trusted_cidrs: list[str], *, lookup: AddressLookup = resolve_addresses
) -> list[tuple[str, int]]:
    pins = approved_origin_pins(origins, trusted_cidrs, lookup=lookup)
    return _destinations(pins)


def _destinations(pins: dict[tuple[str, int], tuple[str, ...]]) -> list[tuple[str, int]]:
    return sorted({(ip, port) for (_, port), ips in pins.items() for ip in ips})


def write_pinned_hosts(path: Path, pins: dict[tuple[str, int], tuple[str, ...]]) -> None:
    # The Proxy's read-only volume subpath binds this inode. Replacing the file on
    # restart would leave an already-mounted Proxy reading the old generation.
    aliases = {(host, ip) for (host, _), ips in pins.items() for ip in ips}
    lines = ["127.0.0.1 localhost", "::1 localhost ip6-localhost"]
    for host, ip in sorted(aliases):
        if host != ip:
            lines.append(f"{ip} {host} {host}.")
    content = ("\n".join(lines) + "\n").encode("ascii")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "r+b") as stream:
        stream.write(content)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())


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
    ready = Path("/tmp/egress-ready")
    ready.unlink(missing_ok=True)
    origins = json.loads(os.environ.get("LITELLM_EGRESS_ALLOWED_ORIGINS", "[]"))
    networks = json.loads(os.environ.get("LITELLM_EGRESS_TRUSTED_NETWORKS", "[]"))
    if not isinstance(origins, list) or not all(isinstance(item, str) for item in origins):
        raise ValueError("LITELLM_EGRESS_ALLOWED_ORIGINS must be a JSON string list")
    if not isinstance(networks, list) or not all(isinstance(item, str) for item in networks):
        raise ValueError("LITELLM_EGRESS_TRUSTED_NETWORKS must be a JSON string list")
    pins = approved_origin_pins(origins, networks)
    # Control-plane DB access is separate from upstream model egress grants.
    database_host = _hostname(os.environ.get("LITELLM_DB_HOST", "litellm-db"))
    database_port = int(os.environ.get("LITELLM_DB_PORT", "5432"))
    if not 1 <= database_port <= 65535:
        raise ValueError("invalid database port")
    cached = next((ips for (host, _), ips in pins.items() if host == database_host), None)
    database_addresses = cached or tuple(
        sorted(
            {
                str(ipaddress.ip_address(ip))
                for ip in resolve_addresses(database_host, database_port)
            }
        )
    )
    if not database_addresses:
        raise ValueError("database has no DNS answers")
    pins[database_host, database_port] = database_addresses
    for command in firewall_commands(_destinations(pins)):
        subprocess.run(command, check=True, capture_output=True)
    hosts_path = os.environ.get("LITELLM_PINNED_HOSTS_FILE")
    if hosts_path:
        write_pinned_hosts(Path(hosts_path), pins)
    ready.write_text("ready\n", encoding="utf-8")
    print("LiteLLM network namespace policy installed", flush=True)
    signal.pause()


if __name__ == "__main__":
    main()
