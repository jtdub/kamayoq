"""Unit tests for the known secret values and redact."""

import logging

import pytest

from kamayoq.api.app import create_app
from kamayoq.secrets import MASK, forget_all, redact, remember
from kamayoq.settings import Settings

FIXTURE_PROBE_VALUE = "value-of-the-earlier-test"


def test_redact_replaces_each_known_value_and_keeps_other_text() -> None:
    """Replace each known value with the mask, and keep the other text."""
    remember("token-1234", "secret://first")
    remember("hunter22", "secret://second")
    text = "a=token-1234 b=hunter22 c=token-1234 d=plain"
    assert redact(text) == f"a={MASK} b={MASK} c={MASK} d=plain"


def test_redact_with_no_known_value_returns_the_text() -> None:
    """Return the text unchanged when no value is known."""
    assert redact("nothing to hide") == "nothing to hide"


def test_redact_masks_a_value_that_contains_another_value_as_one_span() -> None:
    """Mask the longer value whole when a shorter value is part of it."""
    remember("abcd", "secret://short")
    remember("abcdef", "secret://long")
    assert redact("xabcdefx") == f"x{MASK}x"


def test_redact_masks_a_value_inside_another_value_as_one_span() -> None:
    """Mask the outer value whole when an inner value starts and ends inside it."""
    remember("abcdef", "secret://outer")
    remember("bcde", "secret://inner")
    assert redact("xabcdefx") == f"x{MASK}x"


def test_redact_merges_overlapping_values_into_one_mask() -> None:
    """Leave no part of two values that overlap in the text."""
    remember("abcd", "secret://left")
    remember("cdef", "secret://right")
    assert redact("abcdef") == MASK


def test_redact_merges_values_that_touch() -> None:
    """Replace two values that touch with one mask."""
    remember("abcd", "secret://left")
    remember("efgh", "secret://right")
    assert redact("-abcdefgh-") == f"-{MASK}-"


def test_redact_masks_overlapping_matches_of_one_value() -> None:
    """Mask each start of a value, also when two matches overlap."""
    remember("aaaa", "secret://repeat")
    assert redact("aaaaaa") == MASK


@pytest.mark.parametrize("value", ["abc", "    ", " \t\n "])
def test_remember_does_not_hide_a_short_or_blank_value_and_warns(
    value: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Keep a short or blank value out of the known values, and warn once."""
    caplog.set_level(logging.WARNING, logger="kamayoq.secrets")
    remember(value, "secret://tiny")
    assert redact(f"x{value}x") == f"x{value}x"
    warnings = [r for r in caplog.records if r.name == "kamayoq.secrets"]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING
    message = warnings[0].getMessage()
    assert message == (
        "secret://tiny is shorter than 4 characters or is only white space, "
        "so log lines do not hide it"
    )


def test_remember_warns_once_for_each_source_until_forget_all(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Warn once for each source, and warn again after forget_all."""
    caplog.set_level(logging.WARNING, logger="kamayoq.secrets")
    remember("abc", "secret://tiny")
    remember("abc", "secret://tiny")
    remember("abc", "secret://other")
    forget_all()
    remember("abc", "secret://tiny")
    assert [r.getMessage().split(" ")[0] for r in caplog.records] == [
        "secret://tiny",
        "secret://other",
        "secret://tiny",
    ]


def test_remember_hides_a_value_of_four_characters(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Make a value of 4 characters a known value, with no warning."""
    caplog.set_level(logging.WARNING, logger="kamayoq.secrets")
    remember("abcd", "secret://four")
    assert redact("abcd") == MASK
    assert caplog.records == []


def test_fixture_probe_remembers_a_value() -> None:
    """Remember a value that the next test must not see."""
    remember(FIXTURE_PROBE_VALUE, "secret://probe")
    assert redact(FIXTURE_PROBE_VALUE) == MASK


def test_fixture_forgets_the_value_of_the_earlier_test() -> None:
    """Start each test with no known values."""
    assert redact(FIXTURE_PROBE_VALUE) == FIXTURE_PROBE_VALUE


def test_create_app_hides_the_encoded_and_decoded_database_password() -> None:
    """Make both forms of the database password known values."""
    create_app(Settings(database_url="postgresql://k:p%40ss%2Fw@h:5/d"))
    assert redact("encoded p%40ss%2Fw") == f"encoded {MASK}"
    assert redact("decoded p@ss/w") == f"decoded {MASK}"


def test_create_app_with_no_database_password_adds_no_known_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Add nothing and warn about nothing when the URL has no password."""
    caplog.set_level(logging.WARNING, logger="kamayoq.secrets")
    url = "postgresql://k@h:5/d"
    create_app(Settings(database_url=url))
    assert redact(url) == url
    assert caplog.records == []


def test_create_app_warns_once_for_a_short_database_password(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Write one warning that names the database password and shows no value."""
    caplog.set_level(logging.WARNING, logger="kamayoq.secrets")
    create_app(Settings(database_url="postgresql://k:pw@h:5/d"))
    assert [r.getMessage() for r in caplog.records] == [
        "the database password is shorter than 4 characters or is only white space, "
        "so log lines do not hide it"
    ]
