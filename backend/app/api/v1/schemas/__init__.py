"""API-boundary HTTP response schemas (Phase 2 §18.1).

These are pure REST response DTOs. They are constructed/validated at the API
router boundary from service/domain output. Services must remain unaware of
them. This package is deliberately separate from ``app/assets/schemas.py``,
which owns persisted/domain serialized state.
"""
