import json
import time

import fakeredis.aioredis
import pytest

from apps.presence import keys as presence_keys
from apps.presence import store as presence_store


@pytest.fixture
def fake_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get_redis():
        return client

    # Patch the MODULE attribute, not an imported function — presence_store
    # does `from apps.common import redis_client` precisely so this works.
    monkeypatch.setattr("apps.common.redis_client.get_redis", _get_redis)
    return client


def test_parse_page_key_splits_app_workspace_resource():
    assert presence_keys.parse_page_key("ace:dimagi-team:opp:bednet/run-001") == (
        "ace",
        "dimagi-team",
        "opp:bednet/run-001",
    )


def test_parse_page_key_rejects_malformed():
    assert presence_keys.parse_page_key("garbage") is None
    assert presence_keys.parse_page_key("") is None
    assert presence_keys.parse_page_key("ace:only-two") is None


def test_group_name_is_channels_safe():
    name = presence_keys.group_name("ace:ws:opp:a/run-001")
    assert name.startswith("presence.")
    assert len(name) <= 100
    assert all(c.isalnum() or c in "-._" for c in name)


def test_group_name_is_stable_and_distinct():
    assert presence_keys.group_name("ace:ws:a") == presence_keys.group_name("ace:ws:a")
    assert presence_keys.group_name("ace:ws:a") != presence_keys.group_name("ace:ws:b")


@pytest.mark.asyncio
async def test_touch_then_roster_returns_the_viewer(fake_redis):
    await presence_store.touch(
        "ace:ws:opp:a/run-001",
        user_id=7,
        connection_id="c1",
        name="Alice Chen",
        email="alice@x.com",
        sub_location="idea-to-pdd",
        idle=False,
    )
    assert await presence_store.roster("ace:ws:opp:a/run-001") == [
        {
            "user_id": 7,
            "email": "alice@x.com",
            "name": "Alice Chen",
            "sub_location": "idea-to-pdd",
            "idle": False,
        }
    ]


@pytest.mark.asyncio
async def test_two_tabs_same_user_appear_once(fake_redis):
    for conn in ("c1", "c2"):
        await presence_store.touch(
            "ace:ws:p", user_id=7, connection_id=conn, name="A", email="a@x.com",
            sub_location="", idle=False,
        )
    assert len(await presence_store.roster("ace:ws:p")) == 1


@pytest.mark.asyncio
async def test_closing_one_of_two_tabs_keeps_the_user_present(fake_redis):
    """The reason fields are per-connection: this must not evict the user."""
    for conn in ("c1", "c2"):
        await presence_store.touch(
            "ace:ws:p", user_id=7, connection_id=conn, name="A", email="a@x.com",
            sub_location="", idle=False,
        )
    await presence_store.forget("ace:ws:p", user_id=7, connection_id="c1")
    assert len(await presence_store.roster("ace:ws:p")) == 1


@pytest.mark.asyncio
async def test_forgetting_the_last_connection_empties_the_roster(fake_redis):
    await presence_store.touch(
        "ace:ws:p", user_id=7, connection_id="c1", name="A", email="a@x.com",
        sub_location="", idle=False,
    )
    await presence_store.forget("ace:ws:p", user_id=7, connection_id="c1")
    assert await presence_store.roster("ace:ws:p") == []


@pytest.mark.asyncio
async def test_expired_fields_are_swept_on_read(fake_redis):
    key = "presence:ace:ws:p"
    await fake_redis.hset(
        key,
        "9.dead",
        json.dumps({
            "exp": int(time.time()) - 5, "name": "Ghost", "email": "g@x.com",
            "loc": "", "idle": False,
        }),
    )
    assert await presence_store.roster("ace:ws:p") == []
    assert await fake_redis.hget(key, "9.dead") is None


@pytest.mark.asyncio
async def test_touch_sets_a_key_level_ttl(fake_redis):
    await presence_store.touch(
        "ace:ws:p", user_id=7, connection_id="c1", name="A", email="a@x.com",
        sub_location="", idle=False,
    )
    assert 0 < await fake_redis.ttl("presence:ace:ws:p") <= presence_store.KEY_TTL_SECONDS


@pytest.mark.asyncio
async def test_idle_flag_round_trips(fake_redis):
    await presence_store.touch(
        "ace:ws:p", user_id=7, connection_id="c1", name="A", email="a@x.com",
        sub_location="", idle=True,
    )
    assert (await presence_store.roster("ace:ws:p"))[0]["idle"] is True


@pytest.mark.asyncio
async def test_idle_merge_one_active_tab_means_present_idle_first(fake_redis):
    """One idle connection + one active connection for the SAME user: the user
    counts as present (idle=False) — one active tab is enough. Writes the idle
    connection FIRST so an implementation that just keeps the last-seen value
    (instead of ORing "not idle" across all of the user's connections) fails
    here even though it might pass the mirrored ordering below."""
    await presence_store.touch(
        "ace:ws:p", user_id=7, connection_id="c-idle", name="A", email="a@x.com",
        sub_location="", idle=True,
    )
    await presence_store.touch(
        "ace:ws:p", user_id=7, connection_id="c-active", name="A", email="a@x.com",
        sub_location="", idle=False,
    )
    entries = await presence_store.roster("ace:ws:p")
    assert len(entries) == 1
    assert entries[0]["idle"] is False


@pytest.mark.asyncio
async def test_idle_merge_one_active_tab_means_present_active_first(fake_redis):
    """Mirror of the above with the connections touched in the OPPOSITE order —
    active tab written FIRST, idle tab written SECOND. hgetall's field order is
    not guaranteed, and a last-seen-wins implementation would pass exactly one
    of these two orderings; both must pass for the merge to be order-independent."""
    await presence_store.touch(
        "ace:ws:p", user_id=7, connection_id="c-active", name="A", email="a@x.com",
        sub_location="", idle=False,
    )
    await presence_store.touch(
        "ace:ws:p", user_id=7, connection_id="c-idle", name="A", email="a@x.com",
        sub_location="", idle=True,
    )
    entries = await presence_store.roster("ace:ws:p")
    assert len(entries) == 1
    assert entries[0]["idle"] is False


@pytest.mark.asyncio
async def test_idle_merge_all_connections_idle_reports_idle(fake_redis):
    """Only when EVERY connection for the user is idle does the roster report
    the user as idle."""
    for conn in ("c1", "c2"):
        await presence_store.touch(
            "ace:ws:p", user_id=7, connection_id=conn, name="A", email="a@x.com",
            sub_location="", idle=True,
        )
    entries = await presence_store.roster("ace:ws:p")
    assert len(entries) == 1
    assert entries[0]["idle"] is True


@pytest.mark.asyncio
async def test_touch_is_a_noop_without_redis(monkeypatch):
    async def _no_redis():
        return None

    monkeypatch.setattr("apps.common.redis_client.get_redis", _no_redis)
    # Must not raise even though there is no client to write to.
    await presence_store.touch(
        "ace:ws:p", user_id=7, connection_id="c1", name="A", email="a@x.com",
        sub_location="", idle=False,
    )


@pytest.mark.asyncio
async def test_forget_is_a_noop_without_redis(monkeypatch):
    async def _no_redis():
        return None

    monkeypatch.setattr("apps.common.redis_client.get_redis", _no_redis)
    # Must not raise even though there is no client to delete from.
    await presence_store.forget("ace:ws:p", user_id=7, connection_id="c1")


@pytest.mark.asyncio
async def test_roster_is_empty_without_redis(monkeypatch):
    async def _no_redis():
        return None

    monkeypatch.setattr("apps.common.redis_client.get_redis", _no_redis)
    assert await presence_store.roster("ace:ws:p") == []
