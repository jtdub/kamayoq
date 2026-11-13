"""Unit tests that prove the pytest, marker, and coverage configuration."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
POSTGRES_TESTS = "tests/test_postgres.py"


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


def collected_ids(result: subprocess.CompletedProcess[str]) -> list[str]:
    """Return the test IDs that a --collect-only -q run prints."""
    return [line for line in result.stdout.splitlines() if "::" in line]


def test_integration_marker_selects_only_postgres_tests(tmp_path: Path) -> None:
    """Select the tests that use the postgres fixture."""
    result = run_pytest(
        tmp_path, "--collect-only", "-q", "--no-cov", "-m", "integration"
    )
    ids = collected_ids(result)
    assert result.returncode == 0
    assert ids
    assert all(test_id.startswith(POSTGRES_TESTS) for test_id in ids)


def test_unit_marker_selects_every_other_test(tmp_path: Path) -> None:
    """Select each test that does not use the postgres fixture."""
    result = run_pytest(tmp_path, "--collect-only", "-q", "--no-cov", "-m", "unit")
    ids = collected_ids(result)
    assert result.returncode == 0
    assert "tests/test_cli.py::test_package_version_is_0_1_0_dev0" in ids
    assert not any(test_id.startswith(POSTGRES_TESTS) for test_id in ids)


def test_unknown_marker_is_an_error(tmp_path: Path) -> None:
    """Reject a marker that the config does not register."""
    sample = tmp_path / "test_sample.py"
    sample.write_text(
        "import pytest\n\n\n@pytest.mark.integraton\ndef test_x() -> None:\n    pass\n"
    )
    result = run_pytest(tmp_path, "--no-cov", "-c", "pyproject.toml", str(sample))
    assert result.returncode != 0
    assert "'integraton' not found in `markers` configuration option" in result.stdout


def test_unit_marker_on_postgres_test_is_an_error(tmp_path: Path) -> None:
    """Stop the run when a test that uses postgres has the unit marker."""
    sample = tmp_path / "test_sample.py"
    sample.write_text(
        "import pytest\n\n\n@pytest.mark.unit\n"
        "def test_x(postgres: object) -> None:\n    pass\n"
    )
    result = run_pytest(
        tmp_path,
        "--no-cov",
        "--collect-only",
        "-c",
        "pyproject.toml",
        "-p",
        "conftest",
        str(sample),
        env={"PYTHONPATH": str(PROJECT_ROOT / "tests")},
    )
    assert result.returncode != 0
    assert "uses postgres, so it cannot be a unit test." in result.stderr


def test_run_prints_coverage_report_with_missing_lines(tmp_path: Path) -> None:
    """Print the terminal coverage report with the Missing column."""
    result = run_pytest(tmp_path, "tests/test_cli.py")
    assert result.returncode == 0
    assert "coverage: platform" in result.stdout
    assert "Missing" in result.stdout
    assert "src/kamayoq/cli.py" in result.stdout


def test_postgres_tests_skip_with_reason_when_docker_is_missing(tmp_path: Path) -> None:
    """Skip, and print why, when no Docker daemon answers."""
    missing = tmp_path / "docker.sock"
    no_docker = {
        "DOCKER_HOST": f"unix://{missing}",
        "HOME": str(tmp_path),
        "KAMAYOQ_REQUIRE_DOCKER": "",
    }
    result = run_pytest(tmp_path, "--no-cov", POSTGRES_TESTS, env=no_docker)
    assert result.returncode == 0
    assert "skipped" in result.stdout
    assert "passed" not in result.stdout
    assert "Docker is not available" in result.stdout
    assert "Start Docker to run this test." in result.stdout


def test_postgres_tests_skip_when_docker_requirement_is_off(tmp_path: Path) -> None:
    """Skip, and print why, when KAMAYOQ_REQUIRE_DOCKER is 0."""
    missing = tmp_path / "docker.sock"
    no_docker = {
        "DOCKER_HOST": f"unix://{missing}",
        "HOME": str(tmp_path),
        "KAMAYOQ_REQUIRE_DOCKER": "0",
    }
    result = run_pytest(tmp_path, "--no-cov", POSTGRES_TESTS, env=no_docker)
    assert result.returncode == 0
    assert "skipped" in result.stdout
    assert "passed" not in result.stdout
    assert "Docker is not available" in result.stdout
    assert "Start Docker to run this test." in result.stdout


@pytest.mark.parametrize("value", ["1", "true"])
def test_postgres_errors_when_docker_is_required_and_missing(
    tmp_path: Path, value: str
) -> None:
    """Report an error at setup when the environment requires Docker."""
    missing = tmp_path / "docker.sock"
    no_docker = {
        "DOCKER_HOST": f"unix://{missing}",
        "HOME": str(tmp_path),
        "KAMAYOQ_REQUIRE_DOCKER": value,
    }
    result = run_pytest(tmp_path, "--no-cov", POSTGRES_TESTS, env=no_docker)
    assert result.returncode == 1
    assert "error" in result.stdout
    assert "skipped" not in result.stdout
    assert "passed" not in result.stdout
    assert "Docker is not available" in result.stdout


def test_child_run_writes_coverage_data_outside_the_repository(tmp_path: Path) -> None:
    """Write the coverage data of a child run to the file in COVERAGE_FILE."""
    result = run_pytest(tmp_path, "tests/test_cli.py")
    assert result.returncode == 0
    assert (tmp_path / ".coverage").is_file()
