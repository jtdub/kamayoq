"""Checks of the org_id rule, on the models or on a live schema."""

from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import Connection, Inspector, MetaData, Table, Uuid, inspect

from kamayoq.db.base import ORG_ID_EXEMPT_TABLES

ORG_ID = "org_id"
ORG_ID_TARGET = "organizations.id"
LIVE_SCHEMA = "public"


@dataclass(frozen=True)
class OrgIdColumn:
    """Facts about one org_id column, from the models or from the live schema."""

    nullable: bool
    is_uuid: bool
    indexed: bool
    foreign_keys: frozenset[tuple[str, str | None]]
    """Pairs of the target column and the ON DELETE action."""


def org_id_errors(table: str, column: OrgIdColumn | None) -> list[str]:
    """Return one line for each part of a valid org_id that the table lacks."""
    if column is None:
        return [f"{table}: has no org_id column."]
    errors = []
    if column.nullable:
        errors.append(f"{table}: org_id is nullable.")
    if not column.is_uuid:
        errors.append(f"{table}: org_id is not a UUID.")
    actions = [
        action for target, action in column.foreign_keys if target == ORG_ID_TARGET
    ]
    if not actions:
        errors.append(f"{table}: org_id has no foreign key to {ORG_ID_TARGET}.")
    elif not any((action or "").upper() == "RESTRICT" for action in actions):
        errors.append(
            f"{table}: the org_id foreign key does not use ON DELETE RESTRICT."
        )
    if not column.indexed:
        errors.append(f"{table}: org_id has no index.")
    return errors


def model_org_id(table: Table) -> OrgIdColumn | None:
    """Return the org_id facts of a table in the models."""
    column = table.c.get(ORG_ID)
    if column is None:
        return None
    return OrgIdColumn(
        nullable=bool(column.nullable),
        is_uuid=isinstance(column.type, Uuid),
        indexed=any(
            [indexed.name for indexed in index.columns][:1] == [ORG_ID]
            for index in table.indexes
        ),
        foreign_keys=frozenset(
            (key.target_fullname, key.ondelete) for key in column.foreign_keys
        ),
    )


def live_org_id(inspector: Inspector, table: str) -> OrgIdColumn | None:
    """Return the org_id facts of a table in the live schema."""
    columns = {
        column["name"]: column
        for column in inspector.get_columns(table, schema=LIVE_SCHEMA)
    }
    column = columns.get(ORG_ID)
    if column is None:
        return None
    return OrgIdColumn(
        nullable=column["nullable"],
        is_uuid=isinstance(column["type"], Uuid),
        indexed=any(
            index["column_names"][:1] == [ORG_ID]
            for index in inspector.get_indexes(table, schema=LIVE_SCHEMA)
        ),
        foreign_keys=frozenset(
            (
                f"{key['referred_table']}.{','.join(key['referred_columns'])}",
                key.get("options", {}).get("ondelete"),
            )
            for key in inspector.get_foreign_keys(table, schema=LIVE_SCHEMA)
            if key["constrained_columns"] == [ORG_ID]
        ),
    )


def org_scope_errors(metadata: MetaData) -> list[str]:
    """Return one line for each defect of org_id in the models."""
    return [
        error
        for name, table in sorted(metadata.tables.items())
        if name not in ORG_ID_EXEMPT_TABLES
        for error in org_id_errors(name, model_org_id(table))
    ]


def live_org_scope_errors(connection: Connection, exempt: Collection[str]) -> list[str]:
    """Return one line for each defect of org_id in the live public schema."""
    inspector = inspect(connection)
    return [
        error
        for name in sorted(inspector.get_table_names(schema=LIVE_SCHEMA))
        if name not in exempt
        for error in org_id_errors(name, live_org_id(inspector, name))
    ]
