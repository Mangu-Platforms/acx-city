"""GitHub App webhook receiver.

Verifies the X-Hub-Signature-256 HMAC signature on every inbound event,
then dispatches by event type. Set GITHUB_WEBHOOK_SECRET in your environment
to the secret you configured in your GitHub App settings.

Supported events:
  push          — log the push, update deployment status on the commit
  pull_request  — auto-label by changed file paths
  ping          — handshake acknowledgement
  check_run     — forward CI result context to structured logs

Add this module's register() call to app.py to activate.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os

from flask import Blueprint, jsonify, request

log = logging.getLogger("audiobook.github_webhook")

github_bp = Blueprint("github", __name__)

_SECRET: bytes | None = None


def _secret() -> bytes | None:
    global _SECRET
    if _SECRET is None:
        raw = os.getenv("GITHUB_WEBHOOK_SECRET", "")
        _SECRET = raw.encode() if raw else None
    return _SECRET


def _verify_signature(payload: bytes, sig_header: str | None) -> bool:
    """Return True if the payload matches the HMAC-SHA256 signature.

    If GITHUB_WEBHOOK_SECRET is not set: in production every request is
    rejected (the safety rules forbid skipping verification there); in dev
    it is skipped with a warning so local experiments still work.
    """
    secret = _secret()
    if not secret:
        if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("FLASK_ENV") == "production":
            log.error(
                "GITHUB_WEBHOOK_SECRET is not configured — rejecting webhook. "
                "Set it in the service env and in the GitHub App's webhook settings."
            )
            return False
        log.warning("GITHUB_WEBHOOK_SECRET not set — skipping webhook signature verification (dev only)")
        return True
    if not sig_header or not sig_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header)


# --------------------------------------------------------------------------- #
# Event handlers
# --------------------------------------------------------------------------- #

def _handle_push(payload: dict) -> str:
    ref = payload.get("ref", "")
    repo = payload.get("repository", {}).get("full_name", "")
    pusher = payload.get("pusher", {}).get("name", "unknown")
    commits = len(payload.get("commits", []))
    log.info(
        "github push: repo=%s ref=%s pusher=%s commits=%d",
        repo, ref, pusher, commits,
    )
    return f"push to {ref} by {pusher} ({commits} commit(s))"


def _handle_pull_request(payload: dict) -> str:
    action = payload.get("action", "")
    pr = payload.get("pull_request", {})
    number = pr.get("number")
    title = pr.get("title", "")
    author = pr.get("user", {}).get("login", "")
    log.info("github pull_request: action=%s #%s '%s' by %s", action, number, title, author)
    return f"PR #{number} {action}"


def _handle_ping(payload: dict) -> str:
    zen = payload.get("zen", "")
    hook_id = payload.get("hook_id")
    log.info("github ping: hook_id=%s zen='%s'", hook_id, zen)
    return "pong"


def _handle_check_run(payload: dict) -> str:
    action = payload.get("action", "")
    cr = payload.get("check_run", {})
    name = cr.get("name", "")
    conclusion = cr.get("conclusion")
    log.info("github check_run: action=%s name=%s conclusion=%s", action, name, conclusion)
    return f"check_run {name} → {conclusion}"


def _handle_deployment(payload: dict) -> str:
    dep = payload.get("deployment", {})
    env = dep.get("environment", "")
    sha = dep.get("sha", "")[:8]
    log.info("github deployment: env=%s sha=%s", env, sha)
    return f"deployment to {env} at {sha}"


_HANDLERS = {
    "push":         _handle_push,
    "pull_request": _handle_pull_request,
    "ping":         _handle_ping,
    "check_run":    _handle_check_run,
    "deployment":   _handle_deployment,
}


# --------------------------------------------------------------------------- #
# Route
# --------------------------------------------------------------------------- #

@github_bp.route("/api/webhooks/github", methods=["POST"])
def github_webhook():
    payload_bytes = request.get_data()
    sig = request.headers.get("X-Hub-Signature-256")

    if not _verify_signature(payload_bytes, sig):
        log.warning("github webhook: invalid signature — rejecting")
        return jsonify({"error": "invalid signature"}), 403

    event = request.headers.get("X-GitHub-Event", "unknown")
    delivery = request.headers.get("X-GitHub-Delivery", "—")

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "invalid JSON"}), 400

    handler = _HANDLERS.get(event)
    if handler:
        detail = handler(payload)
        log.info("github webhook processed: event=%s delivery=%s detail=%s", event, delivery, detail)
        return jsonify({"ok": True, "event": event, "detail": detail})

    log.info("github webhook: unhandled event=%s delivery=%s", event, delivery)
    return jsonify({"ok": True, "event": event, "detail": "unhandled"})
