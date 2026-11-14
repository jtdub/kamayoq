"""Unit tests for the kamayoq settings."""

import pytest

from kamayoq.settings import InvalidSettingsError, load_settings

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


def test_missing_database_url_names_field_and_env_name() -> None:
    """Stop with a message that names the field and its variable."""
    with pytest.raises(InvalidSettingsError) as error_info:
        load_settings()
    assert str(error_info.value) == (
        "Settings are not valid:\n- database_url (KAMAYOQ_DATABASE_URL): Field required"
    )


def test_driver_scheme_in_database_url_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept only the libpq schemes postgres and postgresql."""
    monkeypatch.setenv("KAMAYOQ_DATABASE_URL", "postgresql+psycopg://u:p@h/db")
    with pytest.raises(InvalidSettingsError) as error_info:
        load_settings()
    assert "- database_url (KAMAYOQ_DATABASE_URL): " in str(error_info.value)
    assert "the scheme must be postgres or postgresql, not postgresql+psycopg" in str(
        error_info.value
    )


def test_error_message_and_repr_do_not_show_database_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the password out of the error message and out of repr."""
    monkeypatch.setenv("KAMAYOQ_DATABASE_URL", "postgresql+psycopg://u:SEKRET@h/db")
    with pytest.raises(InvalidSettingsError) as error_info:
        load_settings()
    assert "SEKRET" not in str(error_info.value)
    monkeypatch.setenv("KAMAYOQ_DATABASE_URL", "postgresql://u:SEKRET@h/db")
    assert "SEKRET" not in repr(load_settings())
