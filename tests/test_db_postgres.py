"""Integration tests of the models and the session on a real Postgres."""

import uuid
from collections.abc import Iterator

import pytest
from scratch import ScratchBase
from sqlalchemy import Engine, MetaData, create_engine, text
from sqlalchemy.exc import IntegrityError

from kamayoq.db.base import Classified, OrgScoped
from kamayoq.db.engine import to_sqlalchemy_url

ORG_ID = str(uuid.uuid4())


@pytest.fixture
def sync_engine(empty_database_url: str) -> Iterator[Engine]:
    """Yield a sync psycopg engine for the empty database."""
    engine = create_engine(to_sqlalchemy_url(empty_database_url))
    yield engine
    engine.dispose()


@pytest.fixture
def scratch_schema(scratch_metadata: MetaData, sync_engine: Engine) -> Engine:
    """Create organizations and one classified org-scoped table, with one org."""

    class Note(Classified, OrgScoped, ScratchBase):
        __tablename__ = "notes"

    scratch_metadata.create_all(sync_engine)
    with sync_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, 'acme')"),
            {"id": ORG_ID},
        )
    return sync_engine


def insert_note(engine: Engine, data_class: str | None) -> None:
    """Insert one note of the org, with this data_class, or with none."""
    columns, values = ("org_id", ":org_id")
    if data_class is not None:
        columns, values = ("org_id, data_class", ":org_id, :data_class")
    with engine.begin() as connection:
        connection.execute(
            text(f"INSERT INTO notes ({columns}) VALUES ({values})"),
            {"org_id": ORG_ID, "data_class": data_class},
        )


def test_delete_of_referenced_org_fails(scratch_schema: Engine) -> None:
    """Refuse to delete an org while a row points to it."""
    insert_note(scratch_schema, "internal")
    with (
        pytest.raises(IntegrityError, match="fk_notes_org_id_organizations"),
        scratch_schema.begin() as connection,
    ):
        connection.execute(text("DELETE FROM organizations"))


@pytest.mark.parametrize(
    ("data_class", "violation"),
    [("secret", "ck_notes_data_class"), (None, "not-null constraint")],
)
def test_database_rejects_unknown_or_missing_data_class(
    scratch_schema: Engine, data_class: str | None, violation: str
) -> None:
    """Reject a data_class that is not in the list, and a NULL data_class."""
    insert_note(scratch_schema, "phi")
    with pytest.raises(IntegrityError, match=violation):
        insert_note(scratch_schema, data_class)
