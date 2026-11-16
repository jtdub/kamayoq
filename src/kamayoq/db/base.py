"""Declarative base and column mixins of the kamayoq models.

Each table carries an org_id, through OrgScoped. The organizations table is the only
exception. Each table that holds content carries a data_class, through Classified.
"""

import enum
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, MetaData, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
"""Constraint and index names, so that each migration gives the same names."""

ORG_ID_EXEMPT_TABLES = frozenset({"organizations"})
"""Tables that have no org_id column."""

UNCLASSIFIED_TABLES: Mapping[str, str] = {
    "organizations": "Holds the org name only, not content.",
}
"""Tables with no data_class column, each with the reason that it holds no content."""


class DataClass(StrEnum):
    """Class of the data that a record holds, from the least to the most strict."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PHI = "phi"


def enum_values(enum_class: type[enum.Enum]) -> Sequence[str]:
    """Return the value of each member, so that the database stores the values."""
    return [member.value for member in enum_class]


class Base(DeclarativeBase):
    """Declarative base of each kamayoq model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class RecordColumns:
    """Add a UUIDv7 id and the created_at and updated_at timestamps.

    The database sets each value. The ORM also sets updated_at on each update.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.uuidv7()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OrgScoped(RecordColumns):
    """Add the record columns and an org_id that points to organizations.id."""

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )


class Classified:
    """Add a NOT NULL data_class with no default.

    Each table that holds content uses this mixin, so that each writer must choose a
    class. The database rejects a value that is not a DataClass value.
    """

    data_class: Mapped[DataClass] = mapped_column(
        Enum(
            DataClass,
            name="data_class",
            native_enum=False,
            create_constraint=True,
            length=32,
            values_callable=enum_values,
        )
    )
