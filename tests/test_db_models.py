"""Unit tests for the org_id and data_class rules of the kamayoq models."""

import json
import subprocess
import sys
from collections.abc import Iterator
from typing import Any

import pytest
from db_rules import classification_errors, org_scope_errors
from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table, Uuid, create_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.schema import CreateTable

from kamayoq.db.base import (
    NAMING_CONVENTION,
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


class ScratchBase(DeclarativeBase):
    """Hold the test models, so that Base.metadata holds only the real tables."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


@pytest.fixture(autouse=True)
def scratch_metadata() -> Iterator[MetaData]:
    """Give each test a ScratchBase with a copy of organizations only."""
    Base.metadata.tables["organizations"].to_metadata(ScratchBase.metadata)
    yield ScratchBase.metadata
    ScratchBase.registry.dispose()
    ScratchBase.metadata.clear()


def org_table(metadata: MetaData, name: str, *org_id: Column[Any]) -> Table:
    """Add a table with a primary key and the given org_id column."""
    return Table(name, metadata, Column("id", Integer, primary_key=True), *org_id)


def test_each_table_has_a_valid_org_id() -> None:
    """Report no error for the tables of Base.metadata."""
    assert org_scope_errors(Base.metadata) == []


def test_org_scope_errors_report_each_missing_part(
    scratch_metadata: MetaData,
) -> None:
    """Name each table and each part of org_id that it lacks."""
    org_table(scratch_metadata, "no_org_id")
    org_table(
        scratch_metadata,
        "nullable_org_id",
        Column(
            "org_id",
            Uuid,
            ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
    )
    org_table(
        scratch_metadata,
        "integer_org_id",
        Column(
            "org_id",
            Integer,
            ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
    )
    org_table(
        scratch_metadata,
        "no_foreign_key",
        Column("org_id", Uuid, nullable=False, index=True),
    )
    org_table(
        scratch_metadata,
        "no_restrict",
        Column(
            "org_id",
            Uuid,
            ForeignKey("organizations.id"),
            nullable=False,
            index=True,
        ),
    )
    org_table(
        scratch_metadata,
        "no_index",
        Column(
            "org_id",
            Uuid,
            ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )
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
