"""Namespace policy rejects unsafe grants before any firewall mutation."""

from __future__ import annotations

import pytest
from app.providers.litellm_gateway.network_guard import (
    approved_destinations,
    approved_origin_pins,
    firewall_commands,
    write_pinned_hosts,
)


def test_dns_pins_exact_ports_and_requires_all_answers_authorized() -> None:
    assert approved_destinations(
        ["https://models.example:8443"], [], lookup=lambda *_: ["8.8.8.8"]
    ) == [("8.8.8.8", 8443)]
    with pytest.raises(ValueError, match="trusted CIDR"):
        approved_destinations(
            ["https://models.example"], [], lookup=lambda *_: ["8.8.8.8", "10.0.0.4"]
        )


@pytest.mark.parametrize("address", ["169.254.169.254", "127.0.0.1", "100.64.0.1", "::1"])
def test_even_explicit_grants_cannot_authorize_metadata_or_shared_targets(address: str) -> None:
    with pytest.raises(ValueError):
        approved_destinations(
            ["https://unsafe.example"], ["10.0.0.0/8"], lookup=lambda *_: [address]
        )


def test_private_plaintext_target_is_an_explicit_address_and_port_grant() -> None:
    assert approved_destinations(
        ["http://local.example:8150"], ["10.0.0.4/32"], lookup=lambda *_: ["10.0.0.4"]
    ) == [("10.0.0.4", 8150)]
    with pytest.raises(ValueError, match="unrestricted"):
        approved_destinations([], ["0.0.0.0/0"])


def test_firewall_has_no_unrestricted_egress_and_covers_ipv6() -> None:
    commands = firewall_commands([("10.0.0.4", 8150)])
    assert ["iptables", "-w", "-P", "OUTPUT", "DROP"] in commands
    assert ["ip6tables", "-w", "-P", "OUTPUT", "DROP"] in commands
    assert commands[-1] == ["ip6tables", "-w", "-A", "OUTPUT", "-j", "REJECT"]
    grants = [command for command in commands if "10.0.0.4" in command]
    assert len(grants) == 1
    assert grants[0][-4:] == ["--dport", "8150", "-j", "ACCEPT"]


def test_proxy_name_pins_use_the_same_answers_as_both_port_grants(tmp_path):
    calls = []

    def lookup(host, port):
        calls.append((host, port))
        return ["8.8.8.8", "2001:4860:4860::8888", "8.8.8.8"]

    pins = approved_origin_pins(
        ["https://Media.Example.:8443", "https://media.example:8444"], [], lookup=lookup
    )
    assert calls == [("media.example", 8443)]
    assert pins == {
        ("media.example", port): ("2001:4860:4860::8888", "8.8.8.8") for port in (8443, 8444)
    }
    hosts = tmp_path / "hosts"
    write_pinned_hosts(hosts, pins)
    assert hosts.read_text().splitlines() == [
        "127.0.0.1 localhost",
        "::1 localhost ip6-localhost",
        "2001:4860:4860::8888 media.example media.example.",
        "8.8.8.8 media.example media.example.",
    ]
    inode = hosts.stat().st_ino
    write_pinned_hosts(hosts, {("db", 5432): ("10.0.0.8",)})
    assert hosts.stat().st_ino == inode
    assert hosts.read_text().splitlines() == [
        "127.0.0.1 localhost",
        "::1 localhost ip6-localhost",
        "10.0.0.8 db db.",
    ]


def test_unusable_hostnames_cannot_become_additional_hosts_entries():
    with pytest.raises(ValueError, match="port"):
        approved_origin_pins(["https://approved.example:0"], [], lookup=lambda *_: ["8.8.8.8"])
    with pytest.raises(ValueError, match="hostname"):
        approved_origin_pins(["https://bad alias.example"], [], lookup=lambda *_: ["8.8.8.8"])
