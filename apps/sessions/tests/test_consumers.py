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

import fakeredis.aioredis  # noqa: E402
import pytest  # noqa: E402
from channels.routing import URLRouter  # noqa: E402
from channels.testing.websocket import WebsocketCommunicator  # noqa: E402
from django.contrib.auth import SESSION_KEY  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402

from apps.common.channels_auth import AceSessionAuthMiddleware  # noqa: E402
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


async def test_connect_rejects_non_participant(fake_redis, session, django_user_model):
    from asgiref.sync import sync_to_async

    stranger = await sync_to_async(django_user_model.objects.create_user)(
        email="stranger@dimagi.com", display_name="Stranger"
    )
    communicator, connected = await _connect(stranger, session.slug)
    assert connected is False


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
