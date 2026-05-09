"""Tests for the Redis singleton lock.

Backed by fakeredis (see conftest.py). Verifies SET-NX-EX semantics, CAS
release, owner reporting on contention, and TTL behavior.
"""
from __future__ import annotations

import pytest

from apps.mobile import singleton


def test_acquire_returns_true_on_first_caller(fake_redis):
    acquired, owner = singleton.try_acquire("alice:req-1")
    assert acquired is True
    assert owner == "alice:req-1"
    assert fake_redis.get(singleton.LOCK_KEY) == "alice:req-1"


def test_acquire_sets_ttl(fake_redis):
    singleton.try_acquire("alice:req-1", ttl_seconds=120)
    ttl = fake_redis.ttl(singleton.LOCK_KEY)
    # Allow a small window for clock drift; TTL should be ~120s and never -1.
    assert 0 < ttl <= 120


def test_second_acquire_returns_owner_string(fake_redis):
    singleton.try_acquire("alice:req-1")
    acquired, owner = singleton.try_acquire("bob:req-2")
    assert acquired is False
    assert owner == "alice:req-1"


def test_release_only_clears_own_key(fake_redis):
    singleton.try_acquire("alice:req-1")
    # Bob tries to release Alice's lock.
    released = singleton.release("bob:req-2")
    assert released is False
    assert fake_redis.get(singleton.LOCK_KEY) == "alice:req-1"


def test_release_clears_when_owner_matches(fake_redis):
    singleton.try_acquire("alice:req-1")
    released = singleton.release("alice:req-1")
    assert released is True
    assert fake_redis.get(singleton.LOCK_KEY) is None


def test_release_after_clear_is_noop(fake_redis):
    # Caller never acquired; release should be False, not raise.
    released = singleton.release("nobody")
    assert released is False


def test_make_owner_includes_both_segments():
    owner = singleton.make_owner(task_id="task-abc", request_uuid="req-123")
    assert owner == "task-abc:req-123"


def test_make_owner_generates_random_when_unspecified():
    a = singleton.make_owner()
    b = singleton.make_owner()
    assert a != b
    assert ":" in a


def test_current_owner_returns_empty_when_unlocked(fake_redis):
    assert singleton.current_owner() == ""


def test_current_owner_returns_value_when_locked(fake_redis):
    singleton.try_acquire("alice:req-1")
    assert singleton.current_owner() == "alice:req-1"


@pytest.mark.parametrize("ttl", [60, 600, 1800])
def test_ttl_seconds_helper_reports_remaining(fake_redis, ttl):
    singleton.try_acquire("alice:req-1", ttl_seconds=ttl)
    remaining = singleton.ttl_seconds()
    assert 0 < remaining <= ttl
