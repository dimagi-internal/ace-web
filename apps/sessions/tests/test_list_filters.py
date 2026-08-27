"""Server-side review filters on GET /api/w/<ws>/sessions (ace-web#706).

The corpus was only sweepable by pulling every session and filtering in the
client. These cover each filter's behaviour against a real queryset — the
passthrough test in test_api.py only proves the params reach the builder.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.auth.models import User
from apps.sessions.api import list_sessions_in_workspace
from apps.sessions.models import Message, Session
from apps.workspaces.models import Workspace, WorkspaceMembership


@pytest.fixture
def ws(db):
    creator = User.objects.create_user(email="creator@example.com")
    workspace = Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=creator,
    )
    user = User.objects.create_user(email="member@example.com")
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="editor")
    return workspace, user


def _mk(workspace, user, **kw):
    kw.setdefault("source", "web")
    return Session.create_with_owner(owner=user, workspace=workspace, **kw)


def _touch(session, when):
    """Force updated_at (auto_now would otherwise stamp 'now')."""
    Session.objects.filter(pk=session.pk).update(updated_at=when)
    session.refresh_from_db()
    return session


def _slugs(rows):
    return {r["slug"] for r in rows}


def _list(workspace, **kw):
    kw.setdefault("opp_slug", None)
    kw.setdefault("archived", False)
    return list_sessions_in_workspace(workspace, **kw)


# --- since -----------------------------------------------------------------


@pytest.mark.django_db
def test_since_keeps_only_rows_updated_at_or_after(ws):
    workspace, user = ws
    now = timezone.now()
    old = _touch(_mk(workspace, user), now - timedelta(days=10))
    recent = _touch(_mk(workspace, user), now - timedelta(hours=1))

    out = _list(workspace, since=(now - timedelta(days=1)).isoformat())
    assert _slugs(out) == {recent.slug}
    assert old.slug not in _slugs(out)


@pytest.mark.django_db
def test_since_is_inclusive_of_the_boundary_row(ws):
    """Inclusive by design: a cursor advanced to the newest updated_at it saw
    re-reads that row rather than risking a same-timestamp row being skipped."""
    workspace, user = ws
    boundary = timezone.now() - timedelta(hours=2)
    s = _touch(_mk(workspace, user), boundary)

    assert _slugs(_list(workspace, since=boundary.isoformat())) == {s.slug}


@pytest.mark.django_db
def test_since_accepts_a_trailing_z(ws):
    workspace, user = ws
    _touch(_mk(workspace, user), timezone.now() - timedelta(days=5))
    assert _list(workspace, since="2020-01-01T00:00:00Z")  # does not raise


@pytest.mark.django_db
def test_since_rejects_garbage_with_422(ws):
    from apps.api.errors import ProblemError

    workspace, _ = ws
    with pytest.raises(ProblemError) as e:
        _list(workspace, since="last tuesday")
    assert e.value.status_code == 422


# --- source / status / opp_run_id ------------------------------------------


@pytest.mark.django_db
def test_source_filter(ws):
    workspace, user = ws
    web = _mk(workspace, user, source="web")
    uploaded = _mk(workspace, user, source="upload", status="imported")

    assert _slugs(_list(workspace, source="upload")) == {uploaded.slug}
    assert _slugs(_list(workspace, source="web")) == {web.slug}


@pytest.mark.django_db
def test_source_rejects_unknown_value_with_422(ws):
    from apps.api.errors import ProblemError

    workspace, _ = ws
    with pytest.raises(ProblemError) as e:
        _list(workspace, source="carrier-pigeon")
    assert e.value.status_code == 422


@pytest.mark.django_db
def test_status_filter_replaces_the_archived_toggle(ws):
    """`status=archived` reaches archived rows even though archived=False —
    otherwise the two params silently intersect to the empty set."""
    workspace, user = ws
    _mk(workspace, user, status="active")
    archived = _mk(workspace, user, status="archived")

    assert _slugs(_list(workspace, status="archived")) == {archived.slug}


@pytest.mark.django_db
def test_archived_default_still_excludes_archived(ws):
    workspace, user = ws
    active = _mk(workspace, user, status="active")
    _mk(workspace, user, status="archived")

    assert _slugs(_list(workspace)) == {active.slug}


@pytest.mark.django_db
def test_opp_run_id_filter(ws):
    workspace, user = ws
    a = _mk(workspace, user, opp_slug="bednet", opp_run_id="20260801-1200")
    _mk(workspace, user, opp_slug="bednet", opp_run_id="20260802-0900")

    assert _slugs(_list(workspace, opp_run_id="20260801-1200")) == {a.slug}


# --- halted ----------------------------------------------------------------


def _mk_interrupted(workspace, user):
    s = _mk(
        workspace, user,
        opp_slug="bednet", opp_run_id="20260801-1200",
        driver_heartbeat_at=timezone.now() - timedelta(seconds=3600),
    )
    Message.objects.create(
        session=s, turn_index=1, role="assistant", status="streaming", content={}
    )
    return s


@pytest.mark.django_db
def test_halted_true_keeps_only_interrupted_runs(ws):
    workspace, user = ws
    halted = _mk_interrupted(workspace, user)
    _mk(workspace, user)

    assert _slugs(_list(workspace, halted=True)) == {halted.slug}


@pytest.mark.django_db
def test_halted_false_excludes_interrupted_runs(ws):
    workspace, user = ws
    _mk_interrupted(workspace, user)
    healthy = _mk(workspace, user)

    assert _slugs(_list(workspace, halted=False)) == {healthy.slug}


@pytest.mark.django_db
def test_halted_omitted_returns_both(ws):
    workspace, user = ws
    halted = _mk_interrupted(workspace, user)
    healthy = _mk(workspace, user)

    assert _slugs(_list(workspace)) == {halted.slug, healthy.slug}


# --- is_interrupted on the row ---------------------------------------------


@pytest.mark.django_db
def test_is_interrupted_is_carried_on_the_row(ws):
    """The 'why is this row interesting?' signal, so a reviewer doesn't have
    to open each transcript."""
    workspace, user = ws
    halted = _mk_interrupted(workspace, user)
    healthy = _mk(workspace, user)

    by_slug = {r["slug"]: r for r in _list(workspace)}
    assert by_slug[halted.slug]["is_interrupted"] is True
    assert by_slug[healthy.slug]["is_interrupted"] is False


# --- cursor ordering -------------------------------------------------------


@pytest.mark.django_db
def test_updated_at_ties_break_by_descending_id(ws):
    """The documented tiebreaker. Without it the order of rows sharing an
    updated_at is whatever the database feels like, so a paging reviewer can
    both repeat and skip rows between requests."""
    workspace, user = ws
    same = timezone.now() - timedelta(hours=1)
    tied = [_touch(_mk(workspace, user), same) for _ in range(5)]

    expected = [s.slug for s in sorted(tied, key=lambda s: s.pk, reverse=True)]
    assert [r["slug"] for r in _list(workspace)] == expected


@pytest.mark.django_db
def test_ordering_is_newest_updated_first(ws):
    workspace, user = ws
    now = timezone.now()
    older = _touch(_mk(workspace, user), now - timedelta(days=2))
    newer = _touch(_mk(workspace, user), now - timedelta(hours=1))

    assert [r["slug"] for r in _list(workspace)] == [newer.slug, older.slug]


# --- combination -----------------------------------------------------------


@pytest.mark.django_db
def test_filters_compose(ws):
    """The real reviewer query: 'uploaded sessions for this run since X'."""
    workspace, user = ws
    now = timezone.now()
    want = _touch(
        _mk(workspace, user, source="upload", status="imported",
            opp_slug="bednet", opp_run_id="20260801-1200"),
        now - timedelta(hours=1),
    )
    _touch(  # right run, too old
        _mk(workspace, user, source="upload", status="imported",
            opp_slug="bednet", opp_run_id="20260801-1200"),
        now - timedelta(days=30),
    )
    _touch(  # right window, wrong run
        _mk(workspace, user, source="upload", status="imported",
            opp_slug="bednet", opp_run_id="20260802-0900"),
        now - timedelta(hours=1),
    )
    _touch(  # right window and run, wrong source
        _mk(workspace, user, source="web",
            opp_slug="bednet", opp_run_id="20260801-1200"),
        now - timedelta(hours=1),
    )

    out = _list(
        workspace,
        since=(now - timedelta(days=1)).isoformat(),
        source="upload",
        opp_run_id="20260801-1200",
    )
    assert _slugs(out) == {want.slug}


@pytest.mark.django_db
def test_filters_never_cross_workspaces(ws):
    workspace, user = ws
    other_creator = User.objects.create_user(email="other@example.com")
    other = Workspace.objects.create(
        slug="ws2", display_name="WS2", drive_root_folder_id="folder-2",
        created_by=other_creator,
    )
    mine = _mk(workspace, user, source="upload", status="imported")
    Session.create_with_owner(
        owner=other_creator, workspace=other, source="upload", status="imported"
    )

    assert _slugs(_list(workspace, source="upload")) == {mine.slug}
