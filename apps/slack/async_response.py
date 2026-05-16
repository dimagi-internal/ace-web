"""Deferred slash-command responses via Slack's response_url.

Slack gives 3 seconds for the initial slash-command HTTP response, but
allows follow-up POSTs to a per-invocation `response_url` for up to 30
minutes. Use this for handlers whose work can blow past 3s (Drive
listing, snapshot loads on cold cache, etc.).

Pattern:
    def handle_thing(*, response_url, ...):
        if response_url:
            run_async(response_url, _do_work, ...)
            return ephemeral_ack("Working on it…")
        return _do_work(...)  # tests / no response_url

`_do_work` returns the same {response_type, text, blocks} dict the
synchronous path would. We POST it to response_url and ignore the
result (Slack returns 200 on success, but there's nothing to do on
failure beyond log).
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import httpx

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 10


def post_to_response_url(response_url: str, payload: dict) -> None:
    """Sync POST to Slack's response_url. Best-effort; logs on failure."""
    try:
        resp = httpx.post(response_url, json=payload, timeout=_HTTP_TIMEOUT_SECONDS)
        if resp.status_code >= 400:
            logger.warning(
                "slack response_url POST returned %s: %s",
                resp.status_code, resp.text[:200],
            )
    except Exception:
        logger.exception("slack response_url POST failed")


def run_async(response_url: str, fn: Callable[..., dict], *args, **kwargs) -> None:
    """Spawn a daemon thread that runs `fn(*args, **kwargs)` and POSTs
    the result to response_url. Returns immediately.

    The POSTed payload gets `replace_original: true` so the result
    replaces the synchronous "Loading…" ack rather than appending."""
    def _runner():
        try:
            payload = fn(*args, **kwargs)
        except Exception:
            logger.exception("async slack handler failed")
            payload = {
                "response_type": "ephemeral",
                "text": ":x: Something went wrong. Check ace-web logs.",
            }
        if payload is not None:
            payload.setdefault("replace_original", True)
            post_to_response_url(response_url, payload)

    threading.Thread(target=_runner, daemon=True).start()
