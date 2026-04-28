"""WebsocketCommunicator tests for SessionConsumer.

These tests set up:
- The in-memory channel layer (via config.settings.test).
- fakeredis patched into apps.common.redis_client.get_redis so presence
  and stop-event state is deterministic.
- A signed Django session cookie so the ASGI auth middleware resolves
  the user inside the handshake.

Note on the daphne stub below: `channels.testing.__init__` unconditionally
imports `channels.testing.live`, which imports `daphne.testing.DaphneProcess`.
We don't need the live-server test case — only `WebsocketCommunicator`, which
lives in `channels.testing.websocket` — and daphne is not a runtime dep
(uvicorn serves the ASGI app in prod). Stubbing a minimal `daphne.testing`
module lets us load the submodule without pulling daphne into the dev extras.
"""
import sys
import types as _types

if "daphne" not in sys.modules:
    _daphne = _types.ModuleType("daphne")
    _daphne_testing = _types.ModuleType("daphne.testing")
    _daphne_testing.DaphneProcess = object  # type: ignore[attr-defined]
    _daphne.testing = _daphne_testing  # type: ignore[attr-defined]
    sys.modules["daphne"] = _daphne
    sys.modules["daphne.testing"] = _daphne_testing

import asyncio  # noqa: E402
from unittest.mock import patch  # noqa: E402

import fakeredis.aioredis  # noqa: E402
import pytest  # noqa: E402
from channels.routing import URLRouter  # noqa: E402
from channels.testing.websocket import WebsocketCommunicator  # noqa: E402
from django.contrib.auth import SESSION_KEY  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402

from apps.common.channels_auth import AceSessionAuthMiddleware  # noqa: E402
from apps.common.chat_backend import StreamEvent  # noqa: E402
from apps.sessions.models import Session, SessionParticipant  # noqa: E402
from apps.sessions.routing import websocket_urlpatterns  # noqa: E402

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
async def fake_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    def _getter():
        async def _inner():
            return client

        return _inner()

    monkeypatch.setattr("apps.common.redis_client.get_redis", _getter)
    yield client
    await client.flushall()
    await client.aclose()


def _build_session_cookie(user):
    store = SessionStore()
    store[SESSION_KEY] = str(user.pk)
    store["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    store["_auth_user_hash"] = user.get_session_auth_hash()
    store.save()
    return store.session_key


def _app():
    return AceSessionAuthMiddleware(URLRouter(websocket_urlpatterns))


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        email="alice@dimagi.com", display_name="Alice"
    )


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(
        email="bob@dimagi.com", display_name="Bob"
    )


@pytest.fixture
def session(alice, bob):
    s = Session.objects.create(owner=alice, title="x")
    SessionParticipant.objects.create(session=s, user=alice, role="owner")
    SessionParticipant.objects.create(session=s, user=bob, role="editor")
    return s


async def _connect(user, slug):
    from asgiref.sync import sync_to_async
    from django.conf import settings

    cookie_key = await sync_to_async(_build_session_cookie)(user)
    communicator = WebsocketCommunicator(
        _app(),
        f"/ws/sessions/{slug}/",
        headers=[
            (
                b"cookie",
                f"{settings.SESSION_COOKIE_NAME}={cookie_key}".encode(),
            )
        ],
    )
    connected, _ = await communicator.connect()
    return communicator, connected


async def test_connect_rejects_anonymous(fake_redis, session):
    communicator = WebsocketCommunicator(
        _app(), f"/ws/sessions/{session.slug}/"
    )
    connected, code = await communicator.connect()
    # Consumer closes with 4001 BEFORE accepting — WebsocketCommunicator
    # surfaces a pre-accept close as (False, code). (A close after accept
    # would return (True, None) from connect() and the 4001 would come
    # through later as a websocket.close output.)
    assert connected is False
    assert code == 4001


async def test_connect_rejects_stranger_for_orphan_session(fake_redis, session, django_user_model):
    """For orphan sessions (workspace=NULL), only the owner or an
    explicit participant may connect. Strangers (any other authed user)
    get the handshake closed with 4003. See apps/sessions/consumers.py
    `_participant_role`."""
    from asgiref.sync import sync_to_async

    from apps.sessions.models import SessionParticipant

    stranger = await sync_to_async(django_user_model.objects.create_user)(
        email="stranger@dimagi.com", display_name="Stranger"
    )
    communicator, connected = await _connect(stranger, session.slug)
    assert connected is False
    # Stranger must NOT have been auto-promoted to a participant.
    has_row = await sync_to_async(
        lambda: SessionParticipant.objects.filter(
            session=session, user=stranger
        ).exists()
    )()
    assert has_row is False


async def test_connect_rejects_unknown_session(fake_redis, django_user_model):
    """A missing session slug still closes the socket."""
    from asgiref.sync import sync_to_async

    user = await sync_to_async(django_user_model.objects.create_user)(
        email="nobody@dimagi.com", display_name="Nobody"
    )
    communicator, connected = await _connect(user, "no-such-slug")
    assert connected is False


async def test_connect_rejects_non_member_for_workspace_session(
    fake_redis, django_user_model
):
    """Workspace-tied sessions reject connection attempts from users
    who are not members of the session's workspace, even if they're
    authenticated. Auto-join only fires for actual workspace members.
    See apps/sessions/consumers.py `_participant_role`."""
    from asgiref.sync import sync_to_async

    from apps.sessions.models import Session, SessionParticipant
    from apps.workspaces.models import Workspace, WorkspaceMembership

    bob = await sync_to_async(django_user_model.objects.create_user)(
        email="bob@example.com", display_name="Bob"
    )
    alice = await sync_to_async(django_user_model.objects.create_user)(
        email="alice@example.com", display_name="Alice"
    )
    ws_b = await sync_to_async(Workspace.objects.create)(
        slug="ws-b-only",
        display_name="Workspace B",
        drive_root_folder_id="folder-b-only",
        created_by=bob,
    )
    await sync_to_async(WorkspaceMembership.objects.create)(
        workspace=ws_b, user=bob, role="owner"
    )
    bob_session = await sync_to_async(Session.objects.create)(
        owner=bob, title="bob's ws-tied chat", workspace=ws_b
    )
    await sync_to_async(SessionParticipant.objects.create)(
        session=bob_session, user=bob, role="owner"
    )

    # Alice is authenticated but NOT a member of ws-b.
    communicator, connected = await _connect(alice, bob_session.slug)
    assert connected is False
    has_row = await sync_to_async(
        lambda: SessionParticipant.objects.filter(
            session=bob_session, user=alice
        ).exists()
    )()
    assert has_row is False


async def test_connect_sends_session_state(fake_redis, session, alice):
    communicator, connected = await _connect(alice, session.slug)
    assert connected is True
    frame = await communicator.receive_json_from()
    assert frame["event"] == "session.state"
    data = frame["data"]
    assert "messages" in data
    assert "active_draft" in data
    assert "participants" in data
    assert "presence_user_ids" in data
    assert alice.id in data["presence_user_ids"]
    assert data["current_user_id"] == alice.id
    await communicator.disconnect()


async def test_alice_draft_update_reaches_bob(fake_redis, session, alice, bob):
    ac, ac_ok = await _connect(alice, session.slug)
    bc, bc_ok = await _connect(bob, session.slug)
    assert ac_ok and bc_ok
    # Drain session.state frames.
    await ac.receive_json_from()
    await bc.receive_json_from()
    # NOTE: do NOT drain presence.joined frames with a short timeout —
    # asgiref.testing.ApplicationCommunicator.receive_output cancels the
    # application task on TimeoutError, which nukes the consumer. Instead
    # we consume frames in order below and skip non-draft frames.

    await ac.send_json_to({
        "action": "draft.update",
        "data": {"version": 0, "body": "Hello Bob"},
    })

    def _find_draft_updated(frames: list[dict]) -> dict | None:
        for f in frames:
            if f["event"] == "draft.updated":
                return f
        return None

    async def _collect_until_draft(sock, max_frames: int = 6) -> dict | None:
        received: list[dict] = []
        for _ in range(max_frames):
            frame = await sock.receive_json_from(timeout=1.0)
            received.append(frame)
            match = _find_draft_updated(received)
            if match is not None:
                return match
        return None

    ac_frame = await _collect_until_draft(ac)
    bc_frame = await _collect_until_draft(bc)
    assert ac_frame is not None
    assert ac_frame["event"] == "draft.updated"
    assert bc_frame is not None
    assert bc_frame["data"]["body"] == "Hello Bob"
    assert bc_frame["data"]["version"] == 1

    await ac.disconnect()
    await bc.disconnect()


# ────────────────────── Task 10 integration tests ──────────────────────


class _FakeBackend:
    """Scripted ChatBackend: yields a fixed sequence of events, then exhausts."""

    def __init__(self, events):
        self._events = events

    async def stream_completion(self, **kwargs):
        for e in self._events:
            yield e


async def _drain_until(communicator, event_name, timeout=2.0):
    """Receive frames until the named event arrives or ``timeout`` elapses.

    Unlike ``_collect_until_draft`` above (which is bounded by a max frame
    count so a short per-frame timeout can't nuke the consumer), this helper
    wraps a pure receive loop in ``asyncio.wait_for`` so we block until the
    expected frame shows up. Callers must be confident that the frame WILL
    arrive within ``timeout`` seconds — otherwise the TimeoutError fires and
    the test fails cleanly with a clear "expected event never arrived"
    signal. This is the right shape for tests that drive the turn driver:
    the expected frames arrive promptly when the happy path works, and the
    test should fail fast if it hangs.
    """

    async def _loop():
        while True:
            frame = await communicator.receive_json_from()
            if frame["event"] == event_name:
                return frame

    return await asyncio.wait_for(_loop(), timeout=timeout)


async def test_chat_send_broadcasts_stream_to_both_users(
    fake_redis, session, alice, bob
):
    events = [
        StreamEvent.delta(text="Hel"),
        StreamEvent.delta(text="lo"),
        StreamEvent.done(),
    ]

    ac, ac_ok = await _connect(alice, session.slug)
    bc, bc_ok = await _connect(bob, session.slug)
    assert ac_ok and bc_ok
    await ac.receive_json_from()  # drain session.state
    await bc.receive_json_from()  # drain session.state

    # Alice writes the draft, then sends.
    await ac.send_json_to({
        "action": "draft.update",
        "data": {"version": 0, "body": "hi"},
    })
    await _drain_until(ac, "draft.updated")
    await _drain_until(bc, "draft.updated")

    with patch(
        "apps.sessions.turn_driver._get_backend",
        return_value=_FakeBackend(events),
    ):
        await ac.send_json_to({"action": "chat.send", "data": {}})

        # Both users should see chat.stream_start → chat.delta × 2 → chat.stream_complete.
        # (draft.committed + the new empty draft.updated frames also go by first,
        # but _drain_until skips non-matching events.)
        for comm in (ac, bc):
            await _drain_until(comm, "chat.stream_start")
            delta1 = await _drain_until(comm, "chat.delta")
            assert delta1["data"]["text"] == "Hel"
            delta2 = await _drain_until(comm, "chat.delta")
            assert delta2["data"]["text"] == "lo"
            await _drain_until(comm, "chat.stream_complete")

    await ac.disconnect()
    await bc.disconnect()


async def test_chat_stop_from_bob_cancels_alice_stream(
    fake_redis, session, alice, bob
):
    class SlowBackend:
        async def stream_completion(self, **kwargs):
            yield StreamEvent.delta(text="partial ")
            await asyncio.sleep(60)
            yield StreamEvent.done()

    ac, ac_ok = await _connect(alice, session.slug)
    bc, bc_ok = await _connect(bob, session.slug)
    assert ac_ok and bc_ok
    await ac.receive_json_from()
    await bc.receive_json_from()

    await ac.send_json_to({
        "action": "draft.update",
        "data": {"version": 0, "body": "stop me"},
    })
    await _drain_until(ac, "draft.updated")
    await _drain_until(bc, "draft.updated")

    with patch(
        "apps.sessions.turn_driver._get_backend",
        return_value=SlowBackend(),
    ):
        await ac.send_json_to({"action": "chat.send", "data": {}})

        start_frame = await _drain_until(bc, "chat.stream_start")
        message_id = start_frame["data"]["message_id"]

        # Wait for Bob to see at least one delta before issuing stop.
        await _drain_until(bc, "chat.delta")

        await bc.send_json_to({
            "action": "chat.stop",
            "data": {"message_id": message_id},
        })

        # The stop path in drive_assistant_turn yields a single
        # StreamEvent.for_error(message="cancelled") after stop_event fires.
        # _run_turn_driver sees event.type == ERROR and broadcasts
        # chat.stream_error (NOT chat.stream_cancelled) — and RETURNS before
        # the stop_event.is_set() branch at the bottom of _run_turn_driver
        # is reached. So the observed event is chat.stream_error with
        # detail="cancelled". Both consumers in the session group receive it.
        err_ac = await _drain_until(ac, "chat.stream_error")
        err_bc = await _drain_until(bc, "chat.stream_error")
        assert err_ac["data"]["message_id"] == message_id
        assert err_ac["data"]["detail"] == "cancelled"
        assert err_bc["data"]["message_id"] == message_id
        assert err_bc["data"]["detail"] == "cancelled"

    await ac.disconnect()
    await bc.disconnect()


async def test_draft_take_over_fails_on_live_lock(fake_redis, session, alice, bob):
    ac, _ = await _connect(alice, session.slug)
    bc, _ = await _connect(bob, session.slug)
    await ac.receive_json_from()
    await bc.receive_json_from()

    await ac.send_json_to({
        "action": "draft.update",
        "data": {"version": 0, "body": "mine"},
    })
    await _drain_until(ac, "draft.updated")
    # Let Bob observe Alice's draft update too, so the take_over attempt
    # happens against a well-defined post-update state.
    await _drain_until(bc, "draft.updated")

    await bc.send_json_to({"action": "draft.take_over", "data": {}})
    frame = await _drain_until(bc, "session.error")
    assert frame["data"]["code"] == "draft_lock_held"

    await ac.disconnect()
    await bc.disconnect()
