"""Async database engine and the session of each request."""

from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from kamayoq.settings import Settings

DRIVER_NAME = "postgresql+psycopg"


def to_sqlalchemy_url(libpq_url: str) -> URL:
    """Return the SQLAlchemy URL of a libpq URL, with the psycopg driver."""
    return make_url(libpq_url).set(drivername=DRIVER_NAME)


def sqlalchemy_url(settings: Settings) -> URL:
    """Return the SQLAlchemy URL of the database in the settings."""
    return to_sqlalchemy_url(str(settings.database_url))


def create_db_engine(url: URL, **options: Any) -> AsyncEngine:
    """Return an async engine. It does not connect until the first query."""
    return create_async_engine(url, **options)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return a session maker that keeps the loaded values after a commit."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield one session for the request.

    The dependency does not commit. A route that writes calls commit. The close of
    the session rolls back a transaction that is still open.
    """
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session
