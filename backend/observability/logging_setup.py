"""Logging configuration: JSON logs + request-id correlation + optional Sentry."""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from contextvars import ContextVar

# Correlation id for the current request/job, injected into every log record.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Keys that must never appear in logs even if passed as `extra`.
_SECRET_KEYS = {
    "password", "password_hash", "token", "authorization", "secret",
    "jwt_secret", "aws_secret_access_key", "storage_s3_secret_key", "source_text",
}


def new_request_id() -> str:
    return uuid.uuid4().hex


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        # Attach safe extras (skip secrets and logging internals).
        for k, v in record.__dict__.items():
            if k in payload or k.startswith("_"):
                continue
            if k in logging.LogRecord("", 0, "", 0, "", (), None).__dict__:
                continue
            if k.lower() in _SECRET_KEYS:
                payload[k] = "***"
                continue
            if k in ("request_id",):
                continue
            try:
                json.dumps(v)
                payload[k] = v
            except (TypeError, ValueError):
                payload[k] = str(v)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    fmt = os.getenv("LOG_FORMAT", "json").lower()  # json | text

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    if fmt == "text":
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] [%(request_id)s] %(message)s"
        ))
    else:
        handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Quiet noisy libraries a notch.
    for noisy in ("werkzeug", "botocore", "urllib3"):
        logging.getLogger(noisy).setLevel(os.getenv("LOG_LEVEL_LIBS", "WARNING"))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def init_sentry() -> bool:
    """Initialize Sentry if SENTRY_DSN is set (MANGU baseline). Returns True if enabled."""
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logging.getLogger("observability").warning("SENTRY_DSN set but sentry-sdk not installed")
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", os.getenv("FLASK_ENV", "production")),
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
        send_default_pii=False,  # never ship user PII / manuscript content
    )
    return True
