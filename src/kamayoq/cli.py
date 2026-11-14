"""Command-line entry point of kamayoq."""

import argparse
import sys
from collections.abc import Sequence
from importlib.metadata import version

import uvicorn

from kamayoq.api.app import create_app
from kamayoq.log import configure_logging
from kamayoq.settings import InvalidSettingsError, load_settings

BAD_SETTINGS_EXIT_CODE = 2


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for the kamayoq command."""
    parser = argparse.ArgumentParser(
        prog="kamayoq", description="Control plane for agentic operations."
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('kamayoq')}"
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="Start the API server.")
    return parser


def serve() -> int:
    """Load the settings and run the API server until it stops.

    A bad setting prints a plain-text message to stderr, before the server opens a
    port, and gives exit code 2.
    """
    try:
        settings = load_settings()
    except InvalidSettingsError as error:
        print(f"kamayoq: {error}", file=sys.stderr)
        return BAD_SETTINGS_EXIT_CODE
    configure_logging(settings.log_level)
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,
        log_level=settings.log_level.lower(),
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the kamayoq command and return the exit code.

    The parser exits through SystemExit for --version, --help, and a bad argument.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        return serve()
    parser.print_help()
    return 0
