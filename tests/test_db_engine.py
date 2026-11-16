"""Unit tests for the async database engine and its place in the app."""

import pytest

from kamayoq.db.engine import sqlalchemy_url, to_sqlalchemy_url
from kamayoq.settings import Settings

PASSWORD = "SEKRET-pw"


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
