"""Unit tests for the kamayoq settings."""

import os
from pathlib import Path

import pytest

from kamayoq.settings import ENV_PREFIX, InvalidSettingsError, Settings, load_settings

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


def load_error() -> str:
    """Return the message of the InvalidSettingsError that load_settings raises."""
    with pytest.raises(InvalidSettingsError) as error_info:
        load_settings()
    return str(error_info.value)


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
    assert load_error() == (
        "Settings are not valid:\n- database_url (KAMAYOQ_DATABASE_URL): Field required"
    )


def test_driver_scheme_in_database_url_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept only the libpq schemes postgres and postgresql."""
    monkeypatch.setenv("KAMAYOQ_DATABASE_URL", "postgresql+psycopg://u:p@h/db")
    message = load_error()
    assert "- database_url (KAMAYOQ_DATABASE_URL): " in message
    assert (
        "the scheme must be postgres or postgresql, not postgresql+psycopg" in message
    )


def test_error_message_and_repr_do_not_show_database_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the password out of the error message and out of repr."""
    monkeypatch.setenv("KAMAYOQ_DATABASE_URL", "postgresql+psycopg://u:SEKRET@h/db")
    assert "SEKRET" not in load_error()
    monkeypatch.setenv("KAMAYOQ_DATABASE_URL", "postgresql://u:SEKRET@h/db")
    assert "SEKRET" not in repr(load_settings())


def test_url_without_host_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject a Unix socket URL that has no host."""
    monkeypatch.setenv("KAMAYOQ_DATABASE_URL", "postgresql:///db?host=/run/postgresql")
    message = load_error()
    assert "- database_url (KAMAYOQ_DATABASE_URL): " in message
    assert "empty host" in message


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("port", "0"),
        ("port", "65536"),
        ("readiness_timeout", "0"),
        ("readiness_timeout", "-1"),
        ("log_level", "TRACE"),
    ],
)
def test_out_of_range_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, database_url: str, field: str, value: str
) -> None:
    """Reject a value outside the range of its field."""
    name = ENV_PREFIX + field.upper()
    monkeypatch.setenv(name, value)
    assert f"- {field} ({name}): " in load_error()


@pytest.mark.parametrize("field", list(Settings.model_fields))
def test_empty_env_value_is_rejected(
    monkeypatch: pytest.MonkeyPatch, database_url: str, field: str
) -> None:
    """Reject an empty value. It does not fall back to the default."""
    name = ENV_PREFIX + field.upper()
    monkeypatch.setenv(name, "")
    assert f"- {field} ({name}): " in load_error()


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


NOT_A_FILE = "KAMAYOQ_CONFIG_FILE names {path}, which is not a file."
EXTRA = "Extra inputs are not permitted"
EMPTY = "KAMAYOQ_CONFIG_FILE is empty. Unset it, or set it to the path of a TOML file."
UNREADABLE = "unreadable.toml"


@pytest.mark.parametrize(
    ("file_name", "content", "expected"),
    [
        ("", None, EMPTY),
        ("nope.toml", None, NOT_A_FILE),
        (".", None, NOT_A_FILE),
        ("k.toml", b"port = \n", "{path} is not valid TOML: "),
        ("k.toml", b'host = "\xff"\n', "{path} is not UTF-8 text."),
        pytest.param(
            UNREADABLE,
            b"port = 8001\n",
            "cannot read {path}: Permission denied",
            marks=pytest.mark.skipif(os.geteuid() == 0, reason="root reads mode 0"),
        ),
        ("k.toml", b"[server]\nport = 8001\n", f"- server (KAMAYOQ_SERVER): {EXTRA}"),
        ("k.toml", b'colour = "red"\n', f"- colour (KAMAYOQ_COLOUR): {EXTRA}"),
    ],
    ids=[
        "empty",
        "missing",
        "directory",
        "syntax",
        "utf8",
        "unreadable",
        "table",
        "key",
    ],
)
def test_config_file_errors_name_the_problem(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    tmp_path: Path,
    file_name: str,
    content: bytes | None,
    expected: str,
) -> None:
    """Stop with a message that names the problem with the config file."""
    path = (tmp_path / file_name).resolve()
    if content is not None:
        path.write_bytes(content)
    if file_name == UNREADABLE:
        path.chmod(0)
    monkeypatch.setenv("KAMAYOQ_CONFIG_FILE", str(path) if file_name else "")
    assert expected.format(path=path) in load_error()


def test_unknown_kamayoq_env_var_is_ignored(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    """Ignore a KAMAYOQ_ variable that is not a setting."""
    monkeypatch.setenv("KAMAYOQ_REQUIRE_DOCKER", "1")
    monkeypatch.setenv("KAMAYOQ_NOT_A_SETTING", "x")
    assert load_settings().port == 8000
