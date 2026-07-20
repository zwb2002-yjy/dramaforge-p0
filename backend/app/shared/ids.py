"""Identifier helpers."""

from uuid import UUID, uuid4


def new_id() -> UUID:
    """Return a new UUID4."""
    return uuid4()
