"""Unit tests that prove the supply-chain controls of the project."""

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
