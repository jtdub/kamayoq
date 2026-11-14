"""Unit tests for the kamayoq settings."""

from pathlib import Path

import pytest

from kamayoq.settings import InvalidSettingsError, load_settings

DATABASE_URL = "postgresql://kamayoq:secret@db.example:5432/kamayoq"
TOML_SETTINGS = """\
host = "0.0.0.0"
port = 8001
readiness_timeout = 0.5
log_level = "warning"
api_docs = true
"""


@pytest.fixture
def database_url(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set a valid KAMAYOQ_DATABASE_URL and return it."""
    monkeypatch.setenv("KAMAYOQ_DATABASE_URL", DATABASE_URL)
    return DATABASE_URL


def config_file(monkeypatch: pytest.MonkeyPatch, path: Path, content: str) -> Path:
    """Write a TOML file, point KAMAYOQ_CONFIG_FILE at it, and return the path."""
    path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("KAMAYOQ_CONFIG_FILE", str(path))
    return path


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


def test_url_without_host_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject a Unix socket URL that has no host."""
    monkeypatch.setenv("KAMAYOQ_DATABASE_URL", "postgresql:///db?host=/run/postgresql")
    with pytest.raises(InvalidSettingsError) as error_info:
        load_settings()
    assert "- database_url (KAMAYOQ_DATABASE_URL): " in str(error_info.value)
    assert "empty host" in str(error_info.value)


@pytest.mark.parametrize(
    ("name", "value", "field"),
    [
        ("KAMAYOQ_PORT", "0", "port"),
        ("KAMAYOQ_PORT", "65536", "port"),
        ("KAMAYOQ_READINESS_TIMEOUT", "0", "readiness_timeout"),
        ("KAMAYOQ_READINESS_TIMEOUT", "-1", "readiness_timeout"),
        ("KAMAYOQ_LOG_LEVEL", "TRACE", "log_level"),
    ],
)
def test_out_of_range_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    name: str,
    value: str,
    field: str,
) -> None:
    """Reject a value outside the range of its field."""
    monkeypatch.setenv(name, value)
    with pytest.raises(InvalidSettingsError) as error_info:
        load_settings()
    assert f"- {field} ({name}): " in str(error_info.value)


@pytest.mark.parametrize(
    "name",
    [
        "KAMAYOQ_HOST",
        "KAMAYOQ_PORT",
        "KAMAYOQ_READINESS_TIMEOUT",
        "KAMAYOQ_LOG_LEVEL",
        "KAMAYOQ_API_DOCS",
        "KAMAYOQ_DATABASE_URL",
    ],
)
def test_empty_env_value_is_rejected(
    monkeypatch: pytest.MonkeyPatch, database_url: str, name: str
) -> None:
    """Reject an empty value. It does not fall back to the default."""
    monkeypatch.setenv(name, "")
    with pytest.raises(InvalidSettingsError) as error_info:
        load_settings()
    field = name.removeprefix("KAMAYOQ_").lower()
    assert f"- {field} ({name}): " in str(error_info.value)


def test_lower_case_log_level_is_accepted(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    """Change a lower-case log level to upper case."""
    monkeypatch.setenv("KAMAYOQ_LOG_LEVEL", "debug")
    assert load_settings().log_level == "DEBUG"


def test_toml_file_supplies_values(
    monkeypatch: pytest.MonkeyPatch, database_url: str, tmp_path: Path
) -> None:
    """Read each optional setting from the file in KAMAYOQ_CONFIG_FILE."""
    config_file(monkeypatch, tmp_path / "kamayoq.toml", TOML_SETTINGS)
    settings = load_settings()
    assert settings.host == "0.0.0.0"
    assert settings.port == 8001
    assert settings.readiness_timeout == 0.5
    assert settings.log_level == "WARNING"
    assert settings.api_docs is True
