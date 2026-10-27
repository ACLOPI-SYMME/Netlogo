"""JSON log lines (one object per line) carrying the session_id of the current context.

Used by the API process and by the worker processes. The session_id comes, in this order, from
the record (logger.info(..., extra={"session_id": ...})) or from the session_id_var context
variable, which the API sets per request (anyio's to_thread copies it into worker threads) and
the worker sets on setup.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

session_id_var: ContextVar[str | None] = ContextVar("aclopi_session_id", default=None)

# Optional attributes copied from the record when present (logger.info(..., extra={...})).
EXTRA_FIELDS = ("worker", "op", "method", "path", "status_code", "elapsed_ms", "client", "phase")


def _install_record_factory() -> None:
    """Capture session_id_var when a record is created: handlers may format it in another context.
    (Stored as ctx_session_id: extra={"session_id": ...} must still be allowed by makeRecord.)"""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_aclopi", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        record.ctx_session_id = session_id_var.get()
        return record

    factory._aclopi = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


_install_record_factory()


class JsonFormatter(logging.Formatter):
    def __init__(self, static: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.static = dict(static or {})

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "session_id": (getattr(record, "session_id", None) or getattr(record, "ctx_session_id", None)
                           or session_id_var.get()),
        }
        data.update(self.static)
        for key in EXTRA_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                data[key] = value
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


def configure(level: str | int = "INFO", static: dict[str, Any] | None = None) -> None:
    """Send every log record (including uvicorn's) to stderr as one JSON object per line."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter(static))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
