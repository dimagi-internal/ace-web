"""Tests for the public-endpoint rate limiter."""
from __future__ import annotations

from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory

from apps.common.rate_limit import allow, client_ip


def setup_function():
    cache.clear()


def test_allows_up_to_the_limit_then_refuses():
    assert [allow("b", limit=3, window_seconds=60) for _ in range(5)] == [
        True, True, True, False, False,
    ]


def test_buckets_are_independent():
    assert allow("a", limit=1, window_seconds=60) is True
    assert allow("a", limit=1, window_seconds=60) is False
    assert allow("b", limit=1, window_seconds=60) is True


def test_fails_open_when_the_cache_is_down():
    # A Redis blip must not lock a real reviewer out of commenting.
    with patch("apps.common.rate_limit.cache.add", side_effect=RuntimeError("boom")):
        assert allow("c", limit=1, window_seconds=60) is True


def test_client_ip_prefers_the_first_forwarded_entry():
    rf = RequestFactory()
    req = rf.post("/", HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.1", REMOTE_ADDR="10.0.0.1")
    assert client_ip(req) == "203.0.113.9"


def test_client_ip_falls_back_to_remote_addr():
    rf = RequestFactory()
    assert client_ip(rf.post("/", REMOTE_ADDR="10.0.0.7")) == "10.0.0.7"
    assert client_ip(rf.post("/")) in {"127.0.0.1", "unknown"}
