"""Structured logging with secret redaction.

Usage:  log = get_logger(__name__); log.info("vector.upsert", extra={"fields": {"n": 3}})
or      log_event(log, "vector.upsert", n=3)
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_SECRET_KEY_RE = re.compile(r"(api[_-]?key|secret|password|authorization|access[_-]?key)", re.I)
_SECRET_VALUE_RES = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),      # OpenAI
    re.compile(r"pcsk_[A-Za-z0-9_\-]{8,}"),    # Pinecone
    re.compile(r"AKIA[0-9A-Z]{16}"),           # AWS access key id
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
]
REDACTED = "***REDACTED***"


def redact(value: Any, key: str | None = None) -> Any:
    if key is not None and _SECRET_KEY_RE.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        for rx in _SECRET_VALUE_RES:
            value = rx.sub(REDACTED, value)
        return value
    if hasattr(value, "get_secret_value"):  # pydantic SecretStr
        return REDACTED
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": redact(record.getMessage()),
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        fields = getattr(record, "fields", None)
        if fields:
            payload.update(redact(fields))
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{record.levelname:<7} {record.name}: {redact(record.getMessage())}"
        fields = getattr(record, "fields", None)
        if fields:
            base += " " + " ".join(f"{k}={v}" for k, v in redact(fields).items())
        if record.exc_info:
            base += "\n" + redact(self.formatException(record.exc_info))
        return base


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if json_logs else PlainFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("botocore", "boto3", "urllib3", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any) -> None:
    logger.log(level, event, extra={"fields": fields})
