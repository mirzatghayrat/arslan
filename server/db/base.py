from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared registry for legacy and companion persistence."""
