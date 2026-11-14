"""JSON log lines for kamayoq and the libraries that it runs."""

import json
import logging
import sys
from datetime import UTC, datetime


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
        if record.stack_info:
            fields["stack_info"] = self.formatStack(record.stack_info)
        return json.dumps(fields, default=str)


def configure_logging(level: str) -> None:
    """Send each log record to stderr as JSON, and replace the root handlers."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
