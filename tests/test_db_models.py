"""Unit tests for the org_id and data_class rules of the kamayoq models."""

import json
import subprocess
import sys
from typing import Any

from db_rules import classification_errors, org_scope_errors
from scratch import ScratchBase
from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    create_engine,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import CreateTable
from sqlalchemy.types import TypeEngine

from kamayoq.db.base import (
    Classified,
    DataClass,
    OrgScoped,
    RecordColumns,
)
from kamayoq.db.models import Base

PRINT_MAPPED_TABLES = """
import importlib
import json
import pkgutil
import sys

import kamayoq
from kamayoq.db.models import Base

if sys.argv[1:] == ["--all-modules"]:
    for module in pkgutil.walk_packages(kamayoq.__path__, "kamayoq."):
        if not module.name.startswith("kamayoq.migrations"):
            importlib.import_module(module.name)
print(json.dumps(sorted(Base.metadata.tables)))
"""
"""Child script that prints the names of the tables in Base.metadata."""


def restrict() -> ForeignKey:
    """Return a foreign key to organizations.id with ON DELETE RESTRICT."""
    return ForeignKey("organizations.id", ondelete="RESTRICT")


def org_id(
    *foreign_key: ForeignKey,
    type_: type[TypeEngine[Any]] = Uuid,
    nullable: bool = False,
    index: bool = True,
) -> Column[Any]:
    """Return an org_id column with the given parts."""
    return Column("org_id", type_, *foreign_key, nullable=nullable, index=index)


def org_table(metadata: MetaData, name: str, *columns: Column[Any]) -> Table:
    """Add a table with an integer primary key and the given columns."""
    return Table(name, metadata, Column("id", Integer, primary_key=True), *columns)


def test_each_table_has_a_valid_org_id() -> None:
    """Report no error for the tables of Base.metadata."""
    assert org_scope_errors(Base.metadata) == []


def test_org_scope_errors_report_each_missing_part(
    scratch_metadata: MetaData,
) -> None:
    """Name each table and each part of org_id that it lacks."""
    org_table(scratch_metadata, "no_org_id")
    org_table(scratch_metadata, "nullable_org_id", org_id(restrict(), nullable=True))
    org_table(scratch_metadata, "integer_org_id", org_id(restrict(), type_=Integer))
    org_table(scratch_metadata, "no_foreign_key", org_id())
    org_table(scratch_metadata, "no_restrict", org_id(ForeignKey("organizations.id")))
    org_table(scratch_metadata, "no_index", org_id(restrict(), index=False))
    assert org_scope_errors(scratch_metadata) == [
        "integer_org_id: org_id is not a UUID.",
        "no_foreign_key: org_id has no foreign key to organizations.id.",
        "no_index: org_id has no index.",
        "no_org_id: has no org_id column.",
        "no_restrict: the org_id foreign key does not use ON DELETE RESTRICT.",
        "nullable_org_id: org_id is nullable.",
    ]


def test_org_scoped_mixin_gives_a_valid_org_id(scratch_metadata: MetaData) -> None:
    """Report no error for a model that uses OrgScoped."""

    class Note(OrgScoped, ScratchBase):
        __tablename__ = "notes"

    assert org_scope_errors(scratch_metadata) == []


def test_composite_constraints_that_start_with_org_id_get_distinct_names(
    scratch_metadata: MetaData,
) -> None:
    """Name each unique constraint and each index after all of its columns."""

    class Note(OrgScoped, ScratchBase):
        __tablename__ = "notes"
        __table_args__ = (
            UniqueConstraint("org_id", "title"),
            UniqueConstraint("org_id", "slug"),
            Index(None, "org_id", "title"),
            Index(None, "org_id", "slug"),
        )

        title: Mapped[str] = mapped_column(String(200))
        slug: Mapped[str] = mapped_column(String(200))

    notes = scratch_metadata.tables["notes"]
    unique_names = sorted(
        str(constraint.name)
        for constraint in notes.constraints
        if isinstance(constraint, UniqueConstraint)
    )
    assert unique_names == ["uq_notes_org_id_slug", "uq_notes_org_id_title"]
    assert sorted(str(index.name) for index in notes.indexes) == [
        "ix_notes_org_id",
        "ix_notes_org_id_notes_slug",
        "ix_notes_org_id_notes_title",
    ]


def test_data_class_values_are_the_four_classes() -> None:
    """Give the four data classes, from the least to the most strict."""
    assert [member.value for member in DataClass] == [
        "public",
        "internal",
        "confidential",
        "phi",
    ]


def test_classified_column_is_not_null_varchar_with_check(
    scratch_metadata: MetaData,
) -> None:
    """Make data_class a NOT NULL VARCHAR(32) with a CHECK and no default."""

    class Note(Classified, RecordColumns, ScratchBase):
        __tablename__ = "notes"

    notes = scratch_metadata.tables["notes"]
    column = notes.c.data_class
    dialect = create_engine("postgresql+psycopg://").dialect
    assert column.nullable is False
    assert column.default is None
    assert column.server_default is None
    assert column.type.compile(dialect=dialect) == "VARCHAR(32)"
    assert (
        "CONSTRAINT ck_notes_data_class CHECK (data_class IN "
        "('public', 'internal', 'confidential', 'phi'))"
    ) in str(CreateTable(notes).compile(dialect=dialect))


def test_each_table_is_classified_or_listed() -> None:
    """Report no error for the tables of Base.metadata."""
    assert classification_errors(Base.metadata) == []


def test_classification_errors_report_an_unlisted_table(
    scratch_metadata: MetaData,
) -> None:
    """Name a table that has no data_class and no entry in UNCLASSIFIED_TABLES."""

    class Note(OrgScoped, ScratchBase):
        __tablename__ = "notes"

    class ClassifiedNote(Classified, OrgScoped, ScratchBase):
        __tablename__ = "classified_notes"

    assert classification_errors(scratch_metadata) == [
        "notes: has no data_class column from Classified,"
        " and UNCLASSIFIED_TABLES does not list it.",
    ]


def mapped_tables(*args: str) -> list[str]:
    """Return the tables that a child process finds in Base.metadata."""
    result = subprocess.run(
        [sys.executable, "-c", PRINT_MAPPED_TABLES, *args],
        capture_output=True,
        text=True,
        check=True,
    )
    tables: list[str] = json.loads(result.stdout)
    return tables


def test_each_mapped_table_is_reachable_from_models() -> None:
    """Map no table that an import of kamayoq.db.models alone does not map."""
    from_models = mapped_tables()
    assert "organizations" in from_models
    assert mapped_tables("--all-modules") == from_models
