"""Async database engine and the session of each request."""

from sqlalchemy.engine import URL, make_url

from kamayoq.settings import Settings

DRIVER_NAME = "postgresql+psycopg"


def to_sqlalchemy_url(libpq_url: str) -> URL:
    """Return the SQLAlchemy URL of a libpq URL, with the psycopg driver."""
    return make_url(libpq_url).set(drivername=DRIVER_NAME)


def sqlalchemy_url(settings: Settings) -> URL:
    """Return the SQLAlchemy URL of the database in the settings."""
    return to_sqlalchemy_url(str(settings.database_url))
