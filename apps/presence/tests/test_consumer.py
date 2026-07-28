import sys
import types as _types

if "daphne" not in sys.modules:
    # ace-web does not depend on daphne (it runs uvicorn), but
    # channels.testing's package __init__ unconditionally imports
    # daphne.testing at import time. Stub it out — mirrors the pattern in
    # apps/opps/tests/test_opp_consumer.py.
    _daphne = _types.ModuleType("daphne")
    _daphne_testing = _types.ModuleType("daphne.testing")
    _daphne_testing.DaphneProcess = object  # type: ignore[attr-defined]
    _daphne.testing = _daphne_testing  # type: ignore[attr-defined]
    sys.modules["daphne"] = _daphne
    sys.modules["daphne.testing"] = _daphne_testing

import fakeredis.aioredis  # noqa: E402
import pytest  # noqa: E402
from asgiref.sync import sync_to_async  # noqa: E402
from channels.db import database_sync_to_async  # noqa: E402
from channels.testing.websocket import WebsocketCommunicator  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402

from apps.presence.consumers import PresenceConsumer  # noqa: E402

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get_redis():
        return client

    monkeypatch.setattr("apps.common.redis_client.get_redis", _get_redis)
    return client


@pytest.fixture
def member_user(db):
    """A user who is a member of the workspace slug 'test-ws'.

    ace-web's Workspace has `slug` as the primary key, requires a unique
    `drive_root_folder_id`, and a required `created_by` FK — unlike
    canopy-web's Workspace this is NOT a plain pk=/name= pair.
    """
    from apps.workspaces.models import Workspace, WorkspaceMembership

    user = get_user_model().objects.create_user(email="m@x.com", display_name="M")
    workspace = Workspace.objects.create(
        slug="test-ws",
        display_name="Test WS",
        drive_root_folder_id="folder-test-ws",
        created_by=user,
    )
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="editor")
    return user


@pytest.fixture
def second_member_user(member_user):
    """A second member of the SAME 'test-ws' workspace, for multi-viewer tests."""
    from apps.workspaces.models import Workspace, WorkspaceMembership

    workspace = Workspace.objects.get(slug="test-ws")
    user = get_user_model().objects.create_user(email="n@x.com", display_name="N")
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="editor")
    return user


@sync_to_async
def _acreate_pref(user):
    from apps.presence.models import PresencePreference

    PresencePreference.objects.create(user=user, show_presence=False)


async def _connect(user):
    communicator = WebsocketCommunicator(PresenceConsumer.as_asgi(), "/ws/presence/")
    communicator.scope["user"] = user
    connected, _ = await communicator.connect()
    return communicator, connected


@pytest.mark.asyncio
async def test_anonymous_is_rejected():
    from django.contrib.auth.models import AnonymousUser

    communicator = WebsocketCommunicator(PresenceConsumer.as_asgi(), "/ws/presence/")
    communicator.scope["user"] = AnonymousUser()
    connected, code = await communicator.connect()
    assert connected is False
    assert code == 4001
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_entering_a_page_broadcasts_a_roster_containing_you(member_user):
    communicator, connected = await _connect(member_user)
    assert connected
    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:opp:a/run-001",
        "sub_location": "run overview",
    })
    message = await communicator.receive_json_from(timeout=2)
    assert message["event"] == "presence.roster"
    assert message["data"]["page_key"] == "ace:test-ws:opp:a/run-001"
    assert [v["email"] for v in message["data"]["viewers"]] == [member_user.email]
    assert message["data"]["viewers"][0]["self"] is True
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_a_foreign_workspace_key_is_silently_rejected(member_user):
    """Membership is checked server-side — the page key is client-supplied.

    Silence alone would also pass an implementation that joined the group
    without ever writing/broadcasting — assert the group was never joined
    at all by checking nothing landed in Redis for that key either.
    """
    from apps.presence import store as presence_store

    communicator, _ = await _connect(member_user)
    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:someone-elses-workspace:opp:secret/run-001",
        "sub_location": "",
    })
    assert await communicator.receive_nothing(timeout=1)
    assert await presence_store.roster("ace:someone-elses-workspace:opp:secret/run-001") == []
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_a_malformed_page_key_is_silently_rejected(member_user):
    communicator, _ = await _connect(member_user)
    await communicator.send_json_to({
        "type": "presence.enter", "page_key": "junk", "sub_location": "",
    })
    assert await communicator.receive_nothing(timeout=1)
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_an_opted_out_user_receives_rosters_but_is_absent_from_them(member_user):
    from apps.presence.models import PresencePreference

    await _acreate_pref(member_user)
    communicator, _ = await _connect(member_user)
    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:activity",
        "sub_location": "Activity",
    })
    message = await communicator.receive_json_from(timeout=2)
    assert message["event"] == "presence.roster"
    assert message["data"]["viewers"] == []
    await communicator.disconnect()
    # This repo's convention (see test_chat_session_consumer.py) wraps sync
    # ORM calls in database_sync_to_async when made from inside an async
    # test — a running event loop trips Django's SynchronousOnlyOperation
    # guard on a bare `.exists()` call here.
    exists = await database_sync_to_async(
        PresencePreference.objects.filter(user=member_user).exists
    )()
    assert exists


@pytest.mark.asyncio
async def test_disconnect_removes_the_viewer(member_user, fake_redis):
    communicator, _ = await _connect(member_user)
    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:activity",
        "sub_location": "Activity",
    })
    await communicator.receive_json_from(timeout=2)
    await communicator.disconnect()

    from apps.presence import store as presence_store

    assert await presence_store.roster("ace:test-ws:activity") == []


@pytest.mark.asyncio
async def test_two_viewers_on_the_same_page_see_each_other_with_correct_self_flag(
    member_user, second_member_user
):
    comm1, connected1 = await _connect(member_user)
    comm2, connected2 = await _connect(second_member_user)
    assert connected1
    assert connected2

    await comm1.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:activity",
        "sub_location": "Activity",
    })
    await comm1.receive_json_from(timeout=2)  # solo roster, not under test here

    await comm2.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:activity",
        "sub_location": "Activity",
    })
    # comm2 joining broadcasts a fresh roster to the whole group — both
    # sockets get a message, each with its OWN "self" flag.
    msg1 = await comm1.receive_json_from(timeout=2)
    msg2 = await comm2.receive_json_from(timeout=2)

    for msg, viewing_as in [(msg1, member_user), (msg2, second_member_user)]:
        viewers = {v["email"]: v for v in msg["data"]["viewers"]}
        assert set(viewers) == {member_user.email, second_member_user.email}
        assert viewers[viewing_as.email]["self"] is True
        other = second_member_user if viewing_as is member_user else member_user
        assert viewers[other.email]["self"] is False

    await comm1.disconnect()
    await comm2.disconnect()


@pytest.mark.asyncio
async def test_opted_out_viewer_sees_others_but_others_do_not_see_them(
    member_user, second_member_user
):
    await _acreate_pref(member_user)  # member_user opts out; second_member_user stays visible

    comm1, _ = await _connect(member_user)
    comm2, _ = await _connect(second_member_user)

    await comm1.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:activity",
        "sub_location": "",
    })
    msg1_solo = await comm1.receive_json_from(timeout=2)
    assert msg1_solo["data"]["viewers"] == []  # opted-out, never written

    await comm2.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:activity",
        "sub_location": "",
    })
    msg1 = await comm1.receive_json_from(timeout=2)
    msg2 = await comm2.receive_json_from(timeout=2)

    # The opted-out viewer RECEIVES a roster containing the visible viewer...
    assert [v["email"] for v in msg1["data"]["viewers"]] == [second_member_user.email]
    # ...but the visible viewer's roster does NOT contain the opted-out one.
    assert [v["email"] for v in msg2["data"]["viewers"]] == [second_member_user.email]

    await comm1.disconnect()
    await comm2.disconnect()


@pytest.mark.asyncio
async def test_a_global_page_key_succeeds_with_no_workspace_memberships():
    user = await database_sync_to_async(get_user_model().objects.create_user)(
        email="g@x.com", display_name="G"
    )
    communicator, connected = await _connect(user)
    assert connected
    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:global:settings",
        "sub_location": "Settings",
    })
    message = await communicator.receive_json_from(timeout=2)
    assert message["event"] == "presence.roster"
    assert message["data"]["page_key"] == "ace:global:settings"
    assert [v["email"] for v in message["data"]["viewers"]] == [user.email]
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_navigating_to_a_new_page_removes_you_from_the_old_rosters(member_user):
    from apps.presence import store as presence_store

    communicator, connected = await _connect(member_user)
    assert connected

    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:opp:a",
        "sub_location": "Page A",
    })
    await communicator.receive_json_from(timeout=2)  # roster for page A

    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:opp:b",
        "sub_location": "Page B",
    })
    message = await communicator.receive_json_from(timeout=2)
    assert message["data"]["page_key"] == "ace:test-ws:opp:b"
    assert [v["email"] for v in message["data"]["viewers"]] == [member_user.email]

    assert await presence_store.roster("ace:test-ws:opp:a") == []
    assert len(await presence_store.roster("ace:test-ws:opp:b")) == 1

    await communicator.disconnect()


# -- Fix-round-2 regressions: each of these must fail if its corresponding
# fix is reverted. See canopy-web's task-7-report.md's "Fix round 2" section
# for the mutant-by-mutant verification that they actually do. --


@pytest.mark.asyncio
async def test_visibility_is_re_read_on_every_enter_not_cached_at_connect(member_user):
    """Regression for a connect-time `self.visible` snapshot: opting out
    mid-connection must stop future writes on the very next enter, not just
    at the next reconnect."""
    communicator, connected = await _connect(member_user)
    assert connected

    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:opp:a",
        "sub_location": "Page A",
    })
    msg_a = await communicator.receive_json_from(timeout=2)
    assert [v["email"] for v in msg_a["data"]["viewers"]] == [member_user.email]

    await _acreate_pref(member_user)  # opt out mid-connection, no reconnect

    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:opp:b",
        "sub_location": "Page B",
    })
    msg_b = await communicator.receive_json_from(timeout=2)
    assert msg_b["data"]["viewers"] == []

    await communicator.disconnect()


@pytest.mark.asyncio
async def test_membership_is_re_checked_on_every_enter_not_cached_at_connect(member_user):
    """Regression for a connect-time `self.workspaces` snapshot: a
    membership revoked mid-connection must reject the very next enter into
    that workspace, not just the next reconnect."""
    from apps.workspaces.models import WorkspaceMembership

    communicator, connected = await _connect(member_user)
    assert connected

    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:opp:a",
        "sub_location": "Page A",
    })
    await communicator.receive_json_from(timeout=2)  # still a member here

    await database_sync_to_async(
        WorkspaceMembership.objects.filter(workspace_id="test-ws", user=member_user).delete
    )()

    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:opp:b",
        "sub_location": "Page B",
    })
    assert await communicator.receive_nothing(timeout=1)

    from apps.presence import store as presence_store

    assert await presence_store.roster("ace:test-ws:opp:b") == []

    await communicator.disconnect()


@pytest.mark.asyncio
async def test_a_revoked_member_is_torn_down_from_their_old_page_too(member_user):
    """Regression for the teardown-on-reject fix: a rejected enter (here,
    lost membership) must leave the connection's PREVIOUS group as well —
    otherwise a revoked member keeps receiving that workspace's roster
    broadcasts until they disconnect or the Redis TTL expires."""
    from apps.workspaces.models import WorkspaceMembership

    communicator, connected = await _connect(member_user)
    assert connected

    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:opp:a",
        "sub_location": "Page A",
    })
    await communicator.receive_json_from(timeout=2)

    await database_sync_to_async(
        WorkspaceMembership.objects.filter(workspace_id="test-ws", user=member_user).delete
    )()

    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:opp:b",
        "sub_location": "Page B",
    })
    assert await communicator.receive_nothing(timeout=1)

    from apps.presence import store as presence_store

    assert await presence_store.roster("ace:test-ws:opp:a") == []

    await communicator.disconnect()


@pytest.mark.asyncio
async def test_whitespace_variant_keys_land_in_the_same_roster(member_user, second_member_user):
    """Regression for using the raw client string instead of the canonical
    (stripped) key: two connections entering the "same" page with different
    whitespace must join the SAME group/Redis key, not silently fragment
    the roster across two."""
    comm1, connected1 = await _connect(member_user)
    comm2, connected2 = await _connect(second_member_user)
    assert connected1
    assert connected2

    await comm1.send_json_to({
        "type": "presence.enter",
        "page_key": "ace: test-ws :activity",
        "sub_location": "",
    })
    msg1 = await comm1.receive_json_from(timeout=2)
    assert msg1["data"]["page_key"] == "ace:test-ws:activity"

    await comm2.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:activity",
        "sub_location": "",
    })
    # If the two connections joined different groups (raw string used as the
    # key), comm1 never gets notified of comm2's entry and this times out.
    msg1_updated = await comm1.receive_json_from(timeout=2)
    msg2 = await comm2.receive_json_from(timeout=2)

    expected = {member_user.email, second_member_user.email}
    assert {v["email"] for v in msg1_updated["data"]["viewers"]} == expected
    assert {v["email"] for v in msg2["data"]["viewers"]} == expected

    await comm1.disconnect()
    await comm2.disconnect()


@pytest.mark.asyncio
async def test_idle_state_does_not_leak_across_navigation(member_user):
    """Regression for not resetting self.idle / self._last_broadcast_idle on
    a page-key change: going idle on page A must not show as idle the
    instant the user arrives on page B."""
    communicator, connected = await _connect(member_user)
    assert connected

    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:opp:a",
        "sub_location": "Page A",
    })
    await communicator.receive_json_from(timeout=2)

    await communicator.send_json_to({"type": "presence.heartbeat", "idle": True})
    idle_msg = await communicator.receive_json_from(timeout=2)
    assert idle_msg["data"]["viewers"][0]["idle"] is True

    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "ace:test-ws:opp:b",
        "sub_location": "Page B",
    })
    msg_b = await communicator.receive_json_from(timeout=2)
    assert msg_b["data"]["viewers"][0]["idle"] is False

    await communicator.disconnect()
