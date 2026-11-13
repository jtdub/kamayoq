"""Command-line entry point of kamayoq."""

import argparse
from collections.abc import Sequence
from importlib.metadata import version


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for the kamayoq command."""
    parser = argparse.ArgumentParser(
        prog="kamayoq", description="Control plane for agentic operations."
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('kamayoq')}"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the kamayoq command and return the exit code.

    The parser exits through SystemExit for --version, --help, and a bad argument.
    """
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
