"""Unit tests for the OIDC discovery and key cache."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import pytest
from fake_idp import DISCOVERY_PATH, FAKE_ISSUER, JWKS_PATH, FakeIdp
from joserfc.jwk import KeySet

from kamayoq.oidc import (
    FAILURE_BACKOFF_SECONDS,
    JWKS_MAX_AGE_SECONDS,
    JWKS_RELOAD_MIN_SECONDS,
    JWKS_STALE_LIMIT_SECONDS,
    IdentityProviderError,
    OidcKeys,
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
    """Refuse a reload within 60 s of the last load, and load after 61 s."""
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

    run_with_keys(idp, clock, scenario)
    assert results == [False, True, False]
    assert idp.requests == {DISCOVERY_PATH: 2, JWKS_PATH: 2}


def test_reload_gives_one_load_for_two_calls_at_the_same_time() -> None:
    """Load once when two reload calls wait on the same lock."""
    idp = FakeIdp()
    clock = FakeClock()

    async def scenario(keys: OidcKeys) -> list[bool]:
        await keys.key_set()
        clock.now += JWKS_RELOAD_MIN_SECONDS + 1
        return list(await asyncio.gather(keys.reload(), keys.reload()))

    results = run_with_keys(idp, clock, scenario)
    assert sorted(results) == [False, True]
    assert idp.requests[JWKS_PATH] == 2


def test_discovery_issuer_with_a_trailing_slash_is_an_error_with_one_error_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reject a discovery issuer that differs, and log both values one time."""
    idp = FakeIdp()
    idp.discovery_overrides["issuer"] = FAKE_ISSUER + "/"
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


@pytest.mark.parametrize(
    ("path", "change"),
    [
        (DISCOVERY_PATH, "status"),
        (JWKS_PATH, "status"),
        (DISCOVERY_PATH, "timeout"),
        (JWKS_PATH, "timeout"),
        (DISCOVERY_PATH, "not json"),
        (JWKS_PATH, "not json"),
        (DISCOVERY_PATH, "not an object"),
        (JWKS_PATH, "keys is a string"),
        (JWKS_PATH, "keys has a string"),
        (JWKS_PATH, "unknown key type"),
        (JWKS_PATH, "no key type"),
        (JWKS_PATH, "empty key set"),
        (DISCOVERY_PATH, "http jwks_uri"),
        (DISCOVERY_PATH, "no jwks_uri"),
    ],
)
def test_a_bad_answer_of_the_idp_is_an_error_with_no_response_body(
    path: str, change: str
) -> None:
    """Raise IdentityProviderError with no response body for each bad answer."""
    idp = FakeIdp()
    bodies: dict[str, object] = {
        "status": {"error": SECRET_BODY_TEXT},
        "not json": SECRET_BODY_TEXT.encode(),
        "not an object": [SECRET_BODY_TEXT],
        "keys is a string": {"keys": SECRET_BODY_TEXT},
        "keys has a string": {"keys": [SECRET_BODY_TEXT]},
        "unknown key type": {"keys": [{"kty": "nope", "x": SECRET_BODY_TEXT}]},
        "no key type": {"keys": [{"x": SECRET_BODY_TEXT}]},
        "empty key set": {"keys": []},
    }
    if change == "status":
        idp.status[path] = 500
    if change == "timeout":
        idp.timeouts.add(path)
    if change in bodies:
        idp.bodies[path] = bodies[change]
    if change == "http jwks_uri":
        idp.discovery_overrides["jwks_uri"] = "http://idp.example.com" + JWKS_PATH
    if change == "no jwks_uri":
        idp.discovery_overrides["jwks_uri"] = None

    async def scenario(keys: OidcKeys) -> IdentityProviderError:
        with pytest.raises(IdentityProviderError) as caught:
            await keys.key_set()
        return caught.value

    error = run_with_keys(idp, FakeClock(), scenario)
    assert SECRET_BODY_TEXT not in str(error)


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
