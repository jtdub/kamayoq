"""Unit tests for the kamayoq command."""

import json
import os
import signal
import socket
import subprocess
import sysconfig
import time
from importlib.metadata import version
from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI

from kamayoq.cli import main

UNUSED_DATABASE_URL = "postgresql://kamayoq:unused@127.0.0.1:1/kamayoq"
SERVER_START_SECONDS = 10.0
SERVER_STOP_SECONDS = 10.0


def free_port() -> int:
    """Return a TCP port on 127.0.0.1 that nothing listens on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    return port


def wait_for_healthz(url: str) -> httpx2.Response:
    """Poll the URL until it answers, and return the response."""
    deadline = time.monotonic() + SERVER_START_SECONDS
    while True:
        try:
            return httpx2.get(url)
        except httpx2.TransportError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)


def test_version_flag_prints_package_version_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Print the metadata version and exit 0."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"kamayoq {version('kamayoq')}\n"


def test_package_version_is_0_1_0_dev0() -> None:
    """Read the version from the installed metadata."""
    assert version("kamayoq") == "0.1.0.dev0"


def test_unknown_flag_exits_two_with_usage_on_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reject an unknown flag."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--bogus"])
    assert exit_info.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_no_arguments_prints_help_and_returns_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Print the help when no argument is given."""
    assert main([]) == 0
    assert capsys.readouterr().out.startswith("usage: kamayoq")


def test_installed_command_prints_version() -> None:
    """Run the console script of the installed package."""
    command = Path(sysconfig.get_path("scripts")) / "kamayoq"
    result = subprocess.run(
        [str(command), "--version"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert result.stdout == "kamayoq 0.1.0.dev0\n"


def test_serve_with_bad_settings_exits_two_and_names_field(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 2 before the server starts when a setting is missing."""

    def fail_run(*args: object, **kwargs: object) -> None:
        pytest.fail("uvicorn started with bad settings")

    monkeypatch.setattr("kamayoq.cli.uvicorn.run", fail_run)
    assert main(["serve"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("kamayoq: Settings are not valid:")
    assert "database_url (KAMAYOQ_DATABASE_URL): Field required" in err


def test_serve_runs_uvicorn_with_settings_and_no_log_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configure the JSON logs, then run uvicorn with the settings."""
    monkeypatch.setenv("KAMAYOQ_DATABASE_URL", UNUSED_DATABASE_URL)
    monkeypatch.setenv("KAMAYOQ_HOST", "127.0.0.2")
    monkeypatch.setenv("KAMAYOQ_PORT", "9123")
    monkeypatch.setenv("KAMAYOQ_LOG_LEVEL", "debug")
    log_levels: list[str] = []
    runs: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr("kamayoq.cli.configure_logging", log_levels.append)
    monkeypatch.setattr(
        "kamayoq.cli.uvicorn.run",
        lambda *args, **kwargs: runs.append((args, kwargs)),
    )
    assert main(["serve"]) == 0
    assert log_levels == ["DEBUG"]
    [(args, kwargs)] = runs
    assert isinstance(args[0], FastAPI)
    assert kwargs == {
        "host": "127.0.0.2",
        "port": 9123,
        "log_config": None,
        "log_level": "debug",
    }


def test_serve_command_answers_healthz_and_logs_json() -> None:
    """Start the installed command, call /healthz, and stop it with SIGTERM."""
    command = Path(sysconfig.get_path("scripts")) / "kamayoq"
    port = free_port()
    env = {
        **os.environ,
        "KAMAYOQ_DATABASE_URL": UNUSED_DATABASE_URL,
        "KAMAYOQ_PORT": str(port),
    }
    process = subprocess.Popen(
        [str(command), "serve"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        response = wait_for_healthz(f"http://127.0.0.1:{port}/healthz")
        process.send_signal(signal.SIGTERM)
        _, stderr = process.communicate(timeout=SERVER_STOP_SECONDS)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert process.returncode == -signal.SIGTERM
    records = [json.loads(line) for line in stderr.splitlines()]
    loggers = {record["logger"] for record in records}
    assert {"uvicorn.error", "uvicorn.access"} <= loggers


def test_help_lists_serve_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    """Show the serve subcommand in the help."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    assert "serve" in capsys.readouterr().out
