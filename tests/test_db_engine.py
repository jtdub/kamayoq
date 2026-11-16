"""Unit tests for the async database engine and its place in the app."""

import psycopg
import pytest
from sqlalchemy.exc import DBAPIError, StatementError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from kamayoq.api.app import create_app
from kamayoq.db.engine import create_db_engine, sqlalchemy_url, to_sqlalchemy_url
from kamayoq.settings import Settings

PASSWORD = "SEKRET-pw"
ROW_VALUE = "SECRET-row-value"


@pytest.mark.parametrize("scheme", ["postgresql", "postgres"])
def test_sqlalchemy_url_uses_psycopg_driver_and_hides_password(scheme: str) -> None:
    """Change a libpq URL to the psycopg driver, and hide the password."""
    url = to_sqlalchemy_url(f"{scheme}://u:{PASSWORD}@h:5/d")
    assert url.drivername == "postgresql+psycopg"
    assert url.password == PASSWORD
    assert repr(url) == "postgresql+psycopg://u:***@h:5/d"
    assert PASSWORD not in url.render_as_string()
    settings = Settings(database_url=f"{scheme}://u:{PASSWORD}@h:5/d")
    assert sqlalchemy_url(settings) == url


def test_create_app_does_not_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the engine and the session maker with no database connection."""

    async def fail_connect(*args: object, **kwargs: object) -> None:
        pytest.fail("create_app opened a database connection")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", fail_connect)
    app = create_app(Settings(database_url=f"postgresql://u:{PASSWORD}@h:5/d"))
    assert isinstance(app.state.engine, AsyncEngine)
    assert isinstance(app.state.sessionmaker, async_sessionmaker)
    assert app.state.sessionmaker.kw["bind"] is app.state.engine
    assert app.state.sessionmaker.kw["expire_on_commit"] is False


def test_statement_error_hides_parameters() -> None:
    """Keep the bound values of a statement out of a database error."""
    engine = create_db_engine(to_sqlalchemy_url("postgresql://u@h:5/d")).sync_engine
    assert engine.hide_parameters is True
    error = DBAPIError.instance(
        "INSERT INTO notes (body) VALUES (%(body)s)",
        {"body": ROW_VALUE},
        ValueError("cannot adapt the value"),
        psycopg.Error,
        hide_parameters=engine.hide_parameters,
        dialect=engine.dialect,
    )
    assert isinstance(error, StatementError)
    assert "SQL parameters hidden" in str(error)
    assert ROW_VALUE not in str(error)
