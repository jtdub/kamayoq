"""Unit tests that prove the pytest, marker, and coverage configuration."""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_pytest(
    tmp_path: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run pytest in a child process with the project config."""
    child_env = {
        **os.environ,
        "COVERAGE_FILE": str(tmp_path / ".coverage"),
        **(env or {}),
    }
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=PROJECT_ROOT,
        env=child_env,
    )


def test_unknown_marker_is_an_error(tmp_path: Path) -> None:
    """Reject a marker that the config does not register."""
    sample = tmp_path / "test_sample.py"
    sample.write_text(
        "import pytest\n\n\n@pytest.mark.integraton\ndef test_x() -> None:\n    pass\n"
    )
    result = run_pytest(tmp_path, "--no-cov", "-c", "pyproject.toml", str(sample))
    assert result.returncode != 0
    assert "'integraton' not found in `markers` configuration option" in result.stdout


def test_run_prints_coverage_report_with_missing_lines(tmp_path: Path) -> None:
    """Print the terminal coverage report with the Missing column."""
    result = run_pytest(tmp_path, "tests/test_cli.py")
    assert result.returncode == 0
    assert "coverage: platform" in result.stdout
    assert "Missing" in result.stdout
    assert "src/kamayoq/cli.py" in result.stdout


def test_child_run_writes_coverage_data_outside_the_repository(tmp_path: Path) -> None:
    """Write the coverage data of a child run to the file in COVERAGE_FILE."""
    result = run_pytest(tmp_path, "tests/test_cli.py")
    assert result.returncode == 0
    assert (tmp_path / ".coverage").is_file()
