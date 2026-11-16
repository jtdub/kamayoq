"""Unit tests of the Alembic config, the revision files, and the env.py errors."""

import configparser
import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util import CommandError

from kamayoq.db.models import DEFAULT_ORG_ID, DEFAULT_ORG_NAME

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
FIRST_REVISION = PROJECT_ROOT / "src/kamayoq/migrations/versions/v0001_organizations.py"
FAILED_EXIT_STATUS = 255
PERCENT_PASSWORD_URL = "postgresql://u:p%25SEKRET@127.0.0.1:1/d"


def test_alembic_ini_has_package_migrations_and_no_url() -> None:
    """Point at the package migrations, with no URL and no logger sections."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ALEMBIC_INI, encoding="utf-8")
    assert parser["alembic"]["script_location"] == "%(here)s/src/kamayoq/migrations"
    assert "sqlalchemy.url" not in parser["alembic"]
    assert not {"loggers", "handlers", "formatters"} & set(parser.sections())


def test_one_head_and_default_org_id_matches() -> None:
    """Keep one head, and insert the same default org as the models name."""
    heads = ScriptDirectory.from_config(Config(ALEMBIC_INI)).get_heads()
    text = FIRST_REVISION.read_text(encoding="utf-8")
    assert len(heads) == 1
    assert str(DEFAULT_ORG_ID) in text
    assert f'"{DEFAULT_ORG_NAME}"' in text


def test_missing_database_url_gives_command_error() -> None:
    """Raise CommandError that names the variable when no URL is set."""
    with pytest.raises(CommandError, match="KAMAYOQ_DATABASE_URL"):
        command.upgrade(Config(ALEMBIC_INI), "head")


def run_alembic_upgrade() -> subprocess.CompletedProcess[str]:
    """Run alembic upgrade head in a child process from the project root."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        check=False,
        cwd=PROJECT_ROOT,
    )


def test_alembic_cli_prints_failed_line() -> None:
    """Print one FAILED line and no traceback, and exit with status 255."""
    result = run_alembic_upgrade()
    assert "FAILED: Settings are not valid" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
    assert result.returncode == FAILED_EXIT_STATUS


def test_offline_mode_is_rejected() -> None:
    """Reject the --sql mode with a plain message."""
    with pytest.raises(
        CommandError, match=r"kamayoq does not support offline mode \(--sql\)\."
    ):
        command.upgrade(Config(ALEMBIC_INI), "head", sql=True)


def test_alembic_cli_accepts_percent_in_password_and_hides_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Try to connect with a % in the password, and show no part of it."""
    monkeypatch.setenv("KAMAYOQ_DATABASE_URL", PERCENT_PASSWORD_URL)
    result = run_alembic_upgrade()
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Connection refused" in output
    assert "interpolation" not in output
    assert "SEKRET" not in output


def test_first_migration_rejects_postgres_older_than_18(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop the first migration on a server that reports Postgres 17."""
    spec = importlib.util.spec_from_file_location("v0001", FIRST_REVISION)
    assert spec is not None
    assert spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    op = MagicMock()
    op.get_bind().exec_driver_sql().scalar_one.return_value = "170000"
    monkeypatch.setattr(revision, "op", op)
    with pytest.raises(
        RuntimeError,
        match=r"kamayoq needs Postgres 18 or later\. This server is 170000\.",
    ):
        revision.upgrade()
    op.create_table.assert_not_called()
