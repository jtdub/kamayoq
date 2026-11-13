"""Unit tests for the kamayoq command."""

import subprocess
import sysconfig
from importlib.metadata import version
from pathlib import Path

import pytest

from kamayoq.cli import main


def test_version_flag_prints_package_version_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Print the metadata version and exit 0."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"kamayoq {version('kamayoq')}\n"


def test_package_version_is_0_1_0_dev0() -> None:
    """Read the version from the installed metadata."""
    assert version("kamayoq") == "0.1.0.dev0"


def test_unknown_flag_exits_two_with_usage_on_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reject an unknown flag."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--bogus"])
    assert exit_info.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_no_arguments_prints_help_and_returns_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Print the help when no argument is given."""
    assert main([]) == 0
    assert capsys.readouterr().out.startswith("usage: kamayoq")


def test_installed_command_prints_version() -> None:
    """Run the console script of the installed package."""
    command = Path(sysconfig.get_path("scripts")) / "kamayoq"
    result = subprocess.run(
        [str(command), "--version"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert result.stdout == "kamayoq 0.1.0.dev0\n"
