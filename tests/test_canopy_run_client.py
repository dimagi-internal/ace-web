"""apps.canopy.client — the run-execution calls (spec 2026-07-26)."""

import io
import json
from unittest import mock

import pytest
from django.test import override_settings

from apps.canopy import client

ENABLED = dict(
    CANOPY_BASE_URL="http://canopy.test",
    CANOPY_APP_CREDENTIAL="secret-cred",
    CANOPY_WORKSPACE="connect",
    CANOPY_AGENT_SLUG="ace",
)


class _Resp(io.BytesIO):
    """Minimal urlopen context-manager stand-in."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _urlopen(payload):
    return mock.patch(
        "apps.canopy.client.urllib.request.urlopen",
        return_value=_Resp(json.dumps(payload).encode()),
    )


@override_settings(**ENABLED)
def test_create_run_session_targets_the_workspace_route_and_agent():
    with _urlopen({"id": "sess-1"}) as opened:
        out = client.create_run_session(
            "usertok", title="seeded-run: o/r", metadata={"opp_slug": "o"},
        )
    assert out["id"] == "sess-1"
    req = opened.call_args.args[0]
    assert req.full_url == "http://canopy.test/api/w/connect/canopy-sessions/"
    body = json.loads(req.data)
    assert body["agent_slug"] == "ace"
    assert body["metadata"] == {"opp_slug": "o"}
    assert req.get_header("Authorization") == "Bearer usertok"


@override_settings(**ENABLED)
def test_send_message_posts_text_and_client_id_and_returns_turn_id():
    with _urlopen({"turn_id": "turn-1", "message": {"id": 7}}) as opened:
        out = client.send_message("usertok", "sess-1", text="/ace:run o/r", client_id="k1")
    assert out["turn_id"] == "turn-1"
    req = opened.call_args.args[0]
    assert req.full_url == "http://canopy.test/api/canopy-sessions/sess-1/send"
    assert json.loads(req.data) == {"text": "/ace:run o/r", "client_id": "k1"}


@override_settings(**ENABLED)
def test_get_turn_is_a_GET_with_the_bearer():
    with _urlopen({"id": "turn-1", "status": "queued"}) as opened:
        out = client.get_turn("usertok", "turn-1")
    assert out["status"] == "queued"
    req = opened.call_args.args[0]
    assert req.get_method() == "GET"
    assert req.full_url == "http://canopy.test/api/harness/turns/turn-1"


@override_settings(**ENABLED)
def test_list_unclaimable_returns_the_rows_verbatim():
    rows = [{"turn_id": "turn-1", "kind": "config", "reason": "no runner ...",
             "target": "session", "prompt": "", "created_at": "2026-07-26T00:00:00Z"}]
    with _urlopen(rows) as opened:
        out = client.list_unclaimable("usertok")
    assert out == rows
    assert opened.call_args.args[0].full_url == "http://canopy.test/api/harness/turns/unclaimable"


@override_settings(**ENABLED)
def test_http_error_becomes_canopy_error():
    import urllib.error

    err = urllib.error.HTTPError("u", 403, "forbidden", {}, io.BytesIO(b"nope"))
    with mock.patch("apps.canopy.client.urllib.request.urlopen", side_effect=err):
        with pytest.raises(client.CanopyError) as exc:
            client.get_turn("usertok", "turn-1")
    assert exc.value.status == 403
