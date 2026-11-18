"""A fake OIDC identity provider for unit tests, served by an httpx2 MockTransport."""

import asyncio
import json
from collections import Counter

import httpx2
from joserfc.jwk import ECKey, KeySet, RSAKey

FAKE_ISSUER = "https://idp.example.com/realms/kamayoq"
DISCOVERY_PATH = "/realms/kamayoq/.well-known/openid-configuration"
JWKS_PATH = "/realms/kamayoq/protocol/openid-connect/certs"


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
        key_set = KeySet([self.rsa_key, self.ec_key])
        return dict(key_set.as_dict(private=False))

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
