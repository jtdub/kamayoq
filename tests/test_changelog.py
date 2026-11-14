"""Unit tests that prove the towncrier setup of the project."""

import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = PROJECT_ROOT / "pyproject.toml"
CHANGES_DIR = PROJECT_ROOT / "changes"
TEMPLATE = CHANGES_DIR / "template.md"
FRAGMENT_TYPES = ("added", "changed", "fixed", "removed", "security")
ISSUE_URL = "https://github.com/jtdub/kamayoq/issues/{issue}"
DRAFT_ARGS = ("build", "--draft", "--version", "0.0.0", "--date", "2026-01-01")
FRAGMENT_NAME = re.compile(r"^(?P<issue>\d+)\.(?P<type>\w+)$")


def run_towncrier(
    args: list[str], cwd: Path, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run towncrier with the arguments and return the result."""
    return subprocess.run(
        [sys.executable, "-m", "towncrier", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def draft_in(project: Path) -> subprocess.CompletedProcess[str]:
    """Run the draft build in the project."""
    return run_towncrier([*DRAFT_ARGS, "--dir", str(project)], cwd=project)


def bullet(text: str, issue: str) -> str:
    """Return the draft line of one fragment item."""
    return f"- {text} ([#{issue}]({ISSUE_URL.format(issue=issue)}))"


@pytest.fixture
def towncrier_project(tmp_path: Path) -> Path:
    """Return a temporary project with the towncrier config and template only."""
    shutil.copy(PYPROJECT, tmp_path / "pyproject.toml")
    (tmp_path / "changes").mkdir()
    shutil.copy(TEMPLATE, tmp_path / "changes" / "template.md")
    return tmp_path


@pytest.fixture(scope="module")
def repo_draft() -> subprocess.CompletedProcess[str]:
    """Return the draft build of the fragments of this repository."""
    return draft_in(PROJECT_ROOT)


def test_towncrier_types_match_contributing_fragment_types() -> None:
    """Declare the five fragment types of CONTRIBUTING.md, in order."""
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    types = config["tool"]["towncrier"]["type"]
    assert tuple(entry["directory"] for entry in types) == FRAGMENT_TYPES
    for entry in types:
        assert entry["showcontent"] is True
        assert entry["name"] == entry["directory"].title()


def test_draft_renders_each_fragment_line_as_own_bullet(
    repo_draft: subprocess.CompletedProcess[str],
) -> None:
    """Render each non-blank fragment line of changes/ as its own bullet."""
    assert repo_draft.returncode == 0, repo_draft.stderr
    expected = []
    for fragment in sorted(CHANGES_DIR.iterdir()):
        if fragment == TEMPLATE:
            continue
        name = FRAGMENT_NAME.match(fragment.name)
        assert name is not None, fragment.name
        lines = fragment.read_text(encoding="utf-8").splitlines()
        expected += [
            bullet(line.strip(), name["issue"]) for line in lines if line.strip()
        ]
    output_lines = repo_draft.stdout.splitlines()
    for line in expected:
        assert line in output_lines
    assert sum(line.startswith("- ") for line in output_lines) == len(expected)


def test_draft_has_no_double_bullet_marker(
    repo_draft: subprocess.CompletedProcess[str],
) -> None:
    """Supply one bullet marker only, as the CONTRIBUTING.md rule needs."""
    assert repo_draft.returncode == 0, repo_draft.stderr
    for line in repo_draft.stdout.splitlines():
        assert not line.startswith(("- - ", "- * "))


def test_multi_line_fragment_gives_one_bullet_for_each_line(
    towncrier_project: Path,
) -> None:
    """Give one bullet for each line and drop the blank lines."""
    fragment = towncrier_project / "changes" / "1.added"
    fragment.write_text("Added one.\n\nAdded two.\n", encoding="utf-8")
    result = draft_in(towncrier_project)
    assert result.returncode == 0, result.stderr
    bullets = [line for line in result.stdout.splitlines() if line.startswith("- ")]
    assert bullets == [bullet("Added one.", "1"), bullet("Added two.", "1")]


def test_draft_fails_on_unknown_fragment_type(towncrier_project: Path) -> None:
    """Fail the draft build on a fragment with an unknown type."""
    fragment = towncrier_project / "changes" / "1.bogus"
    fragment.write_text("x\n", encoding="utf-8")
    result = draft_in(towncrier_project)
    assert result.returncode == 1
    assert "Invalid news fragment name: 1.bogus" in result.stderr


def test_orphan_fragment_has_no_empty_issue_link(towncrier_project: Path) -> None:
    """Omit the empty issue link of a fragment with no issue."""
    fragment = towncrier_project / "changes" / "+abc.added"
    fragment.write_text("Added orphan.\n", encoding="utf-8")
    result = draft_in(towncrier_project)
    assert result.returncode == 0, result.stderr
    output_lines = result.stdout.splitlines()
    assert "- Added orphan." in output_lines
    assert not any(line.endswith("()") for line in output_lines)


def test_check_fails_without_fragment_and_passes_with_one(
    towncrier_project: Path,
) -> None:
    """Fail towncrier check with no new fragment, and pass with one."""
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=towncrier_project, env=env, check=True)

    def check() -> subprocess.CompletedProcess[str]:
        return run_towncrier(
            [
                "check",
                "--compare-with",
                "origin/develop",
                "--dir",
                str(towncrier_project),
            ],
            cwd=towncrier_project,
            env=env,
        )

    git("init", "--quiet", "--initial-branch=develop")
    git("add", "--all")
    git("commit", "--quiet", "--message", "base")
    git("update-ref", "refs/remotes/origin/develop", "HEAD")
    git("switch", "--quiet", "--create", "feature")
    (towncrier_project / "code.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "--all")
    git("commit", "--quiet", "--message", "code")

    without_fragment = check()
    assert without_fragment.returncode == 1
    assert "No new newsfragments found on this branch." in without_fragment.stdout

    fragment = towncrier_project / "changes" / "1.added"
    fragment.write_text("Added one.\n", encoding="utf-8")
    git("add", "--all")
    git("commit", "--quiet", "--message", "fragment")

    with_fragment = check()
    assert with_fragment.returncode == 0, with_fragment.stdout + with_fragment.stderr
