"""Declarative base, naming conventions and reusable column mixins.

Two things here matter beyond boilerplate:

* **Constraint naming convention.** Without it, Alembic autogenerate emits migrations
  that cannot drop unnamed constraints, and every database ends up with different
  server-generated names. Set once, forever.
* **Timestamps are database-generated** (``now()``), not Python-generated, so that
  values are consistent across application instances and correct for rows touched by
  migrations or manual SQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.ids import uuid7

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for every ORM model.

    Models must be imported by ``app.db.registry`` so that Alembic autogenerate and
    ``Base.metadata`` see them.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # Fetch server-generated values (``created_at``/``updated_at``) with RETURNING as
    # part of the INSERT/UPDATE itself. Without this, touching ``updated_at`` after a
    # flush triggers a lazy refresh -- which under asyncio raises MissingGreenlet
    # instead of quietly issuing a second query.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy contract

    def __repr__(self) -> str:
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


class UUIDPrimaryKeyMixin:
    """UUIDv7 primary keys: globally unique, safe to expose, and time-ordered.

    Time ordering matters -- random UUIDv4 keys fragment B-tree indexes and make
    insert-heavy tables progressively slower. UUIDv7 keeps insertions at the right edge
    of the index while remaining opaque enough not to leak row counts the way a serial
    integer does.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        primary_key=True,
        default=uuid7,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Opt-in. Only add it where the product genuinely requires recoverable deletes --
    every query against the table then has to filter ``deleted_at IS NULL``."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


def as_dict(instance: Base) -> dict[str, Any]:
    """Debug/logging helper. Not a serialisation layer -- Pydantic schemas do that."""
    return {c.key: getattr(instance, c.key) for c in instance.__table__.columns}
