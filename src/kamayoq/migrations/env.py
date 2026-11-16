"""Alembic environment of kamayoq. It runs the migrations online, with asyncio.

A caller can give the libpq URL in config.attributes["database_url"]. Otherwise the
URL comes from the kamayoq settings, and the logs go to stderr as JSON.
"""

import asyncio

from alembic import context
from alembic.util import CommandError
from sqlalchemy import Connection
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from kamayoq.db.engine import create_db_engine, sqlalchemy_url, to_sqlalchemy_url
from kamayoq.db.models import Base
from kamayoq.log import configure_logging
from kamayoq.settings import InvalidSettingsError, load_settings

DATABASE_URL_ATTRIBUTE = "database_url"
OFFLINE_MODE_MESSAGE = "kamayoq does not support offline mode (--sql)."

config = context.config
target_metadata = Base.metadata


def database_url() -> URL:
    """Return the SQLAlchemy URL of the database to migrate.

    Raises:
        CommandError: If the settings are not valid.
    """
    if DATABASE_URL_ATTRIBUTE in config.attributes:
        return to_sqlalchemy_url(config.attributes[DATABASE_URL_ATTRIBUTE])
    try:
        settings = load_settings()
    except InvalidSettingsError as error:
        raise CommandError(str(error)) from None
    configure_logging(settings.log_level)
    return sqlalchemy_url(settings)


def do_run_migrations(connection: Connection) -> None:
    """Run the migrations on one connection, in one transaction."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Connect with a new engine, run the migrations, and dispose of the engine."""
    engine = create_db_engine(database_url(), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise CommandError(OFFLINE_MODE_MESSAGE)
asyncio.run(run_async_migrations())
