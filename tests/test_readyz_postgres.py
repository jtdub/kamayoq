"""Integration tests of /readyz against a real Postgres."""

import logging

import pytest
from fastapi.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

from kamayoq.api.app import create_app
from kamayoq.settings import Settings

WRONG_PASSWORD = "WRONG-password-for-test"


def readyz(database_url: str) -> tuple[int, str]:
    """Return the status code and the body of one /readyz call."""
    settings = Settings(database_url=database_url)
    response = TestClient(create_app(settings)).get("/readyz")
    return response.status_code, response.text


def test_readyz_returns_200_when_postgres_answers(
    postgres: PostgresContainer,
) -> None:
    """Return 200 when Postgres answers SELECT 1."""
    status, body = readyz(postgres.get_connection_url())
    assert status == 200
    assert body == '{"status":"ok"}'


def test_readyz_returns_503_and_hides_password_on_bad_login(
    postgres: PostgresContainer, caplog: pytest.LogCaptureFixture
) -> None:
    """Return 503 and log no password when Postgres refuses the login."""
    url = postgres.get_connection_url()
    bad_url = url.replace(f":{postgres.password}@", f":{WRONG_PASSWORD}@")
    assert bad_url != url
    with caplog.at_level(logging.WARNING, logger="kamayoq.api.health"):
        status, body = readyz(bad_url)
    assert status == 503
    assert body == '{"status":"unavailable"}'
    assert "Postgres is not ready" in caplog.text
    for password in (WRONG_PASSWORD, postgres.password):
        assert password not in body
        assert password not in caplog.text
