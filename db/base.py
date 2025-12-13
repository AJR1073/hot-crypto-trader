"""
Database base module.

Re-exports the SQLAlchemy Base for use in models.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""
    pass
