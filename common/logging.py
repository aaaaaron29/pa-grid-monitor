"""Structured JSON logs to stdout, read via `kubectl logs` — no Loki/log-aggregation stack
(Architecture.md Section 7: that's ~500MB to solve a problem this project doesn't have yet)."""
from __future__ import annotations

import json
import logging
import sys
import time

# Standard attributes every LogRecord carries — anything else on the record was passed
# via logger.info(..., extra={...}) and should ride along in the JSON output.
_STD_RECORD_KEYS = frozenset(logging.makeLogRecord({}).__dict__.keys())


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _STD_RECORD_KEYS and key not in payload:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
