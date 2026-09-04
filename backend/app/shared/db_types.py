"""Shared SQLAlchemy types whose PostgreSQL representation is migration-owned.

The application models intentionally use one type object for each primitive
that has a PostgreSQL-specific historical representation.  ``JSON_DOCUMENT``
keeps the portable JSON behavior used by local/unit databases while compiling
to PostgreSQL's JSONB, matching the existing migrations.  The fixed-width
character aliases make the ORM authority explicit for hashes and currency
codes instead of relying on a length-limited ``String`` approximation.
"""

from __future__ import annotations

from sqlalchemy import CHAR, JSON
from sqlalchemy.dialects.postgresql import JSONB

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
HASH_64 = CHAR(64)
CURRENCY_CODE = CHAR(3)

__all__ = ["CURRENCY_CODE", "HASH_64", "JSON_DOCUMENT"]
