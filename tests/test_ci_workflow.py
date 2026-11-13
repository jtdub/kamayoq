"""Unit tests that prove the structure of the CI workflow."""

from pathlib import Path
from typing import Any

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
JOB_NAMES = ("lint", "types", "tests")


def load_workflow() -> dict[str, Any]:
    """Return the CI workflow, with each key and each scalar as a string."""
    workflow: dict[str, Any] = yaml.load(
        WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )
    return workflow


def run_commands(job: dict[str, Any]) -> list[str]:
    """Return the run command of each step of the job, in step order."""
    return [step["run"] for step in job["steps"] if "run" in step]


def step_using(job: dict[str, Any], action: str) -> dict[str, Any]:
    """Return the one step of the job that uses the action."""
    steps = [
        step for step in job["steps"] if step.get("uses", "").startswith(f"{action}@")
    ]
    if len(steps) != 1:
        pytest.fail(f"Expected one step that uses {action}, found {len(steps)}.")
    step: dict[str, Any] = steps[0]
    return step


def test_workflow_runs_on_pull_request_and_push_to_develop() -> None:
    """Run on a pull request to develop and a push to develop only."""
    assert load_workflow()["on"] == {
        "pull_request": {"branches": ["develop"]},
        "push": {"branches": ["develop"]},
    }


def test_workflow_has_exactly_lint_types_and_tests_jobs() -> None:
    """Name the checks lint, types, and tests, from the job IDs."""
    jobs = load_workflow()["jobs"]
    assert set(jobs) == set(JOB_NAMES)
    for job in jobs.values():
        assert "name" not in job


@pytest.mark.parametrize("job_name", JOB_NAMES)
def test_each_job_installs_locked_with_uv_cache(job_name: str) -> None:
    """Install from the lock file with the uv cache in each job."""
    job = load_workflow()["jobs"][job_name]
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == "10"
    assert step_using(job, "astral-sh/setup-uv")["with"]["enable-cache"] == "true"
    assert run_commands(job)[0] == "uv sync --locked"


def test_lint_job_runs_ruff_check_format_and_comment_check() -> None:
    """Run ruff check, ruff format check, and the no-comments check."""
    jobs = load_workflow()["jobs"]
    assert run_commands(jobs["lint"]) == [
        "uv sync --locked",
        "uv run ruff check",
        "uv run ruff format --check",
        "uv run pre-commit run no-comments --all-files",
    ]


def test_types_job_runs_mypy() -> None:
    """Run mypy."""
    jobs = load_workflow()["jobs"]
    assert run_commands(jobs["types"]) == ["uv sync --locked", "uv run mypy"]


def test_tests_job_runs_pytest_and_requires_docker() -> None:
    """Run pytest with Docker required for the integration tests."""
    jobs = load_workflow()["jobs"]
    assert run_commands(jobs["tests"]) == [
        "uv sync --locked",
        "uv run kamayoq --version",
        "uv run pytest",
    ]
    assert jobs["tests"]["env"] == {"KAMAYOQ_REQUIRE_DOCKER": "1"}


def test_workflow_keeps_read_only_token_and_no_persisted_credentials() -> None:
    """Give the token read access only, and keep no credentials after checkout."""
    workflow = load_workflow()
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        assert step_using(job, "actions/checkout")["with"]["persist-credentials"] == (
            "false"
        )
