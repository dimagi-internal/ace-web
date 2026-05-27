"""WebsocketCommunicator tests for OppConsumer decision edit/revert messages.

Verifies the multi-player decision editing flow:
  - decision.edit   -> broadcasts decision.edited to all connected clients
  - decision.revert -> broadcasts decision.reverted to all connected clients
  - unauthenticated connections are rejected with code 4001

Uses the same daphne-stub + session-cookie pattern as test_opp_consumer.py.
CHANNEL_LAYERS is already configured as InMemoryChannelLayer in test.py.
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

import pytest  # noqa: E402
from asgiref.sync import sync_to_async  # noqa: E402
from channels.routing import URLRouter  # noqa: E402
from channels.testing.websocket import WebsocketCommunicator  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth import SESSION_KEY  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402

from apps.common.channels_auth import AceSessionAuthMiddleware  # noqa: E402
from apps.opps.routing import websocket_urlpatterns  # noqa: E402

pytestmark = pytest.mark.django_db(transaction=True)

_OPP_PATH = "/ws/opps/malaria-pilot/runs/run-001/"
_OPP_PATH_NO_RUN = "/ws/opps/malaria-pilot/"


def _build_session_cookie(user):
    store = SessionStore()
    store[SESSION_KEY] = str(user.pk)
    store["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    store["_auth_user_hash"] = user.get_session_auth_hash()
    store.save()
    return store.session_key


def _app():
    return AceSessionAuthMiddleware(URLRouter(websocket_urlpatterns))


async def _connect(user, path: str):
    cookie_key = await sync_to_async(_build_session_cookie)(user)
    communicator = WebsocketCommunicator(
        _app(),
        path,
        headers=[
            (
                b"cookie",
                f"{settings.SESSION_COOKIE_NAME}={cookie_key}".encode(),
            )
        ],
    )
    connected, code = await communicator.connect()
    return communicator, connected, code


async def test_decision_edit_broadcasts_to_all_clients(django_user_model):
    """decision.edit from one client must be relayed to all connected clients."""
    alice = await sync_to_async(django_user_model.objects.create_user)(
        email="alice@dimagi.com", display_name="Alice"
    )
    bob = await sync_to_async(django_user_model.objects.create_user)(
        email="bob@dimagi.com", display_name="Bob"
    )

    comm_alice, connected_a, _ = await _connect(alice, _OPP_PATH)
    assert connected_a is True

    comm_bob, connected_b, _ = await _connect(bob, _OPP_PATH)
    assert connected_b is True

    # Alice sends a decision.edit
    await comm_alice.send_json_to({
        "type": "decision.edit",
        "row_id": "row-42",
        "new_answer": "Yes, confirmed",
    })

    # Both Alice and Bob should receive decision.edited
    msg_alice = await comm_alice.receive_json_from()
    msg_bob = await comm_bob.receive_json_from()

    for msg in (msg_alice, msg_bob):
        assert msg["event"] == "decision.edited"
        assert msg["data"]["row_id"] == "row-42"
        assert msg["data"]["new_answer"] == "Yes, confirmed"
        assert msg["data"]["editor_email"] == "alice@dimagi.com"
        assert msg["data"]["editor_name"] == "Alice"

    await comm_alice.disconnect()
    await comm_bob.disconnect()


async def test_decision_edit_persists_to_buffer(django_user_model):
    """decision.edit must write through to the decisions_buffer cache."""
    from apps.opps.decisions_buffer import get_edits

    alice = await sync_to_async(django_user_model.objects.create_user)(
        email="alice@dimagi.com", display_name="Alice"
    )
    comm, connected, _ = await _connect(alice, _OPP_PATH)
    assert connected is True

    await comm.send_json_to({
        "type": "decision.edit",
        "row_id": "row-7",
        "new_answer": "No",
    })
    # Consume the broadcast so the communicator buffer doesn't overflow
    await comm.receive_json_from()

    edits = await sync_to_async(get_edits)("malaria-pilot", "run-001")
    assert "row-7" in edits
    assert edits["row-7"]["new_answer"] == "No"
    assert edits["row-7"]["editor_email"] == "alice@dimagi.com"

    await comm.disconnect()


async def test_decision_edit_carries_override_reasoning(django_user_model):
    """The override_reasoning field flows from client → consumer →
    Redis buffer → broadcast back to all clients."""
    from apps.opps.decisions_buffer import get_edits

    alice = await sync_to_async(django_user_model.objects.create_user)(
        email="alice@dimagi.com", display_name="Alice"
    )
    bob = await sync_to_async(django_user_model.objects.create_user)(
        email="bob@dimagi.com", display_name="Bob"
    )

    comm_alice, connected_a, _ = await _connect(alice, _OPP_PATH)
    assert connected_a is True
    comm_bob, connected_b, _ = await _connect(bob, _OPP_PATH)
    assert connected_b is True

    await comm_alice.send_json_to({
        "type": "decision.edit",
        "row_id": "row-7",
        "new_answer": "No",
        "override_reasoning": "LLO told me in standup",
    })

    msg_alice = await comm_alice.receive_json_from()
    msg_bob = await comm_bob.receive_json_from()

    for msg in (msg_alice, msg_bob):
        assert msg["data"]["override_reasoning"] == "LLO told me in standup"

    edits = await sync_to_async(get_edits)("malaria-pilot", "run-001")
    assert edits["row-7"]["override_reasoning"] == "LLO told me in standup"

    await comm_alice.disconnect()
    await comm_bob.disconnect()


async def test_decision_edit_without_reasoning_defaults_to_empty(django_user_model):
    """Existing clients that don't send the field still work — buffer
    entry carries an empty string, broadcast carries an empty string."""
    from apps.opps.decisions_buffer import get_edits

    alice = await sync_to_async(django_user_model.objects.create_user)(
        email="alice@dimagi.com", display_name="Alice"
    )
    comm, connected, _ = await _connect(alice, _OPP_PATH)
    assert connected is True

    await comm.send_json_to({
        "type": "decision.edit",
        "row_id": "row-7",
        "new_answer": "No",
    })
    msg = await comm.receive_json_from()
    assert msg["data"]["override_reasoning"] == ""

    edits = await sync_to_async(get_edits)("malaria-pilot", "run-001")
    assert edits["row-7"]["override_reasoning"] == ""

    await comm.disconnect()


async def test_decision_revert_broadcasts_to_all_clients(django_user_model):
    """decision.revert from one client must be relayed to all connected clients."""
    alice = await sync_to_async(django_user_model.objects.create_user)(
        email="alice@dimagi.com", display_name="Alice"
    )
    bob = await sync_to_async(django_user_model.objects.create_user)(
        email="bob@dimagi.com", display_name="Bob"
    )

    comm_alice, connected_a, _ = await _connect(alice, _OPP_PATH)
    assert connected_a is True
    comm_bob, connected_b, _ = await _connect(bob, _OPP_PATH)
    assert connected_b is True

    # Alice reverts a decision
    await comm_alice.send_json_to({
        "type": "decision.revert",
        "row_id": "row-42",
    })

    msg_alice = await comm_alice.receive_json_from()
    msg_bob = await comm_bob.receive_json_from()

    for msg in (msg_alice, msg_bob):
        assert msg["event"] == "decision.reverted"
        assert msg["data"]["row_id"] == "row-42"
        assert msg["data"]["editor_email"] == "alice@dimagi.com"

    await comm_alice.disconnect()
    await comm_bob.disconnect()


async def test_decision_revert_removes_from_buffer(django_user_model):
    """decision.revert must remove the row from the decisions_buffer cache."""
    from apps.opps.decisions_buffer import get_edits, set_edit

    alice = await sync_to_async(django_user_model.objects.create_user)(
        email="alice@dimagi.com", display_name="Alice"
    )

    # Pre-seed the buffer
    await sync_to_async(set_edit)(
        "malaria-pilot", "run-001",
        row_id="row-9",
        new_answer="Maybe",
        editor_email="alice@dimagi.com",
        editor_name="Alice",
    )

    comm, connected, _ = await _connect(alice, _OPP_PATH)
    assert connected is True

    await comm.send_json_to({
        "type": "decision.revert",
        "row_id": "row-9",
    })
    await comm.receive_json_from()

    edits = await sync_to_async(get_edits)("malaria-pilot", "run-001")
    assert "row-9" not in edits

    await comm.disconnect()


async def test_decision_edit_missing_fields_is_ignored(django_user_model):
    """decision.edit with missing row_id or new_answer must not crash or broadcast."""
    alice = await sync_to_async(django_user_model.objects.create_user)(
        email="alice@dimagi.com", display_name="Alice"
    )
    comm, connected, _ = await _connect(alice, _OPP_PATH)
    assert connected is True

    # Missing new_answer — should be silently dropped
    await comm.send_json_to({
        "type": "decision.edit",
        "row_id": "row-1",
    })

    # No broadcast expected; communicator should have no pending message
    assert await comm.receive_nothing() is True

    await comm.disconnect()


async def test_unauthenticated_connection_rejected():
    """A WebSocket connection without a valid session must be closed with code 4001."""
    communicator = WebsocketCommunicator(_app(), _OPP_PATH)
    connected, code = await communicator.connect()
    assert connected is False
    assert code == 4001
