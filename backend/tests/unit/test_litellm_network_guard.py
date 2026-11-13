"""Namespace policy rejects unsafe grants before any firewall mutation."""

from __future__ import annotations

import pytest
from app.providers.litellm_gateway.network_guard import approved_destinations, firewall_commands


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
