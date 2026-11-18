"""Integration tests of the API token check against a Keycloak container."""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Iterator

import httpx2
import pytest
from fastapi.testclient import TestClient

from kamayoq.api.app import create_app
from kamayoq.oidc import InvalidTokenError, OidcKeys, OidcVerifier
from kamayoq.settings import Settings

DATABASE_URL = "postgresql://kamayoq@127.0.0.1:1/kamayoq"
TEST_REALM = "kamayoq-test"
OTHER_REALM = "kamayoq-other"
CLI_CLIENT = "kamayoq-cli"
OTHER_CLIENT = "kamayoq-other"
API_AUDIENCE = "kamayoq-api"
ALICE_PASSWORD = "alice-test-only-password"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


def realm_url(keycloak: str, realm: str = TEST_REALM) -> str:
    """Return the issuer URL of the realm."""
    return f"{keycloak}/realms/{realm}"


def password_token(
    keycloak: str, realm: str = TEST_REALM, client_id: str = CLI_CLIENT
) -> str:
    """Return an access token of alice from the password grant."""
    response = httpx2.post(
        f"{realm_url(keycloak, realm)}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": client_id,
            "username": "alice",
            "password": ALICE_PASSWORD,
        },
    )
    response.raise_for_status()
    token: str = response.json()["access_token"]
    return token


def b64url(data: bytes) -> str:
    """Return the data in base64url form with no padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_json(segment: str) -> dict[str, object]:
    """Return the JSON object of a base64url token segment."""
    decoded: dict[str, object] = json.loads(
        base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    )
    return decoded


@pytest.fixture
def client(keycloak: str) -> Iterator[TestClient]:
    """Return a started test client of an app that trusts the kamayoq-test realm."""
    settings = Settings(
        database_url=DATABASE_URL,
        oidc_issuer=realm_url(keycloak),
        oidc_audience=API_AUDIENCE,
    )
    with TestClient(create_app(settings)) as started:
        yield started


@pytest.fixture
def alice_token(keycloak: str) -> str:
    """Return an access token of alice from the kamayoq-test realm."""
    return password_token(keycloak)


def assert_refused(
    client: TestClient, token: str, caplog: pytest.LogCaptureFixture, reason: str
) -> None:
    """Assert that GET /v1/me gives 401, and that the log names the reason."""
    with caplog.at_level(logging.INFO, logger="kamayoq.api.auth"):
        response = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert reason in caplog.text


def test_keycloak_token_gives_subject_and_groups(
    client: TestClient, alice_token: str, keycloak: str
) -> None:
    """Accept a Keycloak token and return its subject and groups (AC-1, AC-5)."""
    response = client.get("/v1/me", headers={"Authorization": f"Bearer {alice_token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == b64url_json(alice_token.split(".")[1])["sub"]
    assert body["issuer"] == realm_url(keycloak)
    assert body["groups"] == ["/kamayoq-admins"]


def test_token_of_other_client_has_wrong_audience(
    client: TestClient, keycloak: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Refuse a token whose audience is not kamayoq-api (AC-2, AC-5)."""
    token = password_token(keycloak, client_id=OTHER_CLIENT)
    assert_refused(client, token, caplog, "in the claim aud")


def test_token_of_other_realm_has_wrong_issuer(
    client: TestClient, keycloak: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Refuse a token of another realm (AC-2, AC-5).

    Each realm has its own signing keys, so the key ID check refuses the token.
    """
    token = password_token(keycloak, realm=OTHER_REALM)
    assert b64url_json(token.split(".")[1])["iss"] == realm_url(keycloak, OTHER_REALM)
    assert_refused(client, token, caplog, "invalid_key_id")


def test_changed_signature_is_refused(
    client: TestClient, alice_token: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Refuse a token with one changed character in the signature (AC-2, AC-5)."""
    header, payload, signature = alice_token.split(".")
    middle = len(signature) // 2
    changed = "B" if signature[middle] == "A" else "A"
    tampered = signature[:middle] + changed + signature[middle + 1 :]
    assert_refused(client, f"{header}.{payload}.{tampered}", caplog, "bad_signature")


def test_alg_none_is_refused(
    client: TestClient, alice_token: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Refuse the token with the none algorithm and no signature (AC-2, AC-5)."""
    payload = alice_token.split(".")[1]
    header = b64url(json.dumps({"alg": "none"}).encode())
    assert_refused(client, f"{header}.{payload}.", caplog, "unsupported_algorithm")


def test_hs256_with_realm_public_key_is_refused(
    client: TestClient,
    alice_token: str,
    keycloak: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Refuse the claims signed with HS256 and the public key as secret (AC-2, AC-5)."""
    original_header, payload, _ = alice_token.split(".")
    public_key = httpx2.get(realm_url(keycloak)).json()["public_key"]
    kid = b64url_json(original_header)["kid"]
    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT", "kid": kid}).encode())
    signing_input = f"{header}.{payload}".encode()
    mac = hmac.new(public_key.encode(), signing_input, hashlib.sha256).digest()
    forged = f"{header}.{payload}.{b64url(mac)}"
    assert_refused(client, forged, caplog, "unsupported_algorithm")


def test_expired_keycloak_token_is_refused(alice_token: str, keycloak: str) -> None:
    """Refuse the token when the clock is one hour later (AC-2, AC-5)."""
    issuer = realm_url(keycloak)

    async def verify_one_hour_later() -> None:
        async with httpx2.AsyncClient() as http:
            verifier = OidcVerifier(
                OidcKeys(issuer, http),
                issuer,
                API_AUDIENCE,
                "groups",
                now=lambda: time.time() + 3600,
            )
            await verifier.verify(alice_token)

    with pytest.raises(InvalidTokenError, match="exp"):
        asyncio.run(verify_one_hour_later())


def test_device_authorization_gives_user_code_and_pending_poll(
    keycloak: str,
) -> None:
    """Start a device login and get authorization_pending at the first poll."""
    endpoints = f"{realm_url(keycloak)}/protocol/openid-connect"
    device = httpx2.post(f"{endpoints}/auth/device", data={"client_id": CLI_CLIENT})
    assert device.status_code == 200
    assert device.json()["user_code"]
    poll = httpx2.post(
        f"{endpoints}/token",
        data={
            "grant_type": DEVICE_GRANT,
            "client_id": CLI_CLIENT,
            "device_code": device.json()["device_code"],
        },
    )
    assert poll.status_code == 400
    assert poll.json()["error"] == "authorization_pending"
