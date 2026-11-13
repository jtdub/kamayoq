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


def run_comment_hook(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    """Run the no-comments pre-commit hook on one sample file."""
    sample = tmp_path / "sample.py"
    sample.write_text(source)
    return run_tool("pre_commit", "run", "no-comments", "--files", str(sample))


def test_comment_hook_rejects_prose_comment(tmp_path: Path) -> None:
    """Report a full-line prose comment."""
    result = run_comment_hook(tmp_path, '"""M."""\n\n# explain the next line\nx = 1\n')
    assert result.returncode == 1
    assert "sample.py:3:# explain the next line" in result.stdout


def test_comment_hook_accepts_encoding_line(tmp_path: Path) -> None:
    """Pass an encoding line."""
    source = '# -*- coding: utf-8 -*-\n"""M."""\n'
    assert run_comment_hook(tmp_path, source).returncode == 0


def test_comment_hook_accepts_tool_directives(tmp_path: Path) -> None:
    """Pass a shebang and bare tool directives."""
    source = (
        "#!/usr/bin/env python\n"
        '"""M."""\n\n'
        "# noqa: E501\n"
        "# type: ignore\n"
        "# pragma: no cover\n"
        "# fmt: off\n"
        "# pylint: disable=C0114\n"
        "# ruff: noqa: E501\n"
        '# mypy: disable-error-code="misc"\n'
    )
    assert run_comment_hook(tmp_path, source).returncode == 0


def test_comment_hook_rejects_end_of_line_comment(tmp_path: Path) -> None:
    """Report a prose comment after code."""
    result = run_comment_hook(tmp_path, '"""M."""\n\nx = 1  # explain x\n')
    assert result.returncode == 1
    assert "sample.py:3:# explain x" in result.stdout


def test_comment_hook_ignores_hash_inside_string(tmp_path: Path) -> None:
    """Pass a line that starts with a hash inside a string."""
    source = '"""M."""\n\nTEXT = """\n# Heading\n"""\n'
    assert run_comment_hook(tmp_path, source).returncode == 0


def test_comment_hook_accepts_header_on_line_two(tmp_path: Path) -> None:
    """Pass a shebang on line 1 and an encoding line on line 2."""
    source = '#!/usr/bin/env python\n# -*- coding: utf-8 -*-\n"""M."""\n'
    assert run_comment_hook(tmp_path, source).returncode == 0


def test_comment_hook_rejects_header_after_line_two(tmp_path: Path) -> None:
    """Report a shebang and an encoding line after line 2."""
    source = '"""M."""\n\n#!/usr/bin/env python\n# -*- coding: utf-8 -*-\n'
    result = run_comment_hook(tmp_path, source)
    assert result.returncode == 1
    assert "sample.py:3:#!/usr/bin/env python" in result.stdout


def test_comment_hook_rejects_directive_with_prose(tmp_path: Path) -> None:
    """Report a directive that does not have an exact form."""
    result = run_comment_hook(tmp_path, '"""M."""\n\nimport os  # noqa because\n')
    assert result.returncode == 1
    assert "sample.py:3:# noqa because" in result.stdout
