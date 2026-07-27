"""apps.canopy.run_state — a canopy Turn's status as an ACE run state."""

from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.canopy import run_state
from apps.sessions.models import Message, Session

User = get_user_model()
pytestmark = pytest.mark.django_db

ON = dict(
    CANOPY_BASE_URL="http://canopy.test", CANOPY_APP_CREDENTIAL="c",
    CANOPY_WORKSPACE="connect", CANOPY_AGENT_SLUG="ace", CANOPY_RUN_EXECUTION=True,
)

_EMAIL_SEQ = iter(range(1, 10_000))


def _session_with_turn(turn_id="turn-1"):
    user = User.objects.create_user(email=f"o{next(_EMAIL_SEQ)}@dimagi.com")
    s = Session.create_with_owner(
        owner=user, title="t", opp_slug="o", opp_run_id="r",
        canopy_session_id="sess-1" if turn_id else "",
    )
    Message.objects.create(
        session=s, turn_index=0, role="assistant", content={"text": ""},
        status="pending", canopy_turn_id=turn_id,
    )
    return s


def _canopy(turn=None, unclaimable=()):
    return (
        mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}),
        mock.patch("apps.canopy.client.get_turn", return_value=turn or {"status": "queued"}),
        mock.patch("apps.canopy.client.list_unclaimable", return_value=list(unclaimable)),
    )


@override_settings(**ON)
def test_no_turn_id_is_not_dispatched():
    s = _session_with_turn(turn_id="")
    assert run_state.execution_state(s)["state"] == "not_dispatched"


@override_settings(**ON)
def test_queued_and_not_yet_unclaimable_is_queued():
    s = _session_with_turn()
    ex, get, unc = _canopy(turn={"status": "queued"})
    with ex, get, unc:
        assert run_state.execution_state(s)["state"] == "queued"


@override_settings(**ON)
def test_unclaimable_config_is_no_runner_configured_with_canopys_reason():
    s = _session_with_turn()
    rows = [{"turn_id": "turn-1", "kind": "config", "reason": "no runner can take this session"}]
    ex, get, unc = _canopy(turn={"status": "queued"}, unclaimable=rows)
    with ex, get, unc:
        out = run_state.execution_state(s)
    assert out["state"] == "no_runner_configured"
    assert out["detail"] == "no runner can take this session"


@override_settings(**ON)
def test_unclaimable_offline_is_waiting_for_runner():
    s = _session_with_turn()
    rows = [{"turn_id": "turn-1", "kind": "offline", "reason": "none are reachable right now"}]
    ex, get, unc = _canopy(turn={"status": "queued"}, unclaimable=rows)
    with ex, get, unc:
        assert run_state.execution_state(s)["state"] == "waiting_for_runner"


@override_settings(**ON)
def test_unclaimable_is_only_consulted_for_a_queued_turn():
    """A running turn must never be re-labelled from a stale unclaimable list."""
    s = _session_with_turn()
    rows = [{"turn_id": "turn-1", "kind": "config", "reason": "stale"}]
    ex, get, unc = _canopy(turn={"status": "running"}, unclaimable=rows)
    with ex, get, unc as unc_m:
        assert run_state.execution_state(s)["state"] == "running"
    unc_m.assert_not_called()


@override_settings(**ON)
def test_an_unclaimable_row_for_another_turn_is_ignored():
    """The list is fleet-wide. Matching the wrong row would label a healthy
    queued run 'no runner available' because some OTHER run is stuck."""
    s = _session_with_turn()
    rows = [{"turn_id": "someone-elses-turn", "kind": "config", "reason": "not ours"}]
    ex, get, unc = _canopy(turn={"status": "queued"}, unclaimable=rows)
    with ex, get, unc:
        out = run_state.execution_state(s)
    assert out["state"] == "queued"
    assert out["detail"] == ""


@override_settings(**ON)
@pytest.mark.parametrize(
    "canopy_status,expected",
    [("claimed", "running"), ("running", "running"), ("needs_human", "running"),
     ("done", "done"), ("failed", "failed"), ("cancelled", "cancelled"),
     ("lost", "lost"), ("missed", "missed")],
)
def test_terminal_and_executing_statuses_map_through(canopy_status, expected):
    s = _session_with_turn()
    ex, get, unc = _canopy(turn={"status": canopy_status, "result_note": ""})
    with ex, get, unc:
        assert run_state.execution_state(s)["state"] == expected


@override_settings(**ON)
def test_an_unrecognised_canopy_status_is_unknown_never_running():
    """canopy adding a status ace-web has never heard of must not be guessed at."""
    s = _session_with_turn()
    ex, get, unc = _canopy(turn={"status": "hibernating", "result_note": ""})
    with ex, get, unc:
        assert run_state.execution_state(s)["state"] == "unknown"


@override_settings(**ON)
def test_canopy_unreachable_is_unknown_never_running():
    from apps.canopy.client import CanopyError

    s = _session_with_turn()
    with mock.patch("apps.canopy.client.exchange_token", side_effect=CanopyError(502, "down")):
        out = run_state.execution_state(s)
    assert out["state"] == "unknown"


@override_settings(**ON)
def test_an_unreachable_unclaimable_list_leaves_a_queued_turn_queued():
    """The unclaimable read is an ENRICHMENT. Failing it must not demote a
    queued run to 'unknown' — we already know the turn is queued."""
    from apps.canopy.client import CanopyError

    s = _session_with_turn()
    ex, get, _ = _canopy(turn={"status": "queued"})
    unc = mock.patch(
        "apps.canopy.client.list_unclaimable", side_effect=CanopyError(502, "down"),
    )
    with ex, get, unc:
        assert run_state.execution_state(s)["state"] == "queued"


@override_settings(**ON)
def test_a_dispatch_failed_message_reports_dispatch_failed():
    s = _session_with_turn(turn_id="")
    Message.objects.filter(session=s).update(
        status="error", error_detail="canopy-dispatch: canopy 403: nope",
    )
    assert run_state.execution_state(s)["state"] == "dispatch_failed"


@override_settings(**ON)
def test_an_ordinary_execution_error_is_not_dispatch_failed():
    """Only the `canopy-dispatch:` prefix means 'we never got a turn id'. A
    turnless message that errored for any other reason is not_dispatched."""
    s = _session_with_turn(turn_id="")
    Message.objects.filter(session=s).update(
        status="error", error_detail="CLIBackendError: boom",
    )
    assert run_state.execution_state(s)["state"] == "not_dispatched"


@override_settings(**ON)
def test_the_newest_assistant_turn_is_the_one_reported():
    """A resumed run has several assistant messages; the run's state is the
    latest turn's, not the corpse of the one the resume superseded."""
    s = _session_with_turn()
    Message.objects.create(
        session=s, turn_index=2, role="assistant", content={"text": ""},
        status="pending", canopy_turn_id="turn-2",
    )
    seen = []

    def _get_turn(_token, turn_id):
        seen.append(turn_id)
        return {"status": "running"}

    with (
        mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}),
        mock.patch("apps.canopy.client.get_turn", side_effect=_get_turn),
    ):
        out = run_state.execution_state(s)
    assert seen == ["turn-2"]
    assert out["canopy_turn_id"] == "turn-2"


# ---------------------------------------------------------------------------
# reconcile_session — write the canopy turn's outcome back onto ace-web's rows
# ---------------------------------------------------------------------------


@override_settings(**ON)
def test_reconcile_marks_a_done_turn_complete():
    s = _session_with_turn()
    ex, get, unc = _canopy(turn={"status": "done", "result_note": "ok"})
    with ex, get, unc:
        run_state.reconcile_session(s)
    m = Message.objects.get(session=s, role="assistant")
    assert m.status == "complete"


@override_settings(**ON)
def test_reconcile_marks_a_failed_turn_error_without_the_cancelled_prefix():
    s = _session_with_turn()
    ex, get, unc = _canopy(turn={"status": "failed", "result_note": "boom"})
    with ex, get, unc:
        run_state.reconcile_session(s)
    m = Message.objects.get(session=s, role="assistant")
    assert m.status == "error"
    assert m.error_detail.startswith("canopy:failed")
    # Must NOT match resumable_after_deploy's graceful_cancel leg.
    assert not m.error_detail.startswith("cancelled")


@override_settings(**ON)
def test_reconcile_of_a_canopy_cancelled_turn_is_not_deploy_resumable():
    """The trap the `canopy:` prefix exists for: `cancelled` is also a canopy
    turn status, and writing it raw would make every canopy-cancelled run get
    auto-resumed by the next deploy sweep, forever."""
    s = _session_with_turn()
    ex, get, unc = _canopy(turn={"status": "cancelled", "result_note": "stopped"})
    with ex, get, unc:
        run_state.reconcile_session(s)
    assert not Session.resumable_after_deploy().filter(pk=s.pk).exists()


@override_settings(**ON)
def test_reconcile_keeps_the_heartbeat_fresh_while_waiting_for_a_runner():
    """A run waiting on a runner is alive. A stale beat would make the
    post-deploy sweep resume it on every single deploy, forever."""
    s = _session_with_turn()
    rows = [{"turn_id": "turn-1", "kind": "config", "reason": "no runner"}]
    ex, get, unc = _canopy(turn={"status": "queued"}, unclaimable=rows)
    with ex, get, unc:
        run_state.reconcile_session(s)
    s.refresh_from_db()
    assert s.driver_heartbeat_at is not None
    assert Message.objects.get(session=s, role="assistant").status == "pending"


@override_settings(**ON)
def test_reconcile_marks_a_claimed_turn_streaming():
    s = _session_with_turn()
    ex, get, unc = _canopy(turn={"status": "running", "result_note": ""})
    with ex, get, unc:
        run_state.reconcile_session(s)
    assert Message.objects.get(session=s, role="assistant").status == "streaming"


@override_settings(**ON)
def test_reconcile_leaves_everything_alone_when_canopy_is_unreachable():
    from apps.canopy.client import CanopyError

    s = _session_with_turn()
    with mock.patch("apps.canopy.client.exchange_token", side_effect=CanopyError(502, "down")):
        out = run_state.reconcile_session(s)
    assert out["state"] == "unknown"
    assert Message.objects.get(session=s, role="assistant").status == "pending"


@override_settings(**ON)
def test_reconcile_does_not_stamp_a_heartbeat_when_canopy_is_unreachable():
    """UNKNOWN must not look alive: stamping the beat on a canopy we cannot
    reach would hide a genuinely dead run from the self-heal sweep."""
    from apps.canopy.client import CanopyError

    s = _session_with_turn()
    assert s.driver_heartbeat_at is None
    with mock.patch("apps.canopy.client.exchange_token", side_effect=CanopyError(502, "down")):
        run_state.reconcile_session(s)
    s.refresh_from_db()
    assert s.driver_heartbeat_at is None


@override_settings(**ON)
def test_reconcile_does_not_touch_a_dispatch_failed_message():
    s = _session_with_turn(turn_id="")
    Message.objects.filter(session=s).update(
        status="error", error_detail="canopy-dispatch: canopy 403: nope",
    )
    out = run_state.reconcile_session(s)
    assert out["state"] == "dispatch_failed"
    m = Message.objects.get(session=s, role="assistant")
    assert m.error_detail == "canopy-dispatch: canopy 403: nope"


# ---------------------------------------------------------------------------
# manage.py reconcile_canopy_runs — the deploy-hook / cron entry point
# ---------------------------------------------------------------------------


@override_settings(**ON)
def test_reconcile_command_reports_a_count_per_state():
    from io import StringIO

    from django.core.management import call_command

    _session_with_turn()
    out = StringIO()
    ex, get, unc = _canopy(turn={"status": "done", "result_note": ""})
    with ex, get, unc:
        call_command("reconcile_canopy_runs", stdout=out)
    assert "done: 1" in out.getvalue()


@override_settings(**ON)
def test_reconcile_command_skips_sessions_that_never_went_to_canopy():
    from io import StringIO

    from django.core.management import call_command

    _session_with_turn(turn_id="")  # no canopy_session_id
    out = StringIO()
    with mock.patch("apps.canopy.client.exchange_token") as ex:
        call_command("reconcile_canopy_runs", stdout=out)
    ex.assert_not_called()
    assert out.getvalue().strip() == ""


@override_settings(**ON)
def test_reconcile_command_survives_one_bad_run():
    """A sweep that dies on its first bad row leaves every later run unreconciled
    — the same defect as the resume sweep, in the batch path."""
    from io import StringIO

    from django.core.management import call_command

    _session_with_turn()
    _session_with_turn()
    calls = []

    def _boom(session):
        calls.append(session.pk)
        if len(calls) == 1:
            raise RuntimeError("kaboom")
        return {"state": "done", "detail": "", "canopy_turn_id": "", "canopy_session_id": ""}

    out, err = StringIO(), StringIO()
    with mock.patch("apps.canopy.run_state.reconcile_session", side_effect=_boom):
        call_command("reconcile_canopy_runs", stdout=out, stderr=err)
    assert len(calls) == 2
    assert "kaboom" in err.getvalue()
    assert "done: 1" in out.getvalue()
