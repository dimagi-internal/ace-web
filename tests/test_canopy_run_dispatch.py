"""apps.canopy.run_dispatch — enqueue a canopy Turn instead of spawning claude -p."""

from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.canopy import run_dispatch
from apps.sessions.models import Message, Session

User = get_user_model()
pytestmark = pytest.mark.django_db

ON = dict(
    CANOPY_BASE_URL="http://canopy.test",
    CANOPY_APP_CREDENTIAL="secret-cred",
    CANOPY_WORKSPACE="connect",
    CANOPY_AGENT_SLUG="ace",
    CANOPY_RUN_EXECUTION=True,
)


def _run(**kw):
    user = User.objects.create_user(email="runner@dimagi.com")
    session = Session.create_with_owner(
        owner=user, title="seeded-run: opp-a/run-1", backend_kind="cli",
        status="active", source="web", opp_slug="opp-a", opp_run_id="run-1", **kw,
    )
    Message.objects.create(
        session=session, turn_index=0, role="user", sender_user=user,
        content={"text": "/ace:run opp-a/run-1"}, plaintext="/ace:run opp-a/run-1",
        status="complete",
    )
    assistant = Message.objects.create(
        session=session, turn_index=1, role="assistant", content={"text": ""}, status="pending",
    )
    return session, assistant


def _patched(send_return=None):
    return (
        mock.patch("apps.canopy.client.exchange_token", return_value={"token": "usertok"}),
        mock.patch("apps.canopy.client.create_run_session", return_value={"id": "sess-9"}),
        mock.patch(
            "apps.canopy.client.send_message",
            return_value=send_return or {"turn_id": "turn-9", "message": {}},
        ),
        mock.patch("apps.canopy.client.stop_session", return_value={"cancelled": False}),
    )


def test_disabled_by_default_is_a_noop():
    session, assistant = _run()
    assert run_dispatch.enabled() is False
    assert run_dispatch.dispatch_turn(assistant.id) == ""
    session.refresh_from_db()
    assert session.canopy_session_id == ""


@override_settings(**ON)
def test_creates_one_session_per_opp_run_with_opp_metadata():
    session, assistant = _run()
    ex, create, send, stop = _patched()
    with ex, create as create_m, send, stop:
        run_dispatch.dispatch_turn(assistant.id)
    session.refresh_from_db()
    assert session.canopy_session_id == "sess-9"
    meta = create_m.call_args.kwargs["metadata"]
    assert meta["source"] == "ace-web"
    assert meta["opp_slug"] == "opp-a"
    assert meta["opp_run_id"] == "run-1"


@override_settings(**ON)
def test_reuses_the_existing_canopy_session_and_stops_its_stale_turn():
    session, assistant = _run(canopy_session_id="sess-existing")
    ex, create, send, stop = _patched()
    with ex, create as create_m, send as send_m, stop as stop_m:
        run_dispatch.dispatch_turn(assistant.id)
    create_m.assert_not_called()
    stop_m.assert_called_once()
    assert send_m.call_args.args[1] == "sess-existing"


@override_settings(**ON)
def test_records_the_turn_id_on_the_assistant_message():
    session, assistant = _run()
    ex, create, send, stop = _patched()
    with ex, create, send, stop:
        turn_id = run_dispatch.dispatch_turn(assistant.id)
    assistant.refresh_from_db()
    assert turn_id == "turn-9"
    assert assistant.canopy_turn_id == "turn-9"
    assert assistant.status == "pending"


@override_settings(**ON)
def test_sends_the_user_turns_text_not_an_empty_prompt():
    session, assistant = _run()
    ex, create, send, stop = _patched()
    with ex, create, send as send_m, stop:
        run_dispatch.dispatch_turn(assistant.id)
    assert send_m.call_args.kwargs["text"] == "/ace:run opp-a/run-1"
    assert send_m.call_args.kwargs["client_id"] == f"acerun:{assistant.id}"


@override_settings(**ON)
def test_dispatch_failure_marks_the_message_error_and_raises():
    from apps.canopy.client import CanopyError

    session, assistant = _run()
    with mock.patch("apps.canopy.client.exchange_token", side_effect=CanopyError(403, "nope")):
        with pytest.raises(run_dispatch.DispatchError):
            run_dispatch.dispatch_turn(assistant.id)
    assistant.refresh_from_db()
    assert assistant.status == "error"
    assert assistant.error_detail.startswith("canopy-dispatch:")


@override_settings(**ON)
def test_a_null_turn_id_from_canopy_is_a_dispatch_failure():
    session, assistant = _run()
    ex, create, send, stop = _patched(send_return={"turn_id": None, "message": {}})
    with ex, create, send, stop:
        with pytest.raises(run_dispatch.DispatchError):
            run_dispatch.dispatch_turn(assistant.id)
    assistant.refresh_from_db()
    assert assistant.status == "error"


def test_start_turn_spawns_the_subprocess_when_disabled():
    session, assistant = _run()
    with mock.patch("apps.sessions.turn_driver.start_turn_subprocess") as spawn:
        run_dispatch.start_turn(assistant.id)
    spawn.assert_called_once_with(assistant.id)


@override_settings(**ON)
def test_start_turn_dispatches_to_canopy_and_never_spawns_when_enabled():
    session, assistant = _run()
    ex, create, send, stop = _patched()
    with mock.patch("apps.sessions.turn_driver.start_turn_subprocess") as spawn:
        with ex, create, send, stop:
            run_dispatch.start_turn(assistant.id)
    spawn.assert_not_called()
    assistant.refresh_from_db()
    assert assistant.canopy_turn_id == "turn-9"


def test_start_turn_makes_no_outbound_canopy_call_when_disabled():
    """The flag-off path must be byte-for-byte the old behaviour: spawn, and
    touch canopy not at all. Any outbound call would blow up here."""
    session, assistant = _run()
    with mock.patch(
        "apps.canopy.client.urllib.request.urlopen",
        side_effect=AssertionError("canopy must not be called with the flag off"),
    ):
        with mock.patch("apps.sessions.turn_driver.start_turn_subprocess") as spawn:
            run_dispatch.start_turn(assistant.id)
    spawn.assert_called_once_with(assistant.id)
    session.refresh_from_db()
    assistant.refresh_from_db()
    assert session.canopy_session_id == ""
    assert assistant.canopy_turn_id == ""
    assert assistant.status == "pending"
