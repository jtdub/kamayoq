"""Reject prose comments in Python files.

A comment passes only when it is a tool directive, a shebang, or an encoding line.
"""

import re
import sys
import tokenize
from pathlib import Path

DIRECTIVE = re.compile(
    r"#\s*(noqa: [A-Z]+[0-9]+|type: ignore\b|pragma: no (cover|branch)\b"
    r"|fmt: (off|on|skip)\b|ruff: (noqa|isort)\b|mypy: |pylint: disable=)"
)
HEADER = re.compile(r"#!|#.*coding[:=]")


def prose_comments(path: Path) -> list[str]:
    """Return one line of the form path:line:text for each prose comment."""
    with path.open("rb") as source:
        tokens = list(tokenize.tokenize(source.readline))
    return [
        f"{path}:{token.start[0]}:{token.string}"
        for token in tokens
        if token.type == tokenize.COMMENT
        and not DIRECTIVE.match(token.string)
        and not (token.start[0] <= 2 and HEADER.match(token.string))
    ]


def main(argv: list[str]) -> int:
    """Print each prose comment and return 1 if one exists."""
    found = [line for name in argv for line in prose_comments(Path(name))]
    print(*found, sep="\n", end="\n" if found else "")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
