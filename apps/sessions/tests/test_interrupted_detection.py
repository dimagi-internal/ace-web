"""Deterministic detection of runs killed mid-flight (e.g. ECS task replaced
by a deploy). A run is interrupted iff its assistant turn is non-terminal
(streaming/pending) but the driver heartbeat has gone stale/null."""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.sessions.models import Message, Session

User = get_user_model()
pytestmark = pytest.mark.django_db


def _run(status, *, heartbeat_age_s=None):
    """A session with one assistant message in `status` and a heartbeat
    `heartbeat_age_s` seconds ago (None = never beat)."""
    user = User.objects.create_user(email=f"u{Session.objects.count()}@x.com")
    hb = None if heartbeat_age_s is None else timezone.now() - timedelta(seconds=heartbeat_age_s)
    s = Session.create_with_owner(owner=user, source="web", driver_heartbeat_at=hb)
    Message.objects.create(session=s, turn_index=0, role="user", status="complete", content={})
    Message.objects.create(session=s, turn_index=1, role="assistant", status=status, content={})
    return s


def _slugs(qs):
    return set(qs.values_list("slug", flat=True))


def test_streaming_with_stale_heartbeat_is_interrupted():
    s = _run("streaming", heartbeat_age_s=300)  # 5 min stale
    assert s.slug in _slugs(Session.interrupted())


def test_streaming_with_fresh_heartbeat_is_live_not_interrupted():
    s = _run("streaming", heartbeat_age_s=10)  # beat 10s ago — alive
    assert s.slug not in _slugs(Session.interrupted())


def test_streaming_with_null_heartbeat_is_interrupted():
    s = _run("streaming", heartbeat_age_s=None)  # driver never beat
    assert s.slug in _slugs(Session.interrupted())


def test_pending_with_stale_heartbeat_is_interrupted():
    s = _run("pending", heartbeat_age_s=300)
    assert s.slug in _slugs(Session.interrupted())


def test_complete_turn_is_not_interrupted():
    s = _run("complete", heartbeat_age_s=300)  # finished — not a resume candidate
    assert s.slug not in _slugs(Session.interrupted())


def test_errored_turn_is_not_in_this_detector():
    # Terminal error (e.g. graceful 'cancelled') is a separate, labeled bucket
    # handled by the shutdown-marking path — not the stale-heartbeat detector.
    s = _run("error", heartbeat_age_s=300)
    assert s.slug not in _slugs(Session.interrupted())


def test_grace_window_is_honored():
    s = _run("streaming", heartbeat_age_s=60)
    assert s.slug not in _slugs(Session.interrupted(grace_seconds=90))  # within grace → live
    assert s.slug in _slugs(Session.interrupted(grace_seconds=30))  # beyond grace → interrupted


# ---- auto-resume (#3) ----

def _interrupted_opp_run(opp_run_id="20260604-1551"):
    user = User.objects.create_user(email=f"r{Session.objects.count()}@x.com")
    s = Session.create_with_owner(
        owner=user, source="web", opp_slug="bednet-spot-check",
        opp_run_id=opp_run_id, driver_heartbeat_at=timezone.now() - timedelta(seconds=300),
    )
    Message.objects.create(session=s, turn_index=0, role="user", status="complete", content={})
    Message.objects.create(
        session=s, turn_index=1, role="assistant", status="streaming", content={}
    )
    return s


def test_resume_appends_fresh_run_turn_and_retires_dead_one():
    from apps.sessions.api import resume_session_run

    s = _interrupted_opp_run()
    res = resume_session_run(s)
    assert res is not None
    assert res["command"] == "/ace:run bednet-spot-check/20260604-1551 --no-evals"
    # dead assistant turn retired so the detector stops flagging it
    old = Message.objects.get(session=s, turn_index=1)
    assert old.status == "error" and "superseded" in old.error_detail
    # fresh user + assistant turns appended
    new_assistant = Message.objects.get(pk=res["assistant_message_id"])
    assert new_assistant.role == "assistant" and new_assistant.status == "pending"
    assert new_assistant.turn_index == 3
    assert Message.objects.get(session=s, turn_index=2).plaintext == res["command"]
    # after resume (old turn retired) the session is no longer interrupted
    assert s.slug not in _slugs(Session.interrupted())


def test_resume_skips_non_opp_session():
    from apps.sessions.api import resume_session_run

    user = User.objects.create_user(email="noopp@x.com")
    s = Session.create_with_owner(owner=user, source="web")  # no opp_run_id
    Message.objects.create(
        session=s, turn_index=1, role="assistant", status="streaming", content={}
    )
    assert resume_session_run(s) is None


# ---------------------------------------------------------------------------
# resumable_after_deploy — the post-deploy hook's resume scope. Wider than
# interrupted() (also catches graceful SIGTERM cancels marked
# error:'cancelled (partial:...)') but age-bounded so ancient corpses and old
# user-stops aren't revived. See the live-validation finding: ECS task-drain
# SIGTERMs the driver, which marks the turn cancelled, NOT streaming.
# ---------------------------------------------------------------------------


def _cancelled(
    *, detail="cancelled (partial: 1200 chars)", completed_age_s=60, heartbeat_age_s=120
):
    """A session whose assistant turn was marked error with `detail`, completed
    `completed_age_s` ago (the kill moment)."""
    user = User.objects.create_user(email=f"c{Session.objects.count()}@x.com")
    hb = None if heartbeat_age_s is None else timezone.now() - timedelta(seconds=heartbeat_age_s)
    s = Session.create_with_owner(owner=user, source="web", driver_heartbeat_at=hb)
    Message.objects.create(session=s, turn_index=0, role="user", status="complete", content={})
    Message.objects.create(
        session=s, turn_index=1, role="assistant", status="error",
        error_detail=detail, completed_at=timezone.now() - timedelta(seconds=completed_age_s),
        content={},
    )
    return s


def test_resumable_includes_recent_graceful_cancel():
    # The common deploy path: SIGTERM → driver marks turn cancelled.
    s = _cancelled(completed_age_s=60)
    assert s.slug in _slugs(Session.resumable_after_deploy())


def test_resumable_excludes_old_cancelled_turn():
    # An ancient cancel (or a user-stop days ago) must NOT be revived.
    s = _cancelled(completed_age_s=3 * 24 * 3600)
    assert s.slug not in _slugs(Session.resumable_after_deploy())


def test_resumable_excludes_genuine_error_turn():
    # A real logic error is terminal — not a deploy casualty.
    s = _cancelled(detail="CLIBackendError: boom", completed_age_s=60)
    assert s.slug not in _slugs(Session.resumable_after_deploy())


def test_resumable_includes_recent_hard_kill():
    # SIGKILL/vanish leaves the turn streaming with a recent-but-stale beat.
    s = _run("streaming", heartbeat_age_s=180)
    assert s.slug in _slugs(Session.resumable_after_deploy())


def test_resumable_excludes_ancient_null_heartbeat_corpse():
    # Pre-heartbeat corpse (null beat, undateable) — don't revive on every deploy.
    s = _run("streaming", heartbeat_age_s=None)
    assert s.slug not in _slugs(Session.resumable_after_deploy())


def test_resumable_excludes_live_run():
    s = _run("streaming", heartbeat_age_s=10)  # fresh beat — still alive
    assert s.slug not in _slugs(Session.resumable_after_deploy())


def test_resumable_excludes_stale_hard_kill_beyond_max_age():
    # Streaming but last beat is hours ago → older than the deploy window.
    s = _run("streaming", heartbeat_age_s=3 * 3600)
    assert s.slug not in _slugs(Session.resumable_after_deploy())


def test_resume_neutralizes_cancelled_turn_no_double_resume():
    # After resuming a graceful-cancel run, its old cancelled turn must stop
    # matching the resume scope — else the next deploy sweep re-resumes it.
    from apps.sessions.api import resume_session_run

    s = _cancelled(completed_age_s=60)
    s.opp_slug = "bednet-spot-check"
    s.opp_run_id = "20260604-2058"
    s.save()
    assert s.slug in _slugs(Session.resumable_after_deploy())
    res = resume_session_run(s)
    assert res is not None
    assert s.slug not in _slugs(Session.resumable_after_deploy())
