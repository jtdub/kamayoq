"""Unit tests for the kamayoq settings."""

import pytest

from kamayoq.settings import load_settings

DATABASE_URL = "postgresql://kamayoq:secret@db.example:5432/kamayoq"


@pytest.fixture
def database_url(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set a valid KAMAYOQ_DATABASE_URL and return it."""
    monkeypatch.setenv("KAMAYOQ_DATABASE_URL", DATABASE_URL)
    return DATABASE_URL


def test_defaults_apply_when_only_database_url_is_set(database_url: str) -> None:
    """Use the documented default for each optional setting."""
    settings = load_settings()
    assert str(settings.database_url) == database_url
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.readiness_timeout == 2.0
    assert settings.log_level == "INFO"
    assert settings.api_docs is False
