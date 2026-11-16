"""Integration tests of the models and the session on a real Postgres."""

import uuid
from collections.abc import Iterator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from scratch import ScratchBase
from sqlalchemy import Engine, MetaData, create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from kamayoq.api.app import create_app
from kamayoq.db.base import Classified, OrgScoped
from kamayoq.db.engine import get_session, to_sqlalchemy_url
from kamayoq.db.models import Base, Organization
from kamayoq.settings import Settings

ORG_ID = str(uuid.uuid4())
DbSession = Annotated[AsyncSession, Depends(get_session)]


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


def org_app(database_url: str) -> FastAPI:
    """Return the kamayoq app with one route that adds an org and one that reads it."""
    app = create_app(Settings(database_url=database_url))

    @app.post("/orgs/{name}")
    async def add_org(name: str, session: DbSession) -> dict[str, str]:
        org = Organization(name=name)
        session.add(org)
        await session.commit()
        return {"id": str(org.id)}

    @app.get("/orgs/{org_id}")
    async def read_org(org_id: uuid.UUID, session: DbSession) -> dict[str, str]:
        org = await session.get(Organization, org_id)
        assert org is not None
        return {
            "name": org.name,
            "created_at": org.created_at.isoformat(),
            "updated_at": org.updated_at.isoformat(),
        }

    return app


def test_session_dependency_inserts_and_reads_an_org(
    empty_database_url: str, sync_engine: Engine
) -> None:
    """Commit an org in one request, and read it in the next request."""
    Base.metadata.create_all(sync_engine)
    with TestClient(org_app(empty_database_url)) as client:
        org_id = uuid.UUID(client.post("/orgs/acme").json()["id"])
        org = client.get(f"/orgs/{org_id}").json()
    assert org_id.version == 7
    assert org["name"] == "acme"
    assert org["created_at"]
    assert org["updated_at"]


def test_orm_update_changes_updated_at(sync_engine: Engine) -> None:
    """Set updated_at to the time of the transaction that updates the row."""
    Base.metadata.create_all(sync_engine)
    with Session(sync_engine) as session:
        org = Organization(name="acme")
        session.add(org)
        session.commit()
        created_at = org.created_at
        assert org.updated_at == created_at
        org.name = "acme-renamed"
        session.commit()
        assert org.updated_at > created_at
