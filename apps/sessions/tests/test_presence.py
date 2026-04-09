"""Unit tests for the Redis-backed presence module. Uses fakeredis as a
drop-in for redis.asyncio.Redis."""
import time

import fakeredis.aioredis
import pytest
from asgiref.sync import sync_to_async

from apps.sessions import presence
from apps.sessions.models import Session, SessionParticipant

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
async def fake_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        "apps.common.redis_client.get_redis",
        lambda: _awaitable(client),
    )
    yield client
    await client.flushall()
    await client.aclose()


def _awaitable(value):
    async def _inner():
        return value
    return _inner()


@pytest.fixture
def session(django_user_model):
    user = django_user_model.objects.create_user(
        email="alice@dimagi.com", display_name="Alice"
    )
    session = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=session, user=user, role="owner")
    return session


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(
        email="bob@dimagi.com", display_name="Bob"
    )


async def test_touch_adds_user_to_hash(fake_redis, session):
    was_new = await presence.touch(session.slug, session.owner.id)
    assert was_new is True
    members = await fake_redis.hkeys(f"presence:{session.slug}")
    assert str(session.owner.id) in members


async def test_touch_repeat_returns_was_new_false(fake_redis, session):
    await presence.touch(session.slug, session.owner.id)
    was_new = await presence.touch(session.slug, session.owner.id)
    assert was_new is False


async def test_snapshot_returns_current_user_ids(fake_redis, session, other_user):
    await presence.touch(session.slug, session.owner.id)
    await presence.touch(session.slug, other_user.id)
    ids = await presence.snapshot(session.slug)
    assert set(ids) == {session.owner.id, other_user.id}


async def test_snapshot_drops_expired_entries(fake_redis, session):
    # Manually insert an expired field — simulate a crashed client whose
    # TTL has passed.
    await fake_redis.hset(
        f"presence:{session.slug}",
        str(session.owner.id),
        str(int(time.time()) - 10),
    )
    ids = await presence.snapshot(session.slug)
    assert ids == []
    remaining = await fake_redis.hkeys(f"presence:{session.slug}")
    assert remaining == []  # Lazy sweep removed it.


async def test_leave_removes_user(fake_redis, session):
    await presence.touch(session.slug, session.owner.id)
    await presence.leave(session.slug, session.owner.id)
    ids = await presence.snapshot(session.slug)
    assert ids == []


async def test_is_present_checks_both_existence_and_expiry(fake_redis, session):
    await presence.touch(session.slug, session.owner.id)
    assert await presence.is_present(session.slug, session.owner.id)
    await presence.leave(session.slug, session.owner.id)
    assert not await presence.is_present(session.slug, session.owner.id)


async def test_maybe_record_last_seen_debounces_writes(
    fake_redis, session, other_user
):
    await sync_to_async(SessionParticipant.objects.create)(
        session=session, user=other_user, role="editor"
    )
    wrote_first = await presence.maybe_record_last_seen(
        session.slug, other_user.id, session_pk=session.pk
    )
    wrote_second = await presence.maybe_record_last_seen(
        session.slug, other_user.id, session_pk=session.pk
    )
    assert wrote_first is True
    assert wrote_second is False
    row = await sync_to_async(SessionParticipant.objects.get)(
        session=session, user=other_user
    )
    assert row.last_seen_at is not None
