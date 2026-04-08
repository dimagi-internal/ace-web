"""Tests for the CircuitBreaker utility."""
import time

import pytest

from apps.common.circuit_breaker import CircuitBreaker, CircuitOpenError


def test_starts_closed():
    cb = CircuitBreaker(threshold=3, cooldown_seconds=1)
    assert not cb.is_open()


def test_opens_after_threshold_failures():
    cb = CircuitBreaker(threshold=3, cooldown_seconds=10)
    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open()
    cb.record_failure()
    assert cb.is_open()


def test_success_resets_failures():
    cb = CircuitBreaker(threshold=3, cooldown_seconds=10)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open()


def test_check_raises_when_open():
    cb = CircuitBreaker(threshold=1, cooldown_seconds=10)
    cb.record_failure()
    with pytest.raises(CircuitOpenError):
        cb.check()


def test_half_opens_after_cooldown():
    cb = CircuitBreaker(threshold=1, cooldown_seconds=0.1)
    cb.record_failure()
    assert cb.is_open()
    time.sleep(0.15)
    # Cooldown elapsed — circuit allows next call
    assert not cb.is_open()
    cb.check()  # does not raise


def test_reopens_immediately_on_first_failure_after_cooldown():
    cb = CircuitBreaker(threshold=1, cooldown_seconds=0.1)
    cb.record_failure()
    time.sleep(0.15)
    cb.record_failure()
    assert cb.is_open()
