"""A fake OIDC identity provider for unit tests, served by an httpx2 MockTransport."""

import asyncio
import base64
import hashlib
import hmac
import json
import time
from collections import Counter

import httpx2
from joserfc import jwt
from joserfc.jwk import ECKey, KeySet, RSAKey

FAKE_ISSUER = "https://idp.example.com/realms/kamayoq"
DISCOVERY_PATH = "/realms/kamayoq/.well-known/openid-configuration"
JWKS_PATH = "/realms/kamayoq/protocol/openid-connect/certs"
FAKE_AUDIENCE = "kamayoq-api"


def _base64url_json(value: dict[str, object]) -> str:
    """Return the value as JSON in base64url text with no padding."""
    return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()


class FakeIdp:
    """Answer discovery and JWKS requests, and count the requests to each path.

    Tests change the answers with the public attributes. A body of bytes goes out
    as it is. Each other body goes out as JSON.
    """

    def __init__(self, issuer: str = FAKE_ISSUER) -> None:
        """Make the signing keys and the default answers."""
        self.issuer = issuer
        self.rsa_key = RSAKey.generate_key(2048, parameters={"kid": "rsa-1"})
        self.ec_key = ECKey.generate_key("P-256", parameters={"kid": "ec-1"})
        self.ec384_key = ECKey.generate_key("P-384", parameters={"kid": "ec-384"})
        self.ec521_key = ECKey.generate_key("P-521", parameters={"kid": "ec-521"})
        self.next_key = RSAKey.generate_key(2048, parameters={"kid": "rsa-2"})
        self.published: list[RSAKey | ECKey] = [
            self.rsa_key,
            self.ec_key,
            self.ec384_key,
            self.ec521_key,
        ]
        self.requests: Counter[str] = Counter()
        self.status: dict[str, int] = {}
        self.errors: dict[str, type[httpx2.RequestError]] = {}
        self.bodies: dict[str, object] = {}
        self.transport = httpx2.MockTransport(self.handle)

    def client(self) -> httpx2.AsyncClient:
        """Return an HTTP client that sends each request to this IdP."""
        return httpx2.AsyncClient(transport=self.transport)

    def jwks(self) -> dict[str, object]:
        """Return the public key set as a JSON object."""
        key_set = KeySet(list(self.published))
        return dict(key_set.as_dict(private=False))

    def rotate(self) -> None:
        """Publish the next key in the key set."""
        self.published.append(self.next_key)

    def claims(self, **claims: object) -> dict[str, object]:
        """Return valid token claims with the changes. A value of None removes it."""
        now = int(time.time())
        defaults: dict[str, object] = {
            "iss": self.issuer,
            "aud": FAKE_AUDIENCE,
            "sub": "user-1",
            "iat": now,
            "exp": now + 300,
            "groups": ["admins", "operators"],
        }
        merged = defaults | claims
        return {name: value for name, value in merged.items() if value is not None}

    def token(
        self,
        alg: str = "RS256",
        kid: str | None = "",
        key: RSAKey | ECKey | None = None,
        **claims: object,
    ) -> str:
        """Return a JWT signed with the key, or with the key of this IdP for the alg.

        An empty kid gives the kid of the key. A kid of None leaves it out.
        """
        keys_for_alg: dict[str, RSAKey | ECKey] = {
            "ES256": self.ec_key,
            "ES384": self.ec384_key,
            "ES512": self.ec521_key,
        }
        signing_key: RSAKey | ECKey = key or keys_for_alg.get(alg, self.rsa_key)
        header: dict[str, object] = {"alg": alg}
        if kid is not None:
            header["kid"] = kid or signing_key.kid
        return jwt.encode(header, self.claims(**claims), signing_key, algorithms=[alg])

    def unsigned_token(self, alg: str = "none") -> str:
        """Return a JWT with the alg and no signature."""
        header = _base64url_json({"alg": alg, "kid": self.rsa_key.kid})
        return f"{header}.{_base64url_json(self.claims())}."

    def hs256_token_with_the_public_key(self) -> str:
        """Return an HS256 JWT with the public RSA key as the HMAC secret."""
        signing_input = self.unsigned_token("HS256").rstrip(".")
        secret = self.rsa_key.as_pem(private=False)
        digest = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
        signature = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        return f"{signing_input}.{signature}"

    def discovery(self) -> dict[str, object]:
        """Return the discovery document."""
        return {
            "issuer": self.issuer,
            "jwks_uri": "https://idp.example.com" + JWKS_PATH,
        }

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        """Return the answer for the path of the request.

        Raises:
            httpx2.RequestError: The error that errors names for the path.
        """
        await asyncio.sleep(0)
        path = request.url.path
        self.requests[path] += 1
        if path in self.errors:
            raise self.errors[path]("fake error", request=request)
        default_bodies: dict[str, object] = {
            DISCOVERY_PATH: self.discovery(),
            JWKS_PATH: self.jwks(),
        }
        body = self.bodies.get(path, default_bodies.get(path, {"error": "not found"}))
        default_status = 200 if path in default_bodies else 404
        content = body if isinstance(body, bytes) else json.dumps(body).encode()
        return httpx2.Response(self.status.get(path, default_status), content=content)
