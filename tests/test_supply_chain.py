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
SUPPLY_CHAIN_WORKFLOW = WORKFLOWS_DIR / "supply-chain.yml"
DEPENDABOT_CONFIG = PROJECT_ROOT / ".github" / "dependabot.yml"
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


def test_supply_chain_workflow_runs_on_pr_push_and_daily() -> None:
    """Run on a pull request to develop, a push to develop, and each day."""
    workflow = load_yaml(SUPPLY_CHAIN_WORKFLOW)
    assert workflow["name"] == "Supply chain"
    assert workflow["on"] == {
        "pull_request": {"branches": ["develop"]},
        "push": {"branches": ["develop"]},
        "schedule": [{"cron": "17 6 * * *"}],
    }


def test_supply_chain_workflow_keeps_read_only_token() -> None:
    """Give the token read access only, and let no step fail without a red run."""
    workflow = load_yaml(SUPPLY_CHAIN_WORKFLOW)
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"audit", "sbom"}
    for job in workflow["jobs"].values():
        assert job["runs-on"] == "ubuntu-latest"
        assert job["timeout-minutes"] == "10"
        assert step_using(job, "actions/checkout")["with"]["persist-credentials"] == (
            "false"
        )
        assert step_using(job, "astral-sh/setup-uv")["with"]["enable-cache"] == "true"
    for step in all_steps(workflow):
        assert "continue-on-error" not in step


def test_audit_job_runs_pip_audit_on_every_locked_package() -> None:
    """Audit each locked package, on each platform, against the OSV database."""
    audit = load_yaml(SUPPLY_CHAIN_WORKFLOW)["jobs"]["audit"]
    assert run_commands(audit) == [
        "uv sync --locked --only-group audit",
        "uv export --locked --all-packages --all-groups --no-emit-project"
        " --format requirements-txt"
        ' --output-file "$RUNNER_TEMP/requirements.txt"',
        "sed -i -E 's/ ; [^\\\\]*//' \"$RUNNER_TEMP/requirements.txt\"",
        "uv run --locked --only-group audit pip-audit"
        " --vulnerability-service osv --strict"
        ' --disable-pip --no-deps --requirement "$RUNNER_TEMP/requirements.txt"',
    ]


def test_sbom_job_uploads_cyclonedx_artifact_on_every_run() -> None:
    """Upload a CycloneDX SBOM of each locked package on each run."""
    sbom = load_yaml(SUPPLY_CHAIN_WORKFLOW)["jobs"]["sbom"]
    assert run_commands(sbom) == [
        "uv export --locked --all-packages --all-groups --format cyclonedx1.5"
        " --preview-features sbom-export --output-file sbom.cdx.json",
    ]
    upload = step_using(sbom, "actions/upload-artifact")
    assert upload["with"] == {
        "name": "sbom-cyclonedx",
        "path": "sbom.cdx.json",
        "if-no-files-found": "error",
    }
    assert "if" not in upload


def test_audit_group_holds_pip_audit_and_is_not_a_default_group() -> None:
    """Keep pip-audit in the lock, out of the default install."""
    pyproject = load_pyproject()
    assert pyproject["dependency-groups"]["audit"] == ["pip-audit>=2.10.1"]
    assert "audit" not in pyproject["tool"]["uv"].get("default-groups", [])


def test_dependabot_updates_uv_and_actions_with_seven_day_cooldown() -> None:
    """Propose weekly updates of uv and Actions, 7 days after each release."""
    config = load_yaml(DEPENDABOT_CONFIG)
    assert config["version"] == "2"
    updates = config["updates"]
    assert len(updates) == 2
    assert {update["package-ecosystem"] for update in updates} == {
        "uv",
        "github-actions",
    }
    for update in updates:
        assert update["directory"] == "/"
        assert update["schedule"] == {"interval": "weekly"}
        assert update["cooldown"] == {"default-days": "7"}
