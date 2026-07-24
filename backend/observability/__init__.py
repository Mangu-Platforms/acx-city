"""Structured logging, request-correlation IDs, and optional Sentry.

- ``configure_logging()`` installs a JSON log formatter (or plain text in dev).
- A ``request_id`` contextvar is injected into every log record so logs from the
  API and worker can be correlated.
- Secrets are never logged, and manuscript text is never logged.
"""
from .logging_setup import (
    configure_logging,
    get_logger,
    request_id_var,
    new_request_id,
    init_sentry,
)

__all__ = [
    "configure_logging",
    "get_logger",
    "request_id_var",
    "new_request_id",
    "init_sentry",
]
