"""JSON log lines for kamayoq and the libraries that it runs."""

import json
import logging
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
        return json.dumps(fields, default=str)
