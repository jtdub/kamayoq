"""Unit tests for the JSON log formatter."""

import json
import logging
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from kamayoq.log import JsonFormatter, configure_logging
from kamayoq.secrets import MASK, remember

SECRET_VALUE = "s3cr3t-Value-42"


@pytest.fixture
def restored_root_logger() -> Iterator[None]:
    """Put back the handlers and the level of the root logger after the test."""
    saved_handlers = logging.root.handlers[:]
    saved_level = logging.root.level
    yield
    for handler in logging.root.handlers:
        if handler not in saved_handlers:
            handler.close()
    logging.root.handlers[:] = saved_handlers
    logging.root.setLevel(saved_level)


class RecordCollector(logging.Handler):
    """Keep each record that reaches the handler, with no filter."""

    def __init__(self) -> None:
        """Start with no records."""
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Keep the record."""
        self.records.append(record)


def start_logging() -> RecordCollector:
    """Configure kamayoq logging, add an unfiltered root handler, and know a value."""
    configure_logging("INFO")
    collector = RecordCollector()
    logging.root.addHandler(collector)
    remember(SECRET_VALUE, "secret://test")
    return collector


def stderr_records(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    """Return each JSON line of stderr as a dict."""
    return [json.loads(line) for line in capsys.readouterr().err.splitlines()]


def make_record(**fields: Any) -> logging.LogRecord:
    """Return a log record of the logger kamayoq.test with the given fields."""
    return logging.makeLogRecord(
        {
            "name": "kamayoq.test",
            "levelname": "INFO",
            "msg": "ready in %d ms",
            "args": (12,),
            **fields,
        }
    )


def test_record_is_one_json_object_with_required_keys() -> None:
    """Write the time, level, logger, and message keys on one line."""
    line = JsonFormatter().format(make_record())
    fields = json.loads(line)
    assert "\n" not in line
    assert set(fields) == {"time", "level", "logger", "message"}
    assert fields["level"] == "INFO"
    assert fields["logger"] == "kamayoq.test"
    assert fields["message"] == "ready in 12 ms"


def test_exception_and_stack_are_included_in_json() -> None:
    """Add the traceback and the stack when the record has them."""
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = make_record(exc_info=sys.exc_info(), stack_info="Stack (most recent)")
    fields = json.loads(JsonFormatter().format(record))
    assert "RuntimeError: boom" in fields["exc_info"]
    assert fields["stack_info"] == "Stack (most recent)"


def test_time_is_utc_iso_8601_with_milliseconds() -> None:
    """Write the time of the record in UTC, to the millisecond."""
    created = datetime(2026, 11, 14, 4, 45, 25, 890123, tzinfo=UTC).timestamp()
    fields = json.loads(JsonFormatter().format(make_record(created=created)))
    assert fields["time"] == "2026-11-14T04:45:25.890+00:00"


@pytest.mark.usefixtures("restored_root_logger")
def test_configure_logging_sends_uvicorn_named_loggers_to_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Write the records of the uvicorn loggers to stderr as JSON."""
    configure_logging("INFO")
    logging.getLogger("uvicorn.error").info("Started server process [%d]", 42)
    logging.getLogger("uvicorn.access").info(
        '%s - "%s" %d', "127.0.0.1:53889", "GET /healthz HTTP/1.1", 200
    )
    logging.getLogger("uvicorn.access").debug("not at the INFO level")
    lines = capsys.readouterr().err.splitlines()
    records = [json.loads(line) for line in lines]
    assert [(r["logger"], r["level"], r["message"]) for r in records] == [
        ("uvicorn.error", "INFO", "Started server process [42]"),
        ("uvicorn.access", "INFO", '127.0.0.1:53889 - "GET /healthz HTTP/1.1" 200'),
    ]


@pytest.mark.usefixtures("restored_root_logger")
@pytest.mark.parametrize("logger_name", ["kamayoq.test", "uvicorn.error", "httpx"])
def test_known_value_is_masked_in_message_args_and_exception(
    logger_name: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Mask the value in each line of the kamayoq handler, for each logger."""
    collector = start_logging()
    logger = logging.getLogger(logger_name)
    logger.info(f"token {SECRET_VALUE} in the message")
    logger.info("token %s in the args", SECRET_VALUE)
    try:
        raise RuntimeError(f"refused {SECRET_VALUE}")
    except RuntimeError:
        logger.exception("call failed")
    err = capsys.readouterr().err
    assert SECRET_VALUE not in err
    records = [json.loads(line) for line in err.splitlines()]
    assert [r["message"] for r in records] == [
        f"token {MASK} in the message",
        f"token {MASK} in the args",
        "call failed",
    ]
    assert f"RuntimeError: refused {MASK}" in records[2]["exc_info"]
    raw = collector.records
    assert SECRET_VALUE in raw[0].getMessage()
    assert SECRET_VALUE in raw[1].getMessage()
    assert raw[2].exc_info is not None
    assert SECRET_VALUE in str(raw[2].exc_info[1])


@pytest.mark.usefixtures("restored_root_logger")
def test_known_value_is_masked_in_stack_info(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Mask the value in the stack text of a record."""
    collector = start_logging()
    record = logging.makeLogRecord(
        {
            "name": "kamayoq.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "x",
            "stack_info": f"Stack {SECRET_VALUE}",
        }
    )
    logging.getLogger().handle(record)
    [line] = stderr_records(capsys)
    assert line["stack_info"] == f"Stack {MASK}"
    assert collector.records[0].stack_info == f"Stack {SECRET_VALUE}"


@pytest.mark.usefixtures("restored_root_logger")
def test_cached_exception_text_is_masked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Mask the value in exc_text that another formatter cached."""
    collector = start_logging()
    record = logging.makeLogRecord(
        {
            "name": "kamayoq.test",
            "levelno": logging.ERROR,
            "levelname": "ERROR",
            "msg": "x",
            "exc_info": None,
            "exc_text": f"Traceback\nRuntimeError: {SECRET_VALUE}",
        }
    )
    logging.getLogger().handle(record)
    [line] = stderr_records(capsys)
    assert line["exc_info"] == f"Traceback\nRuntimeError: {MASK}"
    assert collector.records[0].exc_text == f"Traceback\nRuntimeError: {SECRET_VALUE}"


@pytest.mark.usefixtures("restored_root_logger")
def test_bad_args_do_not_raise_and_the_line_has_no_known_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Write the redacted message text when the args do not match it."""
    start_logging()
    logging.getLogger("kamayoq.test").info(f"{SECRET_VALUE} count %d", "x")
    err = capsys.readouterr().err
    assert SECRET_VALUE not in err
    assert "Logging error" not in err
    [line] = [json.loads(text) for text in err.splitlines()]
    assert line["message"] == f"{MASK} count %d"


@pytest.mark.usefixtures("restored_root_logger")
def test_filter_does_not_change_the_record_of_other_handlers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Give the next handler the original message, args, and exception."""
    collector = start_logging()
    try:
        raise RuntimeError(SECRET_VALUE)
    except RuntimeError:
        logging.getLogger("kamayoq.test").exception("value %s", SECRET_VALUE)
    assert MASK in capsys.readouterr().err
    [record] = collector.records
    assert record.msg == "value %s"
    assert record.args == (SECRET_VALUE,)
    assert record.exc_info is not None
    assert record.exc_text is None
