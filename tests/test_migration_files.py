"""Unit tests of the Alembic config, the revision files, and the env.py errors."""

import configparser
import os
import subprocess
import sys
from pathlib import Path

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


def test_alembic_cli_prints_failed_line() -> None:
    """Print one FAILED line and no traceback, and exit with status 255."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        check=False,
        cwd=PROJECT_ROOT,
        env=dict(os.environ),
    )
    assert "FAILED: Settings are not valid" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
    assert result.returncode == FAILED_EXIT_STATUS


def test_offline_mode_is_rejected() -> None:
    """Reject the --sql mode with a plain message."""
    with pytest.raises(
        CommandError, match=r"kamayoq does not support offline mode \(--sql\)\."
    ):
        command.upgrade(Config(ALEMBIC_INI), "head", sql=True)
