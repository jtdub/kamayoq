"""Integration tests of the Alembic migrations on a real Postgres 18."""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from db_rules import live_org_scope_errors
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

import kamayoq.api.health
from kamayoq.api.app import create_app
from kamayoq.db.base import ORG_ID_EXEMPT_TABLES
from kamayoq.db.engine import get_session, to_sqlalchemy_url
from kamayoq.db.models import DEFAULT_ORG_ID, DEFAULT_ORG_NAME, Base, Organization
from kamayoq.settings import Settings

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"
LIVE_CHECK_EXEMPT = ORG_ID_EXEMPT_TABLES | {"alembic_version"}


@pytest.fixture
def alembic_config(empty_database_url: str) -> Config:
    """Return the Alembic config with the URL of the empty database."""
    return Config(ALEMBIC_INI, attributes={"database_url": empty_database_url})


@pytest.fixture
def sync_engine(empty_database_url: str) -> Iterator[Engine]:
    """Yield a sync psycopg engine for the empty database."""
    engine = create_engine(to_sqlalchemy_url(empty_database_url))
    yield engine
    engine.dispose()


@pytest.fixture
def migrated(alembic_config: Config, sync_engine: Engine) -> Engine:
    """Upgrade the empty database to head, and return its sync engine."""
    command.upgrade(alembic_config, "head")
    return sync_engine


def test_upgrade_head_from_empty_database_creates_default_org(
    migrated: Engine,
) -> None:
    """Insert one default org on the first upgrade."""
    with migrated.connect() as connection:
        rows = connection.execute(text("SELECT id, name FROM organizations")).all()
    assert [tuple(row) for row in rows] == [(DEFAULT_ORG_ID, DEFAULT_ORG_NAME)]


def test_each_public_table_has_org_id_after_upgrade(migrated: Engine) -> None:
    """Find no defect after the upgrade, and report a table with no org_id."""
    with migrated.begin() as connection:
        assert live_org_scope_errors(connection, LIVE_CHECK_EXEMPT) == []
        connection.execute(text("CREATE TABLE stray (id int)"))
        errors = live_org_scope_errors(connection, LIVE_CHECK_EXEMPT)
    assert errors == ["stray: has no org_id column."]


def test_app_loggers_work_after_migration(alembic_config: Config) -> None:
    """Keep the app loggers on and the root handlers as they were."""
    root_handlers = list(logging.getLogger().handlers)
    command.upgrade(alembic_config, "head")
    assert logging.getLogger(kamayoq.api.health.__name__).disabled is False
    assert logging.getLogger().handlers == root_handlers


def test_migrations_match_models(migrated: Engine) -> None:
    """Find no difference between the migrated schema and the models."""
    with migrated.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        )
        assert compare_metadata(context, Base.metadata) == []


def test_org_without_id_gets_uuidv7_from_migrated_schema(migrated: Engine) -> None:
    """Fill id with a UUIDv7 and created_at with now() in raw SQL."""
    with migrated.begin() as connection:
        row = connection.execute(
            text(
                "INSERT INTO organizations (name) VALUES ('x') RETURNING id, created_at"
            )
        ).one()
    assert row.id.version == 7
    assert row.created_at is not None


def test_downgrade_base_then_upgrade_again(
    alembic_config: Config, migrated: Engine
) -> None:
    """Remove each kamayoq table on downgrade, and upgrade again."""
    command.downgrade(alembic_config, "base")
    with migrated.connect() as connection:
        tables = inspect(connection).get_table_names(schema="public")
        versions = connection.execute(text("SELECT count(*) FROM alembic_version"))
        assert tables == ["alembic_version"]
        assert versions.scalar_one() == 0
    command.upgrade(alembic_config, "head")
    with migrated.connect() as connection:
        names = connection.execute(text("SELECT name FROM organizations")).scalars()
        assert list(names) == [DEFAULT_ORG_NAME]


def test_session_dependency_reads_default_org(
    empty_database_url: str, migrated: Engine
) -> None:
    """Read the default org through get_session after the upgrade."""
    app = create_app(Settings(database_url=empty_database_url))

    @app.get("/default-org")
    async def read_default_org(
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> dict[str, str]:
        org = await session.get(Organization, DEFAULT_ORG_ID)
        assert org is not None
        return {"id": str(org.id), "name": org.name}

    with TestClient(app) as client:
        body = client.get("/default-org").json()
    assert body == {"id": str(DEFAULT_ORG_ID), "name": DEFAULT_ORG_NAME}
