"""Slack signing-secret HMAC verification.

Slack signs every inbound request with v0=hmac_sha256(secret, "v0:" + ts + ":" + body).
The timestamp protects against replay (we reject anything more than 5 min old).
"""
from __future__ import annotations

import hashlib
import hmac
import time


class SignatureError(Exception):
    pass


_MAX_AGE_SECONDS = 5 * 60


def verify_slack_signature(*, secret: str, body: bytes,
                           timestamp: str, signature: str) -> None:
    if not secret:
        raise SignatureError("no signing secret configured")
    try:
        ts_int = int(timestamp)
    except (TypeError, ValueError):
        raise SignatureError("bad timestamp") from None
    if abs(time.time() - ts_int) > _MAX_AGE_SECONDS:
        raise SignatureError("stale timestamp")
    base = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        raise SignatureError("signature mismatch")
