"""Unit tests that prove the lint and type configuration rejects bad code."""

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = PROJECT_ROOT / "pyproject.toml"


def run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    """Run a tool module of the dev environment with the project config."""
    return subprocess.run(
        [sys.executable, "-m", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=PROJECT_ROOT,
    )


@pytest.mark.parametrize(
    ("source", "rule"),
    [
        ('"""Module."""\n\n# print("x")\n', "ERA001"),
        ("def f() -> None:\n    pass\n", "D100"),
        (
            '"""Module."""\n\n\ndef f(x: int) -> int:\n'
            '    """Return x.\n\n    Args:\n        y: A value.\n    """\n'
            "    return x\n",
            "D417",
        ),
        ('"""Module."""\n\nimport os  # noqa\n', "PGH004"),
    ],
)
def test_ruff_rejects_owner_rule_violation(
    tmp_path: Path, source: str, rule: str
) -> None:
    """Report the rule for a file that breaks it."""
    sample = tmp_path / "sample.py"
    sample.write_text(source)
    result = run_tool(
        "ruff", "check", "--config", str(PYPROJECT), "--no-cache", str(sample)
    )
    assert result.returncode == 1
    assert rule in result.stdout


def test_mypy_strict_rejects_untyped_function(tmp_path: Path) -> None:
    """Report a function with no annotations."""
    sample = tmp_path / "sample.py"
    sample.write_text("def f(x):\n    return x\n")
    result = run_tool(
        "mypy", "--config-file", str(PYPROJECT), "--no-incremental", str(sample)
    )
    assert result.returncode == 1
    assert "no-untyped-def" in result.stdout
