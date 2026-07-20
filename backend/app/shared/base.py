"""SQLAlchemy declarative base shell (models arrive with stage migrations)."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root declarative base for all ORM models."""
