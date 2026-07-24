"""Structured logging: JSON output, request-id correlation, secret redaction."""
import json
import logging

from observability.logging_setup import JsonFormatter, RequestIdFilter, request_id_var


def _format(record_kwargs, extra=None):
    formatter = JsonFormatter()
    rec = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg=record_kwargs.get("msg", "hi"), args=(), exc_info=None,
    )
    RequestIdFilter().filter(rec)
    for k, v in (extra or {}).items():
        setattr(rec, k, v)
    return json.loads(formatter.format(rec))


def test_request_id_in_output():
    request_id_var.set("req-xyz")
    out = _format({"msg": "hello"})
    assert out["request_id"] == "req-xyz"
    assert out["level"] == "INFO"
    assert out["msg"] == "hello"


def test_secrets_are_redacted():
    out = _format({"msg": "sensitive"}, extra={
        "password": "hunter2", "token": "abc", "source_text": "secret book",
        "organization_id": "o-1",
    })
    assert out["password"] == "***"
    assert out["token"] == "***"
    assert out["source_text"] == "***"
    # Non-secret extras pass through.
    assert out["organization_id"] == "o-1"


def test_output_is_valid_json():
    out = _format({"msg": "ok"}, extra={"job_id": "j-1"})
    assert out["job_id"] == "j-1"
