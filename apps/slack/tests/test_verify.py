import hashlib
import hmac
import time

import pytest

from apps.slack.verify import SignatureError, verify_slack_signature

SECRET = "abc-test-secret"


def _sign(body: bytes, ts: str, secret: str = SECRET) -> str:
    base = b"v0:" + ts.encode() + b":" + body
    digest = hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return f"v0={digest}"


def test_verify_accepts_valid_signature():
    ts = str(int(time.time()))
    body = b"command=/ace&text=run+my-opp"
    sig = _sign(body, ts)
    verify_slack_signature(secret=SECRET, body=body, timestamp=ts, signature=sig)
    # No exception = pass.


def test_verify_rejects_bad_signature():
    ts = str(int(time.time()))
    body = b"command=/ace&text=run+my-opp"
    with pytest.raises(SignatureError, match="signature mismatch"):
        verify_slack_signature(secret=SECRET, body=body, timestamp=ts,
                               signature="v0=deadbeef")


def test_verify_rejects_stale_timestamp():
    ts = str(int(time.time()) - 60 * 10)  # 10 min old
    body = b"command=/ace"
    sig = _sign(body, ts)
    with pytest.raises(SignatureError, match="stale"):
        verify_slack_signature(secret=SECRET, body=body, timestamp=ts,
                               signature=sig)


def test_verify_rejects_missing_secret():
    with pytest.raises(SignatureError, match="no signing secret"):
        verify_slack_signature(secret="", body=b"x", timestamp="0", signature="v0=x")
