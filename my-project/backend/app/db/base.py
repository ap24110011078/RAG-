"""SQLAlchemy declarative base and shared column helpers."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, mapped_column, MappedColumn
from sqlalchemy.dialects.postgresql import UUID


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models.

    All tables automatically receive:
    - ``id``         — UUID primary key generated on the Python side.
    - ``created_at`` — timestamp set by the database on INSERT.
    - ``updated_at`` — timestamp updated by the database on every UPDATE.
    """

    # ------------------------------------------------------------------ #
    # Shared primary key                                                   #
    # ------------------------------------------------------------------ #
    id: MappedColumn[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )

    # ------------------------------------------------------------------ #
    # Audit timestamps (server-side, timezone-aware)                       #
    # ------------------------------------------------------------------ #
    created_at: MappedColumn[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: MappedColumn[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
