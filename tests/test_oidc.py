"""Unit tests for the OIDC discovery, the key cache, and the token check."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx2
import pytest
from fake_idp import DISCOVERY_PATH, FAKE_AUDIENCE, FAKE_ISSUER, JWKS_PATH, FakeIdp
from joserfc.jwk import KeySet, RSAKey

from kamayoq.oidc import (
    CLOCK_LEEWAY_SECONDS,
    FAILURE_BACKOFF_SECONDS,
    JWKS_MAX_AGE_SECONDS,
    JWKS_RELOAD_MIN_SECONDS,
    JWKS_STALE_LIMIT_SECONDS,
    MAX_TOKEN_BYTES,
    IdentityProviderError,
    InvalidTokenError,
    OidcKeys,
    OidcVerifier,
    Principal,
    discovery_url,
)

SECRET_BODY_TEXT = "body-text-that-must-not-leak"


class FakeClock:
    """Give a monotonic time that a test moves by hand."""

    def __init__(self) -> None:
        """Start at 1000 s."""
        self.now = 1000.0

    def __call__(self) -> float:
        """Return the current fake time."""
        return self.now


def run_with_keys[T](
    idp: FakeIdp, clock: FakeClock, scenario: Callable[[OidcKeys], Awaitable[T]]
) -> T:
    """Run the scenario on one event loop with an OidcKeys of the fake IdP."""

    async def main() -> T:
        async with idp.client() as client:
            return await scenario(OidcKeys(FAKE_ISSUER, client, clock=clock))

    return asyncio.run(main())


def oidc_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Return the log records of the kamayoq.oidc logger."""
    return [record for record in caplog.records if record.name == "kamayoq.oidc"]


def test_key_set_loads_discovery_and_jwks_once_for_two_calls() -> None:
    """Load the documents once and answer the second call from the cache."""
    idp = FakeIdp()

    async def scenario(keys: OidcKeys) -> tuple[KeySet, KeySet]:
        return await keys.key_set(), await keys.key_set()

    first, second = run_with_keys(idp, FakeClock(), scenario)
    assert first is second
    assert first.get_by_kid("rsa-1") is not None
    assert idp.requests == {DISCOVERY_PATH: 1, JWKS_PATH: 1}


def test_ten_key_set_calls_at_the_same_time_send_one_load() -> None:
    """Send one discovery and one JWKS request for ten calls at the same time."""
    idp = FakeIdp()

    async def scenario(keys: OidcKeys) -> list[KeySet]:
        return await asyncio.gather(*(keys.key_set() for _ in range(10)))

    results = run_with_keys(idp, FakeClock(), scenario)
    assert len({id(result) for result in results}) == 1
    assert idp.requests == {DISCOVERY_PATH: 1, JWKS_PATH: 1}


def test_key_set_loads_again_after_the_max_age() -> None:
    """Load the documents again when the key set is older than one hour."""
    idp = FakeIdp()
    clock = FakeClock()

    async def scenario(keys: OidcKeys) -> None:
        await keys.key_set()
        clock.now += JWKS_MAX_AGE_SECONDS - 1
        await keys.key_set()
        assert idp.requests[JWKS_PATH] == 1
        clock.now += 2
        await keys.key_set()

    run_with_keys(idp, clock, scenario)
    assert idp.requests == {DISCOVERY_PATH: 2, JWKS_PATH: 2}


def test_reload_loads_at_most_once_in_each_reload_interval() -> None:
    """Refuse a reload within 60 s, load after 61 s, and answer waiters True."""
    idp = FakeIdp()
    clock = FakeClock()
    results: list[bool] = []

    async def scenario(keys: OidcKeys) -> None:
        await keys.key_set()
        clock.now += JWKS_RELOAD_MIN_SECONDS - 1
        results.append(await keys.reload())
        assert idp.requests[JWKS_PATH] == 1
        clock.now += 2
        results.append(await keys.reload())
        clock.now += 1
        results.append(await keys.reload())
        clock.now += JWKS_RELOAD_MIN_SECONDS + 1
        results.extend(await asyncio.gather(keys.reload(), keys.reload()))

    run_with_keys(idp, clock, scenario)
    assert results == [False, True, False, True, True]
    assert idp.requests == {DISCOVERY_PATH: 3, JWKS_PATH: 3}


def test_discovery_issuer_with_a_trailing_slash_is_an_error_with_one_error_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reject a discovery issuer that differs, and log both values one time."""
    idp = FakeIdp()
    idp.bodies[DISCOVERY_PATH] = {"issuer": FAKE_ISSUER + "/"}
    caplog.set_level(logging.WARNING)

    async def scenario(keys: OidcKeys) -> None:
        for _ in range(3):
            with pytest.raises(IdentityProviderError):
                await keys.key_set()

    run_with_keys(idp, FakeClock(), scenario)
    records = oidc_records(caplog)
    assert [record.levelno for record in records] == [logging.ERROR]
    assert FAKE_ISSUER + "/'" in records[0].getMessage()
    assert FAKE_ISSUER + "'" in records[0].getMessage()
    assert idp.requests[JWKS_PATH] == 0


HTTP_JWKS_URI = {
    "issuer": FAKE_ISSUER,
    "jwks_uri": "http://idp.example.com" + JWKS_PATH,
}


@pytest.mark.parametrize(
    ("path", "status", "body"),
    [
        (DISCOVERY_PATH, 500, {"error": SECRET_BODY_TEXT}),
        (JWKS_PATH, 500, {"error": SECRET_BODY_TEXT}),
        (DISCOVERY_PATH, httpx2.ReadTimeout, None),
        (JWKS_PATH, httpx2.ReadTimeout, None),
        (DISCOVERY_PATH, httpx2.DecodingError, None),
        (JWKS_PATH, httpx2.DecodingError, None),
        (DISCOVERY_PATH, 200, SECRET_BODY_TEXT.encode()),
        (JWKS_PATH, 200, SECRET_BODY_TEXT.encode()),
        (DISCOVERY_PATH, 200, [SECRET_BODY_TEXT]),
        (DISCOVERY_PATH, 200, {"issuer": FAKE_ISSUER}),
        (DISCOVERY_PATH, 200, HTTP_JWKS_URI),
        (DISCOVERY_PATH, 200, {"issuer": "x" * 10000}),
        (JWKS_PATH, 200, {"keys": SECRET_BODY_TEXT}),
        (JWKS_PATH, 200, {"keys": [SECRET_BODY_TEXT]}),
        (JWKS_PATH, 200, {"keys": [{"kty": "nope", "x": SECRET_BODY_TEXT}]}),
        (JWKS_PATH, 200, {"keys": [{"x": SECRET_BODY_TEXT}]}),
        (JWKS_PATH, 200, {"keys": []}),
    ],
)
def test_a_bad_answer_of_the_idp_is_an_error_with_no_response_body(
    path: str, status: int | type[httpx2.RequestError], body: object
) -> None:
    """Raise IdentityProviderError with no response body for each bad answer.

    A status that is an httpx2 error class makes the request raise it.
    """
    idp = FakeIdp()
    if not isinstance(status, int):
        idp.errors[path] = status
    else:
        idp.status[path] = status
        idp.bodies[path] = body

    async def scenario(keys: OidcKeys) -> IdentityProviderError:
        with pytest.raises(IdentityProviderError) as caught:
            await keys.key_set()
        return caught.value

    error = run_with_keys(idp, FakeClock(), scenario)
    assert SECRET_BODY_TEXT not in str(error)
    assert len(str(error)) < 500


def test_discovery_url_has_one_slash_before_well_known() -> None:
    """Join the issuer and the well-known path with one slash."""
    expected = FAKE_ISSUER + "/.well-known/openid-configuration"
    assert discovery_url(FAKE_ISSUER + "/") == expected
    assert discovery_url(FAKE_ISSUER) == expected


def test_failure_backoff_sends_no_request_and_writes_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Fail at once with no request in the backoff window, then fetch again."""
    idp = FakeIdp()
    idp.status[DISCOVERY_PATH] = 500
    clock = FakeClock()
    caplog.set_level(logging.WARNING)

    async def scenario(keys: OidcKeys) -> None:
        for _ in range(10):
            with pytest.raises(IdentityProviderError):
                await keys.key_set()
            clock.now += 1
        assert idp.requests[DISCOVERY_PATH] == 1
        assert not await keys.reload()
        assert idp.requests[DISCOVERY_PATH] == 1
        clock.now = 1000.0 + FAILURE_BACKOFF_SECONDS + 1
        with pytest.raises(IdentityProviderError):
            await keys.key_set()

    run_with_keys(idp, clock, scenario)
    assert idp.requests[DISCOVERY_PATH] == 2
    levels = [record.levelno for record in oidc_records(caplog)]
    assert levels == [logging.WARNING, logging.WARNING]


def test_old_keys_stay_in_use_until_the_stale_limit_when_a_refresh_fails() -> None:
    """Return the old keys after a failed refresh, and raise after 24 hours."""
    idp = FakeIdp()
    clock = FakeClock()

    async def scenario(keys: OidcKeys) -> None:
        loaded = await keys.key_set()
        idp.status[JWKS_PATH] = 500
        clock.now += JWKS_MAX_AGE_SECONDS + 1
        assert await keys.key_set() is loaded
        assert await keys.key_set() is loaded
        assert idp.requests[JWKS_PATH] == 2
        clock.now = 1000.0 + JWKS_STALE_LIMIT_SECONDS + 1
        with pytest.raises(IdentityProviderError):
            await keys.key_set()

    run_with_keys(idp, clock, scenario)
    assert idp.requests[JWKS_PATH] == 3


def run_verifier[T](
    idp: FakeIdp,
    scenario: Callable[[OidcVerifier], Awaitable[T]],
    clock: FakeClock | None = None,
    now: Callable[[], float] = time.time,
    groups_claim: str = "groups",
) -> T:
    """Run the scenario on one event loop with an OidcVerifier of the fake IdP."""

    async def main() -> T:
        async with idp.client() as client:
            keys = OidcKeys(FAKE_ISSUER, client, clock=clock or FakeClock())
            verifier = OidcVerifier(
                keys, FAKE_ISSUER, FAKE_AUDIENCE, groups_claim, now=now
            )
            return await scenario(verifier)

    return asyncio.run(main())


def verify_token(
    idp: FakeIdp,
    token: str,
    now: Callable[[], float] = time.time,
    groups_claim: str = "groups",
) -> Principal:
    """Return the principal of one token, checked by a new verifier."""
    return run_verifier(
        idp, lambda verifier: verifier.verify(token), now=now, groups_claim=groups_claim
    )


def assert_no_token_text(token: str, *texts: str) -> None:
    """Fail if a text holds a part of the token."""
    for part in filter(None, token.split(".")):
        for text in texts:
            assert part[:40] not in text


@pytest.fixture
def rejected(
    caplog: pytest.LogCaptureFixture,
) -> Callable[..., InvalidTokenError]:
    """Return a check that a token is rejected with no token text in logs or error."""
    caplog.set_level(logging.DEBUG)

    def check(
        idp: FakeIdp, token: str, now: Callable[[], float] = time.time
    ) -> InvalidTokenError:
        with pytest.raises(InvalidTokenError) as caught:
            verify_token(idp, token, now=now)
        assert_no_token_text(token, str(caught.value), caplog.text)
        return caught.value

    return check


Rejected = Callable[..., InvalidTokenError]


def test_a_good_rs256_token_gives_the_subject_the_issuer_and_the_groups() -> None:
    """Return the principal of a valid token (AC-1)."""
    idp = FakeIdp()
    principal = verify_token(idp, idp.token())
    assert principal == Principal(
        subject="user-1",
        issuer=FAKE_ISSUER,
        groups=frozenset({"admins", "operators"}),
    )


@pytest.mark.parametrize("alg", ["RS384", "PS256", "ES256", "ES384"])
def test_a_good_token_of_each_allowed_algorithm_is_accepted(alg: str) -> None:
    """Accept each algorithm on the list, also the ones joserfc does not recommend."""
    idp = FakeIdp()
    assert verify_token(idp, idp.token(alg)).subject == "user-1"


def test_a_token_with_the_wrong_audience_is_rejected(rejected: Rejected) -> None:
    """Reject a token for another audience, such as an ID token (AC-2, E13)."""
    idp = FakeIdp()
    rejected(idp, idp.token(aud="kamayoq-cli"))


def test_a_list_audience_is_accepted_only_with_the_kamayoq_audience(
    rejected: Rejected,
) -> None:
    """Accept a list aud that holds the audience, and reject one that does not."""
    idp = FakeIdp()
    assert verify_token(idp, idp.token(aud=["account", FAKE_AUDIENCE])).subject
    rejected(idp, idp.token(aud=["account", "kamayoq-cli"]))


def test_a_token_with_the_wrong_issuer_is_rejected(rejected: Rejected) -> None:
    """Reject a token of another issuer (AC-2)."""
    idp = FakeIdp()
    rejected(idp, idp.token(iss=FAKE_ISSUER + "/"))


FIXED_NOW = 2_000_000_000
PAST_LEEWAY = CLOCK_LEEWAY_SECONDS + 1
IN_LEEWAY = CLOCK_LEEWAY_SECONDS - 1


@pytest.mark.parametrize(
    ("claims", "accepted"),
    [
        ({"exp": FIXED_NOW - IN_LEEWAY}, True),
        ({"exp": FIXED_NOW - PAST_LEEWAY}, False),
        ({"nbf": FIXED_NOW + IN_LEEWAY}, True),
        ({"nbf": FIXED_NOW + PAST_LEEWAY}, False),
        ({"iat": FIXED_NOW + IN_LEEWAY}, True),
        ({"iat": FIXED_NOW + PAST_LEEWAY}, False),
    ],
)
def test_time_claims_permit_a_leeway_of_60_seconds(
    claims: dict[str, Any], accepted: bool, rejected: Rejected
) -> None:
    """Accept a time claim within 60 s of now, and reject one past it (AC-2, E8)."""
    idp = FakeIdp()
    token = idp.token(**({"iat": FIXED_NOW, "exp": FIXED_NOW + 300} | claims))
    if accepted:
        assert verify_token(idp, token, now=lambda: FIXED_NOW).subject == "user-1"
    else:
        rejected(idp, token, now=lambda: FIXED_NOW)


@pytest.mark.parametrize("claim", ["exp", "sub", "iss", "aud"])
def test_a_token_without_an_essential_claim_is_rejected(
    claim: str, rejected: Rejected
) -> None:
    """Reject a token with no exp, sub, iss, or aud (E9)."""
    idp = FakeIdp()
    without_claim: dict[str, Any] = {claim: None}
    error = rejected(idp, idp.token(**without_claim))
    assert claim in str(error)


def test_a_token_signed_by_another_key_with_a_known_kid_is_rejected(
    rejected: Rejected,
) -> None:
    """Reject a bad signature (AC-2)."""
    idp = FakeIdp()
    other_key = RSAKey.generate_key(2048, parameters={"kid": "rsa-1"})
    rejected(idp, idp.token(key=other_key))


def test_none_hs256_and_es512_tokens_are_rejected(rejected: Rejected) -> None:
    """Reject each algorithm that is not on the list (AC-2, E7)."""
    idp = FakeIdp()
    rejected(idp, idp.unsigned_token())
    rejected(idp, idp.hs256_token_with_the_public_key())
    rejected(idp, idp.token("ES512"))


def test_an_unknown_kid_reloads_the_key_set_at_most_once_in_60_seconds() -> None:
    """Accept a token of a new key after one reload, and refuse a second reload (E6)."""
    idp = FakeIdp()
    clock = FakeClock()

    async def scenario(verifier: OidcVerifier) -> None:
        await verifier.verify(idp.token())
        clock.now += JWKS_RELOAD_MIN_SECONDS + 1
        idp.rotate()
        principal = await verifier.verify(idp.token(key=idp.next_key))
        assert principal.subject == "user-1"
        assert idp.requests[JWKS_PATH] == 2
        with pytest.raises(InvalidTokenError):
            await verifier.verify(idp.token(kid="rsa-3"))
        assert idp.requests[JWKS_PATH] == 2

    run_verifier(idp, scenario, clock=clock)


def test_a_token_with_no_kid_and_two_keys_is_rejected_with_no_reload(
    rejected: Rejected,
) -> None:
    """Reject a token with no kid at once, because a reload cannot help (E6a)."""
    idp = FakeIdp()
    rejected(idp, idp.token(kid=None))
    assert idp.requests[JWKS_PATH] == 1


@pytest.mark.parametrize(
    ("claims", "groups_claim", "groups"),
    [
        ({"groups": None}, "groups", frozenset()),
        ({"groups": "admins"}, "groups", frozenset()),
        ({"groups": ["admins", 7]}, "groups", frozenset()),
        ({"kamayoq_groups": ["readers"]}, "kamayoq_groups", frozenset({"readers"})),
    ],
)
def test_groups_are_empty_unless_the_claim_is_a_list_of_strings(
    claims: dict[str, Any], groups_claim: str, groups: frozenset[str]
) -> None:
    """Give no groups for a bad groups claim, and read a custom claim (E10)."""
    idp = FakeIdp()
    token = idp.token(**claims)
    assert verify_token(idp, token, groups_claim=groups_claim).groups == groups


def test_a_token_larger_than_16_kib_is_rejected_before_any_request(
    rejected: Rejected,
) -> None:
    """Reject a large token before a request to the IdP (E11)."""
    idp = FakeIdp()
    rejected(idp, "a" * (MAX_TOKEN_BYTES + 1))
    assert not idp.requests
