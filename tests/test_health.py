"""Unit tests for the health endpoints and the API docs setting."""

import asyncio
import socket
import time

import httpx2
import psycopg
import pytest
from fastapi.testclient import TestClient

from kamayoq.api.app import create_app
from kamayoq.settings import Settings

UNREACHABLE_PASSWORD = "SEKRET-not-sent"


def free_port() -> int:
    """Return a TCP port on 127.0.0.1 that nothing listens on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    return port


def client_for(
    database_url: str, readiness_timeout: float = 2.0, api_docs: bool = False
) -> TestClient:
    """Return a test client for an app with this database URL."""
    settings = Settings(
        database_url=database_url,
        readiness_timeout=readiness_timeout,
        api_docs=api_docs,
    )
    return TestClient(create_app(settings))


def refused_url() -> str:
    """Return a URL with a password for a port that refuses the connection."""
    return f"postgresql://kamayoq:{UNREACHABLE_PASSWORD}@127.0.0.1:{free_port()}/k"


def test_healthz_returns_ok_without_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer /healthz without a database connection."""

    async def fail_connect(*args: object, **kwargs: object) -> None:
        pytest.fail("/healthz opened a database connection")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", fail_connect)
    response = client_for(refused_url()).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_returns_503_when_postgres_refuses_connection() -> None:
    """Return 503 when nothing listens on the database port."""
    response = client_for(refused_url()).get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_readyz_returns_503_when_host_does_not_resolve() -> None:
    """Return 503 when the database host name does not resolve."""
    response = client_for("postgresql://kamayoq@no-such-host.invalid/k").get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_readyz_returns_503_on_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return 503, not 500, when the check raises an error that is not expected."""

    async def broken_connect(*args: object, **kwargs: object) -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", broken_connect)
    response = client_for(refused_url()).get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_readyz_returns_503_within_timeout_when_postgres_is_slow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop the check at the readiness timeout."""

    async def slow_connect(*args: object, **kwargs: object) -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", slow_connect)
    client = client_for(refused_url(), readiness_timeout=0.1)
    started = time.monotonic()
    response = client.get("/readyz")
    elapsed = time.monotonic() - started
    assert response.status_code == 503
    assert elapsed < 0.6


def test_readyz_body_has_no_error_text() -> None:
    """Keep the error text and the credentials out of the response."""
    response = client_for(refused_url()).get("/readyz")
    assert response.text == '{"status":"unavailable"}'
    assert UNREACHABLE_PASSWORD not in response.text


def test_concurrent_readyz_calls_open_one_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run one check for many calls at the same time."""
    calls = 0

    async def counted_connect(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        raise OSError("refused")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", counted_connect)
    app = create_app(Settings(database_url=refused_url()))

    async def send_calls() -> list[int]:
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            responses = await asyncio.gather(
                *(client.get("/readyz") for _ in range(100))
            )
        return [response.status_code for response in responses]

    statuses = asyncio.run(send_calls())
    assert statuses == [503] * 100
    assert calls == 1


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_are_off_by_default(path: str) -> None:
    """Hide the API docs when KAMAYOQ_API_DOCS is not set."""
    assert client_for(refused_url()).get(path).status_code == 404


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_setting_turns_docs_on(path: str) -> None:
    """Show the API docs when api_docs is true."""
    assert client_for(refused_url(), api_docs=True).get(path).status_code == 200
