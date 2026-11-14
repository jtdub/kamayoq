"""Unit tests that prove the supply-chain controls of the project."""

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"
PYPROJECT = PROJECT_ROOT / "pyproject.toml"
README = PROJECT_ROOT / "README.md"
UV_LOCK = PROJECT_ROOT / "uv.lock"
PRE_COMMIT_CONFIG = PROJECT_ROOT / ".pre-commit-config.yaml"
PYPI_SOURCE = {"registry": "https://pypi.org/simple"}
INSTALLS_OUTSIDE_THE_LOCK = (
    "uvx",
    "uv pip",
    "uv tool",
    "uv add",
    "uv lock",
    "pip install",
)
PINNED_USES_LINE = re.compile(
    r"\s*(- )?uses: [\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+(\.\d+)*"
)
UV_VERSION = "0.11.33"


def load_yaml(path: Path) -> dict[str, Any]:
    """Return the YAML file, with each key and each scalar as a string."""
    document: dict[str, Any] = yaml.load(
        path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )
    return document


def load_pyproject() -> dict[str, Any]:
    """Return the parsed pyproject.toml."""
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def load_uv_lock() -> dict[str, Any]:
    """Return the parsed uv.lock."""
    return tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))


def workflow_paths() -> list[Path]:
    """Return the path of each workflow file."""
    return sorted(WORKFLOWS_DIR.glob("*.yml"))


def all_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """Return each step of each job of the workflow."""
    return [step for job in workflow["jobs"].values() for step in job["steps"]]


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


def test_project_requires_uv_0_11() -> None:
    """Require uv 0.11.33 or a later 0.11 release, in the config and the README."""
    pyproject = load_pyproject()
    assert pyproject["tool"]["uv"]["required-version"] == ">=0.11.33,<0.12"
    assert pyproject["build-system"]["requires"] == ["uv_build>=0.11.33,<0.12.0"]
    assert "0.11.33 or a later 0.11 release." in README.read_text(encoding="utf-8")


def test_every_setup_uv_step_uses_uv_0_11_33() -> None:
    """Install uv 0.11.33 in each setup-uv step of each workflow."""
    setup_uv_steps = [
        step
        for path in workflow_paths()
        for step in all_steps(load_yaml(path))
        if step.get("uses", "").startswith("astral-sh/setup-uv@")
    ]
    assert setup_uv_steps
    for step in setup_uv_steps:
        assert step["with"]["version"] == UV_VERSION


def test_uv_rejects_packages_newer_than_seven_days() -> None:
    """Lock no release that is less than 7 days old."""
    assert load_pyproject()["tool"]["uv"]["exclude-newer"] == "7 days"
    assert load_uv_lock()["options"]["exclude-newer-span"] == "P7D"


@pytest.mark.parametrize("path", workflow_paths(), ids=lambda path: path.name)
def test_every_workflow_sets_uv_locked(path: Path) -> None:
    """Stop each uv command of the workflow that would change the lock."""
    assert load_yaml(path)["env"]["UV_LOCKED"] == "1"


def test_no_workflow_or_hook_installs_outside_the_lock() -> None:
    """Install only from uv.lock, in each workflow and each pre-commit hook."""
    run_values = [
        step["run"]
        for path in workflow_paths()
        for step in all_steps(load_yaml(path))
        if "run" in step
    ]
    hook_entries = [
        hook["entry"]
        for repo in load_yaml(PRE_COMMIT_CONFIG)["repos"]
        for hook in repo["hooks"]
    ]
    assert run_values
    assert hook_entries
    for command in run_values + hook_entries:
        for forbidden in INSTALLS_OUTSIDE_THE_LOCK:
            assert forbidden not in command
    for entry in hook_entries:
        if entry.startswith("uv "):
            assert entry.startswith("uv run --locked ")


def test_each_locked_package_has_a_hash_on_each_file() -> None:
    """Lock each package from PyPI, with a sha256 hash on each file."""
    packages = [
        package for package in load_uv_lock()["package"] if package["name"] != "kamayoq"
    ]
    assert packages
    for package in packages:
        assert package["source"] == PYPI_SOURCE, package["name"]
        files = package.get("wheels", []) + (
            [package["sdist"]] if "sdist" in package else []
        )
        assert files, package["name"]
        for locked_file in files:
            assert locked_file["hash"].startswith("sha256:"), package["name"]


def test_every_workflow_action_is_pinned_by_sha_with_version_comment() -> None:
    """Pin each action of each workflow by commit SHA, with the version in a comment."""
    uses_values = [
        step["uses"]
        for path in workflow_paths()
        for step in all_steps(load_yaml(path))
        if "uses" in step
    ]
    uses_lines = [
        line
        for path in workflow_paths()
        for line in path.read_text(encoding="utf-8").splitlines()
        if "uses:" in line
    ]
    assert uses_values
    assert len(uses_lines) == len(uses_values)
    for line in uses_lines:
        assert PINNED_USES_LINE.fullmatch(line), line
