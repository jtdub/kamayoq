"""Unit tests for the bearer token check on the /v1 routes."""

import logging
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from fake_idp import (
    DISCOVERY_PATH,
    FAKE_AUDIENCE,
    FAKE_ISSUER,
    FakeIdp,
    assert_no_token_text,
)
from fastapi import APIRouter, FastAPI
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient

from kamayoq.api import app as app_module
from kamayoq.api import auth
from kamayoq.api.app import create_app
from kamayoq.api.health import ReadinessCheck
from kamayoq.settings import Settings

DATABASE_URL = "postgresql://kamayoq@127.0.0.1:1/kamayoq"


@pytest.fixture
def idp() -> FakeIdp:
    """Return a fake IdP."""
    return FakeIdp()


@pytest.fixture
def made_clients(
    idp: FakeIdp, monkeypatch: pytest.MonkeyPatch
) -> list[httpx2.AsyncClient]:
    """Connect each IdP client that create_app makes to the fake IdP, and keep it."""
    clients: list[httpx2.AsyncClient] = []

    def client_with_fake_transport(**options: Any) -> httpx2.AsyncClient:
        made = httpx2.AsyncClient(transport=idp.transport, **options)
        clients.append(made)
        return made

    fake_httpx2 = SimpleNamespace(AsyncClient=client_with_fake_transport)
    monkeypatch.setattr(app_module, "httpx2", fake_httpx2)
    return clients


def oidc_app() -> FastAPI:
    """Return an app with the OIDC settings of the fake IdP."""
    settings = Settings(
        database_url=DATABASE_URL,
        oidc_issuer=FAKE_ISSUER,
        oidc_audience=FAKE_AUDIENCE,
    )
    return create_app(settings)


@pytest.fixture
def client(made_clients: list[httpx2.AsyncClient]) -> Iterator[TestClient]:
    """Return a started test client of an app with OIDC settings."""
    with TestClient(oidc_app()) as started:
        yield started


def bearer(token: str) -> dict[str, str]:
    """Return the Authorization header for the token."""
    return {"Authorization": f"Bearer {token}"}


def test_no_oidc_settings_gives_401_and_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Refuse each protected route when the server has no OIDC settings (E1)."""
    with caplog.at_level(logging.WARNING):
        app = create_app(Settings(database_url=DATABASE_URL))
    warnings = [r for r in caplog.records if r.name == app_module.logger.name]
    assert [r.getMessage() for r in warnings] == [
        "OIDC settings are not set, so each protected route returns 401"
    ]
    with TestClient(app) as started:
        response = started.get("/v1/me", headers=bearer("abc"))
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {"detail": auth.NOT_CONFIGURED_DETAIL}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Basic abc"}])
def test_missing_bearer_header_gives_401(
    client: TestClient, headers: dict[str, str]
) -> None:
    """Refuse a request with no bearer token (E12)."""
    response = client.get("/v1/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_good_token_gives_the_principal(client: TestClient, idp: FakeIdp) -> None:
    """Return the subject, the issuer, and the sorted groups (AC-1)."""
    token = idp.token(groups=["operators", "admins"])
    response = client.get("/v1/me", headers=bearer(token))
    assert response.status_code == 200
    assert response.json() == {
        "subject": "user-1",
        "issuer": FAKE_ISSUER,
        "groups": ["admins", "operators"],
    }


@pytest.mark.parametrize(
    "token_of",
    [
        lambda idp: idp.token(aud="other"),
        lambda idp: idp.token(iss="https://other.example.com"),
        lambda idp: idp.token(exp=1),
        lambda idp: idp.unsigned_token(),
        lambda idp: idp.hs256_token_with_the_public_key(),
        lambda idp: "not-a-token",
    ],
    ids=["aud", "iss", "exp", "alg-none", "hs256", "garbage"],
)
def test_bad_token_gives_401_invalid_token(
    client: TestClient,
    idp: FakeIdp,
    token_of: Callable[[FakeIdp], str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Refuse a token that is not valid, and log the reason only (AC-2)."""
    token = token_of(idp)
    with caplog.at_level(logging.DEBUG):
        response = client.get("/v1/me", headers=bearer(token))
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Bearer error="invalid_token"'
    infos = [r for r in caplog.records if r.name == auth.logger.name]
    assert len(infos) == 1
    assert infos[0].levelno == logging.INFO
    assert_no_token_text(token, caplog.text, response.text)


def test_identity_provider_failure_gives_503_and_readyz_is_unchanged(
    client: TestClient,
    idp: FakeIdp,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Return 503 while the IdP fails, and keep /readyz as it is (E4)."""

    async def postgres_answers(self: ReadinessCheck) -> bool:
        return True

    monkeypatch.setattr(ReadinessCheck, "_check", postgres_answers)
    idp.status[DISCOVERY_PATH] = 500
    token = idp.token()
    with caplog.at_level(logging.DEBUG):
        first = client.get("/v1/me", headers=bearer(token))
        second = client.get("/v1/me", headers=bearer(token))
    assert [first.status_code, second.status_code] == [503, 503]
    assert idp.requests[DISCOVERY_PATH] == 1
    assert client.get("/readyz").status_code == 200
    assert not [r for r in caplog.records if r.name == auth.logger.name]
    assert_no_token_text(token, caplog.text, first.text)


def test_healthz_needs_no_token(client: TestClient) -> None:
    """Answer /healthz with no token."""
    assert client.get("/healthz").status_code == 200


def test_new_route_on_the_protected_router_needs_a_token(
    made_clients: list[httpx2.AsyncClient],
) -> None:
    """Protect a route that has no auth code of its own (E13a)."""
    protected = auth.build_protected_router()
    probe = APIRouter()

    @probe.get("/probe")
    async def probe_route() -> dict[str, str]:
        return {"status": "open"}

    protected.include_router(probe)
    app = oidc_app()
    app.include_router(protected)
    with TestClient(app) as started:
        response = started.get("/v1/probe")
    assert response.status_code == 401


def test_each_v1_route_not_on_the_public_list_needs_a_token(
    client: TestClient,
) -> None:
    """Refuse each /v1 route of the app with no token (E13a)."""
    routes = [
        (method, route.path)
        for route in iter_route_contexts(client.app.routes)  # type: ignore[attr-defined]
        if route.path is not None
        and route.path.startswith("/v1/")
        and route.path not in auth.PUBLIC_V1_PATHS
        for method in route.methods or ()
    ]
    assert ("GET", "/v1/me") in routes
    for method, path in routes:
        assert client.request(method, path).status_code == 401, (method, path)


def test_app_stop_closes_the_http_client(
    made_clients: list[httpx2.AsyncClient],
) -> None:
    """Close the HTTP client of the IdP when the app stops."""
    with TestClient(oidc_app()):
        assert [made.is_closed for made in made_clients] == [False]
    assert [made.is_closed for made in made_clients] == [True]


def test_app_stop_closes_the_http_client_when_the_engine_fails(
    made_clients: list[httpx2.AsyncClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Close the HTTP client of the IdP when the engine dispose raises."""
    app = oidc_app()

    async def failing_dispose(self: object, close: bool = True) -> None:
        raise RuntimeError("dispose failed")

    monkeypatch.setattr(type(app.state.engine), "dispose", failing_dispose)
    with pytest.raises(RuntimeError, match="dispose failed"), TestClient(app):
        pass
    assert [made.is_closed for made in made_clients] == [True]
