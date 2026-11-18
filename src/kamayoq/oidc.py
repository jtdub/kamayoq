"""Discovery, signing keys, and bearer token check of the OIDC identity provider."""

import asyncio
import logging
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx2
from joserfc import jwt
from joserfc.errors import ClaimError, InvalidKeyIdError, JoseError
from joserfc.jwk import KeySet
from joserfc.jws import extract_compact

from kamayoq.roles import Role, roles_for_groups
from kamayoq.settings import require_secure_url

CLOCK_LEEWAY_SECONDS = 60
"""Difference between the clocks of kamayoq and the IdP that a token check permits."""
JWKS_MAX_AGE_SECONDS = 3600
"""Age after which the key set loads again."""
JWKS_STALE_LIMIT_SECONDS = 86400
"""Age after which an old key set is not used while the IdP fails."""
JWKS_RELOAD_MIN_SECONDS = 60
"""Shortest time between a load and a reload for an unknown key ID."""
FAILURE_BACKOFF_SECONDS = 30
"""Time after a failed load in which no new request goes to the IdP."""
HTTP_TIMEOUT_SECONDS = 5.0
"""Time limit of one request to the IdP."""
ALLOWED_ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "ES256", "ES384")
"""Signature algorithms that a token can use."""
MAX_TOKEN_BYTES = 16 * 1024
"""Largest token that the check decodes."""

logger = logging.getLogger(__name__)


class IdentityProviderError(Exception):
    """Raise when the IdP gives no valid discovery document or key set.

    The message names the URL and the reason. It has no response body.
    """


class InvalidTokenError(Exception):
    """Raise when a bearer token is not valid.

    The message names the reason and the claim. It has no token text.
    """


@dataclass(frozen=True)
class Principal:
    """The identity that a valid token gives."""

    subject: str
    issuer: str
    groups: frozenset[str]
    roles: frozenset[Role] = frozenset()


class _IssuerMismatchError(IdentityProviderError):
    """Raise when the discovery document names another issuer."""


def discovery_url(issuer: str) -> str:
    """Return the URL of the discovery document of the issuer."""
    return issuer.rstrip("/") + "/.well-known/openid-configuration"


async def _get_json_object(client: httpx2.AsyncClient, url: str) -> dict[str, object]:
    """Return the JSON object at the URL.

    Raises:
        IdentityProviderError: If the request fails, the status is not 200, or the
            body is not a JSON object.
    """
    try:
        response = await client.get(url, timeout=HTTP_TIMEOUT_SECONDS)
    except httpx2.RequestError as error:
        raise IdentityProviderError(
            f"{url} did not answer: {type(error).__name__}"
        ) from error
    if response.status_code != 200:
        raise IdentityProviderError(f"{url} returned HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError as error:
        raise IdentityProviderError(f"{url} did not return JSON") from error
    if not isinstance(body, dict):
        raise IdentityProviderError(f"{url} did not return a JSON object")
    return body


class OidcKeys:
    """Load and cache the key set of one issuer, with a reload limit and a backoff.

    A key set is fresh for one hour. While the IdP fails, an old key set stays in use
    for up to 24 hours. After a failed load, no request goes to the IdP for 30 s.
    """

    def __init__(
        self,
        issuer: str,
        client: httpx2.AsyncClient,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Keep the issuer, the HTTP client, and the monotonic clock."""
        self._issuer = issuer
        self._client = client
        self._clock = clock
        self._lock = asyncio.Lock()
        self._key_set: KeySet | None = None
        self._loaded_at = -math.inf
        self._failed_at = -math.inf
        self._failure = "the key set did not load yet"

    async def key_set(self) -> KeySet:
        """Return the key set, and load it when it is not fresh.

        Raises:
            IdentityProviderError: If no key set younger than the stale limit exists
                and the IdP fails or the backoff is active.
        """
        fresh = self._key_set_younger_than(JWKS_MAX_AGE_SECONDS)
        if fresh is not None:
            return fresh
        async with self._lock:
            if (
                self._key_set_younger_than(JWKS_MAX_AGE_SECONDS) is None
                and not self._backoff_is_active()
            ):
                await self._load()
            usable = self._key_set_younger_than(JWKS_STALE_LIMIT_SECONDS)
            if usable is None:
                raise IdentityProviderError(self._failure)
            return usable

    async def reload(self) -> bool:
        """Load the key set again for an unknown key ID.

        Returns:
            True if a new key set loaded after the call started. False if the
            last load is younger than the reload limit, the backoff is active, or
            the load failed.
        """
        loaded_at_start = self._loaded_at
        async with self._lock:
            if self._loaded_at != loaded_at_start:
                return True
            if self._clock() - self._loaded_at < JWKS_RELOAD_MIN_SECONDS:
                return False
            if self._backoff_is_active():
                return False
            return await self._load()

    def _key_set_younger_than(self, seconds: float) -> KeySet | None:
        """Return the key set if it loaded less than the given time ago."""
        if self._clock() - self._loaded_at < seconds:
            return self._key_set
        return None

    def _backoff_is_active(self) -> bool:
        """Return True if the last failed load is in the backoff window."""
        return self._clock() - self._failed_at < FAILURE_BACKOFF_SECONDS

    async def _load(self) -> bool:
        """Fetch the key set, record the result, and log a failure one time."""
        try:
            key_set = await self._fetch()
        except IdentityProviderError as error:
            self._failed_at = self._clock()
            self._failure = str(error)
            is_mismatch = isinstance(error, _IssuerMismatchError)
            level = logging.ERROR if is_mismatch else logging.WARNING
            logger.log(
                level,
                "The OIDC identity provider failed: %s. "
                "kamayoq sends no request to it for %s s.",
                error,
                FAILURE_BACKOFF_SECONDS,
            )
            return False
        self._key_set = key_set
        self._loaded_at = self._clock()
        return True

    async def _fetch(self) -> KeySet:
        """Fetch the discovery document, then the key set that it names.

        Raises:
            IdentityProviderError: If a document is not valid.
        """
        url = discovery_url(self._issuer)
        discovery = await _get_json_object(self._client, url)
        if discovery.get("issuer") != self._issuer:
            raise _IssuerMismatchError(
                f"{url} names the issuer {discovery.get('issuer')!r:.200}, "
                f"but KAMAYOQ_OIDC_ISSUER is {self._issuer!r}"
            )
        jwks_uri = discovery.get("jwks_uri")
        if not isinstance(jwks_uri, str):
            raise IdentityProviderError(f"{url} has no jwks_uri")
        try:
            require_secure_url(jwks_uri)
        except ValueError as error:
            raise IdentityProviderError(f"{url} has a bad jwks_uri: {error}") from error
        jwks = await _get_json_object(self._client, jwks_uri)
        keys = jwks.get("keys")
        if not isinstance(keys, list) or not all(isinstance(k, dict) for k in keys):
            raise IdentityProviderError(f"{jwks_uri} has no list of key objects")
        try:
            return KeySet.import_key_set({"keys": keys})
        except (KeyError, TypeError, ValueError, JoseError) as error:
            raise IdentityProviderError(
                f"{jwks_uri} has a key set that cannot load: {type(error).__name__}"
            ) from error


def _string_set(value: object) -> frozenset[str]:
    """Return a list of strings as a set, and each other value as an empty set."""
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return frozenset(value)
    return frozenset()


class OidcVerifier:
    """Check the signature and the claims of a bearer token of one issuer."""

    def __init__(
        self,
        keys: OidcKeys,
        issuer: str,
        audience: str,
        groups_claim: str,
        role_map: Mapping[str, frozenset[Role]] | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        """Keep the key cache, the expected claims, the role map, and the wall clock."""
        self._keys = keys
        self._groups_claim = groups_claim
        self._role_map = role_map or {}
        self._claims_registry = jwt.JWTClaimsRegistry(
            now=lambda: int(now()),
            leeway=CLOCK_LEEWAY_SECONDS,
            iss={"essential": True, "value": issuer},
            aud={"essential": True, "value": audience},
            exp={"essential": True},
            sub={"essential": True},
        )

    async def verify(self, token: str) -> Principal:
        """Return the principal of a valid token.

        A groups claim that is not a list of strings gives no groups. The roles
        are the roles of each group in the role map.

        Raises:
            InvalidTokenError: If the token is not valid.
            IdentityProviderError: If no key set is available.
        """
        if not token.isascii():
            raise InvalidTokenError("the token has a character that is not ASCII")
        if len(token) > MAX_TOKEN_BYTES:
            raise InvalidTokenError(f"the token is larger than {MAX_TOKEN_BYTES} bytes")
        try:
            claims = await self._decode(token)
            self._claims_registry.validate(claims)
        except ClaimError as error:
            raise InvalidTokenError(
                f"{error.error} in the claim {error.claim}"
            ) from None
        except JoseError as error:
            raise InvalidTokenError(error.error) from None
        groups = _string_set(claims.get(self._groups_claim))
        return Principal(
            subject=claims["sub"],
            issuer=claims["iss"],
            groups=groups,
            roles=roles_for_groups(groups, self._role_map),
        )

    async def _decode(self, token: str) -> dict[str, Any]:
        """Return the claims of a token with a valid signature.

        An unknown key ID reloads the key set one time, within the reload limit.
        """
        try:
            return self._decode_with(token, await self._keys.key_set())
        except InvalidKeyIdError:
            if not extract_compact(token.encode()).headers().get("kid"):
                raise InvalidTokenError(
                    "the token has no kid, and the key set has more than one key"
                ) from None
            if not await self._keys.reload():
                raise
        return self._decode_with(token, await self._keys.key_set())

    @staticmethod
    def _decode_with(token: str, key_set: KeySet) -> dict[str, Any]:
        """Return the claims of the token, signed by a key of the key set."""
        return jwt.decode(token, key_set, algorithms=ALLOWED_ALGORITHMS).claims
