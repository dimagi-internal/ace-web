"""WebsocketCommunicator tests for OppConsumer.

Mirrors the daphne-stub + fixture patterns used in
``apps/sessions/tests/test_consumers.py`` so that we can exercise the
full ASGI stack (URL router + auth middleware) against an in-memory
channel layer.
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
from channels.layers import get_channel_layer  # noqa: E402
from channels.routing import URLRouter  # noqa: E402
from channels.testing.websocket import WebsocketCommunicator  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth import SESSION_KEY  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402

from apps.common.channels_auth import AceSessionAuthMiddleware  # noqa: E402
from apps.opps.routing import websocket_urlpatterns  # noqa: E402

pytestmark = pytest.mark.django_db(transaction=True)


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


async def test_consumer_relays_opp_updated(django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(
        email="a@dimagi.com", display_name="A"
    )
    communicator, connected, _ = await _connect(
        user, "/ws/opps/malaria-pilot/runs/run-001/"
    )
    assert connected is True

    layer = get_channel_layer()
    await layer.group_send(
        "opp.malaria-pilot.run-001",
        {
            "type": "opp.updated",
            "opp_slug": "malaria-pilot",
            "run_id": "run-001",
        },
    )

    msg = await communicator.receive_json_from()
    assert msg["event"] == "opp.updated"
    assert msg["data"]["slug"] == "malaria-pilot"
    assert msg["data"]["run_id"] == "run-001"

    await communicator.disconnect()


async def test_consumer_no_run_id_uses_default_group(django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(
        email="b@dimagi.com", display_name="B"
    )
    communicator, connected, _ = await _connect(user, "/ws/opps/malaria-pilot/")
    assert connected is True

    layer = get_channel_layer()
    await layer.group_send(
        "opp.malaria-pilot.default",
        {
            "type": "opp.updated",
            "opp_slug": "malaria-pilot",
            "run_id": "",
        },
    )

    msg = await communicator.receive_json_from()
    assert msg["event"] == "opp.updated"
    assert msg["data"]["slug"] == "malaria-pilot"
    assert msg["data"]["run_id"] == ""

    await communicator.disconnect()


async def test_consumer_rejects_unauthenticated():
    communicator = WebsocketCommunicator(_app(), "/ws/opps/malaria-pilot/")
    connected, code = await communicator.connect()
    # Pre-accept close surfaces as (False, code).
    assert connected is False
    assert code == 4001
