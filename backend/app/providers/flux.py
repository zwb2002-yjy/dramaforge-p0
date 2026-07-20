"""Flux image adapter. Real BYOK path is optional; default export is FakeFluxAdapter."""

from app.providers.fake import FakeFluxAdapter

# S2 real adapter lands when BYOK authorized; local READY uses fake.
FluxAdapter = FakeFluxAdapter
