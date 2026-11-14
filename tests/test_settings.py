"""Unit tests for the kamayoq settings."""

import os
from collections.abc import Callable
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


def empty_config_file_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """Set KAMAYOQ_CONFIG_FILE to an empty value."""
    monkeypatch.setenv("KAMAYOQ_CONFIG_FILE", "")
    return (
        "KAMAYOQ_CONFIG_FILE is empty. Unset it, or set it to the path of a TOML file."
    )


def missing_config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """Point KAMAYOQ_CONFIG_FILE at a path that does not exist."""
    path = tmp_path / "nope.toml"
    monkeypatch.setenv("KAMAYOQ_CONFIG_FILE", str(path))
    return f"KAMAYOQ_CONFIG_FILE names {path.resolve()}, which is not a file."


def directory_config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """Point KAMAYOQ_CONFIG_FILE at a directory."""
    monkeypatch.setenv("KAMAYOQ_CONFIG_FILE", str(tmp_path))
    return f"KAMAYOQ_CONFIG_FILE names {tmp_path.resolve()}, which is not a file."


def invalid_toml_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """Write a file with a TOML syntax error."""
    path = config_file(monkeypatch, tmp_path / "kamayoq.toml", "port = \n")
    return f"{path.resolve()} is not valid TOML: "


def non_utf8_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """Write a file that is not UTF-8 text."""
    path = config_file(monkeypatch, tmp_path / "kamayoq.toml", "")
    path.write_bytes(b'host = "\xff"\n')
    return f"{path.resolve()} is not UTF-8 text."


def unreadable_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """Write a file that the process cannot read."""
    path = config_file(monkeypatch, tmp_path / "kamayoq.toml", TOML_SETTINGS)
    path.chmod(0)
    return f"cannot read {path.resolve()}: Permission denied"


def table_in_toml_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """Write a file that puts a setting in a table."""
    config_file(monkeypatch, tmp_path / "kamayoq.toml", "[server]\nport = 8001\n")
    return "- server (KAMAYOQ_SERVER): Extra inputs are not permitted"


def unknown_key_in_toml_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """Write a file with a key that is not a setting."""
    config_file(monkeypatch, tmp_path / "kamayoq.toml", 'colour = "red"\n')
    return "- colour (KAMAYOQ_COLOUR): Extra inputs are not permitted"


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


def test_env_value_wins_over_toml_value(
    monkeypatch: pytest.MonkeyPatch, database_url: str, tmp_path: Path
) -> None:
    """Use the environment variable when the TOML file has the same setting."""
    config_file(monkeypatch, tmp_path / "kamayoq.toml", TOML_SETTINGS)
    monkeypatch.setenv("KAMAYOQ_PORT", "9000")
    assert load_settings().port == 9000


@pytest.mark.parametrize(
    "write_case",
    [
        empty_config_file_env,
        missing_config_file,
        directory_config_file,
        invalid_toml_file,
        non_utf8_file,
        pytest.param(
            unreadable_file,
            marks=pytest.mark.skipif(
                os.geteuid() == 0, reason="root can read a file with mode 0"
            ),
        ),
        table_in_toml_file,
        unknown_key_in_toml_file,
    ],
)
def test_config_file_errors_name_the_problem(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    tmp_path: Path,
    write_case: Callable[[pytest.MonkeyPatch, Path], str],
) -> None:
    """Stop with a message that names the problem with the config file."""
    expected = write_case(monkeypatch, tmp_path)
    with pytest.raises(InvalidSettingsError) as error_info:
        load_settings()
    assert expected in str(error_info.value)
