"""Shared SQLAlchemy metadata; domain mappings register against this base."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
