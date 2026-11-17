"""JSON log lines for kamayoq and the libraries that it runs."""

import copy
import json
import logging
import sys
from datetime import UTC, datetime

from kamayoq.secrets import redact


class JsonFormatter(logging.Formatter):
    """Format each log record as one JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        """Return the record as one line of JSON."""
        fields: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            fields["exc_info"] = self.formatException(record.exc_info)
        elif record.exc_text:
            fields["exc_info"] = record.exc_text
        if record.stack_info:
            fields["stack_info"] = self.formatStack(record.stack_info)
        return json.dumps(fields, default=str)


class SecretFilter(logging.Filter):
    """Replace each known secret value in a record with the mask."""

    def filter(self, record: logging.LogRecord) -> logging.LogRecord:
        """Return a copy of the record with the message, exception, and stack redacted.

        The copy has no args and no exc_info, so a formatter reads only the redacted
        text. The original record stays the same for the other handlers.
        """
        clean = copy.copy(record)
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        clean.msg = redact(message)
        clean.args = None
        if record.exc_info:
            exception_text = logging.Formatter().formatException(record.exc_info)
            clean.exc_text = redact(exception_text)
            clean.exc_info = None
        elif record.exc_text:
            clean.exc_text = redact(record.exc_text)
        if record.stack_info:
            clean.stack_info = redact(record.stack_info)
        return clean


def configure_logging(level: str) -> None:
    """Send each record to stderr as redacted JSON, and replace the root handlers."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(SecretFilter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
