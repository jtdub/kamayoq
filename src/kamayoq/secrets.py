"""Read secrets by name, and keep their values out of log lines."""

import logging
import threading

MASK = "**********"
MIN_REDACTED_LENGTH = 4

_logger = logging.getLogger(__name__)
_known_values: set[str] = set()
_known_values_lock = threading.Lock()


def remember(value: str, source: str) -> None:
    """Make the value a known value, so that redact hides it.

    A value shorter than MIN_REDACTED_LENGTH, or of white space only, is not added.
    kamayoq writes one WARNING line that names the source and shows no value.

    Args:
        value: The secret value.
        source: The text that names the value in the warning, for example
            ``secret://slack_token``.
    """
    if len(value) < MIN_REDACTED_LENGTH or value.isspace():
        _logger.warning(
            "%s is shorter than %d characters or is only white space, "
            "so log lines do not hide it",
            source,
            MIN_REDACTED_LENGTH,
        )
        return
    with _known_values_lock:
        _known_values.add(value)


def forget_all() -> None:
    """Remove all known values."""
    with _known_values_lock:
        _known_values.clear()


def _match_spans(text: str, value: str) -> list[tuple[int, int]]:
    """Return the start and end of each match of the value, overlaps included."""
    spans = []
    start = text.find(value)
    while start != -1:
        spans.append((start, start + len(value)))
        start = text.find(value, start + 1)
    return spans


def redact(text: str) -> str:
    """Return the text with each known value replaced by MASK.

    Matches that overlap or touch become one MASK, so no part of a value stays.
    """
    with _known_values_lock:
        values = tuple(_known_values)
    spans = sorted(span for value in values for span in _match_spans(text, value))
    if not spans:
        return text
    merged = [list(spans[0])]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    parts = []
    position = 0
    for start, end in merged:
        parts.append(text[position:start] + MASK)
        position = end
    parts.append(text[position:])
    return "".join(parts)
