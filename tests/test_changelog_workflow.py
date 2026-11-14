"""Unit tests that prove the structure of the Changelog workflow."""

from pathlib import Path
from typing import Any

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS_DIR / "changelog.yml"
CI_WORKFLOW = WORKFLOWS_DIR / "ci.yml"
TOWNCRIER = "uv run --locked --only-group changelog towncrier"
CHECK_COMMAND = f"{TOWNCRIER} check --compare-with origin/develop"
CHECK_CONDITION = (
    "${{ !contains(github.event.pull_request.labels.*.name, 'skip-changelog')"
    " && github.event.pull_request.user.login != 'dependabot[bot]' }}"
)


def load_yaml(path: Path) -> dict[str, Any]:
    """Return the YAML file, with each key and each scalar as a string."""
    document: dict[str, Any] = yaml.load(
        path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )
    return document


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


def changelog_job() -> dict[str, Any]:
    """Return the changelog job of the workflow."""
    job: dict[str, Any] = load_yaml(WORKFLOW)["jobs"]["changelog"]
    return job


def test_changelog_workflow_runs_on_pull_request_label_events() -> None:
    """Run on each pull request to develop, also when a label changes."""
    workflow = load_yaml(WORKFLOW)
    assert workflow["name"] == "Changelog"
    assert workflow["on"] == {
        "pull_request": {
            "branches": ["develop"],
            "types": ["opened", "synchronize", "reopened", "labeled", "unlabeled"],
        }
    }


def test_changelog_workflow_has_one_job_that_always_runs() -> None:
    """Name the check changelog, and run the job with no job condition."""
    workflow = load_yaml(WORKFLOW)
    assert set(workflow["jobs"]) == {"changelog"}
    job = workflow["jobs"]["changelog"]
    assert "name" not in job
    assert "if" not in job
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == "10"
    assert workflow["concurrency"] == load_yaml(CI_WORKFLOW)["concurrency"]


def test_changelog_job_runs_sync_draft_and_check() -> None:
    """Sync the changelog group, build the draft, then run towncrier check."""
    job = changelog_job()
    assert run_commands(job) == [
        "uv sync --locked --only-group changelog",
        f"{TOWNCRIER} build --draft --version next",
        CHECK_COMMAND,
    ]
    assert step_using(job, "astral-sh/setup-uv")["with"]["enable-cache"] == "true"


def test_only_check_step_has_label_and_dependabot_condition() -> None:
    """Skip only the towncrier check step for the label and for Dependabot."""
    for step in changelog_job()["steps"]:
        if step.get("run") == CHECK_COMMAND:
            assert step["if"] == CHECK_CONDITION
        else:
            assert "if" not in step


def test_changelog_job_fetches_history_with_read_only_token() -> None:
    """Fetch the full history with a read-only token and no saved credentials."""
    assert load_yaml(WORKFLOW)["permissions"] == {"contents": "read"}
    job = changelog_job()
    checkout = step_using(job, "actions/checkout")
    assert checkout["with"]["fetch-depth"] == "0"
    assert checkout["with"]["persist-credentials"] == "false"
    for step in job["steps"]:
        assert "continue-on-error" not in step
