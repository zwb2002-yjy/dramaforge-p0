"""One paid-create gate implementation for every BYOK media adapter."""

from __future__ import annotations

import asyncio

from app.providers.submission_gate import submission_gate


async def test_gate_is_shared_per_provider_host_and_limit() -> None:
    assert submission_gate("minimax", "https://api.example", 1) is submission_gate(
        "minimax", "https://api.example", 1
    )
    assert submission_gate("minimax", "https://api.example", 1) is not submission_gate(
        "minimax", "https://other.example", 1
    )
    assert submission_gate("minimax", "https://api.example", 1) is not submission_gate(
        "volcengine", "https://api.example", 1
    )


async def test_gate_serializes_paid_creates() -> None:
    gate = submission_gate("gate-test", "https://gate.example", 1)
    order: list[str] = []

    async def worker(index: int) -> None:
        async with gate:
            order.append(f"enter{index}")
            await asyncio.sleep(0.01)
            order.append(f"exit{index}")

    await asyncio.gather(worker(1), worker(2))

    assert order in (
        ["enter1", "exit1", "enter2", "exit2"],
        ["enter2", "exit2", "enter1", "exit1"],
    )
