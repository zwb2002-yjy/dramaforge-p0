"""Per-process paid-create gate shared by every BYOK media adapter.

Worker slots bound how many media jobs run, not how many Provider ``create``
requests are in flight for one connection/host. Agnes had its own gate while
MiniMax and Ark had none; this module is the single implementation, keyed by
provider and normalized host so different connections do not share a quota by
accident.
"""

from __future__ import annotations

import asyncio
from weakref import WeakKeyDictionary

_GATES: WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[tuple[str, str, int], asyncio.Semaphore]
] = WeakKeyDictionary()


def submission_gate(provider: str, host: str, limit: int) -> asyncio.Semaphore:
    """Return the per-loop create gate for one provider host."""
    loop = asyncio.get_running_loop()
    gates = _GATES.setdefault(loop, {})
    key = (provider, host, limit)
    gate = gates.get(key)
    if gate is None:
        gate = asyncio.Semaphore(limit)
        gates[key] = gate
    return gate
