"""Tests for the workspace-activity aggregator."""
from __future__ import annotations

import datetime as dt
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.activity.workspace_activity import (
    ActivityRow,
    detect_source,
    list_workspace_activity,
)
from apps.sessions.models import Session
from apps.workspaces.models import Workspace


@pytest.fixture
def ws(db):
    User = get_user_model()
    user = User.objects.create(email="jj@dimagi.com")
    return Workspace.objects.create(
        slug="dimagi-team", display_name="Dimagi Team",
        drive_root_folder_id="f", created_by=user,
    )


@pytest.mark.django_db
def test_detect_source_returns_ace_web_when_session_exists(ws):
    User = get_user_model()
    jj = User.objects.get(email="jj@dimagi.com")
    Session.create_with_owner(
        owner=jj, workspace=ws,
        opp_slug="turmeric", opp_run_id="20260515-1830",
        status="active", title="t",
    )
    hint, actor = detect_source(
        workspace=ws, opp_slug="turmeric", run_id="20260515-1830",
    )
    assert hint == "ace-web"
    assert actor == "jj@dimagi.com"


@pytest.mark.django_db
def test_detect_source_returns_drive_only_when_no_session(ws):
    hint, actor = detect_source(
        workspace=ws, opp_slug="loner", run_id="20260515-2000",
    )
    assert hint == "drive-only"
    assert actor is None


@pytest.mark.django_db
def test_detect_source_ignores_inactive_session(ws):
    User = get_user_model()
    jj = User.objects.get(email="jj@dimagi.com")
    Session.create_with_owner(
        owner=jj, workspace=ws,
        opp_slug="turmeric", opp_run_id="20260515-1830",
        status="archived", title="t",
    )
    hint, _ = detect_source(
        workspace=ws, opp_slug="turmeric", run_id="20260515-1830",
    )
    assert hint == "drive-only"


@pytest.mark.django_db
def test_list_excludes_opps_with_no_runs(ws):
    with patch("apps.activity.workspace_activity.list_opp_cards") as mock_cards:
        mock_cards.return_value = [
            {"slug": "fresh-opp", "title": "Fresh", "last_run_id": None,
             "current_phase": None, "status": "no-state",
             "last_activity_at": None},
            {"slug": "has-runs", "title": "Has Runs",
             "last_run_id": "20260515-1830",
             "current_phase": "connect-setup", "status": "ok",
             "last_activity_at": "2026-05-15T18:30:00Z"},
        ]
        rows = list_workspace_activity(ws)
    assert len(rows) == 1
    assert rows[0].opp_slug == "has-runs"


@pytest.mark.django_db
def test_list_drops_old_complete_runs_by_default(ws):
    """Completed runs older than 24h drop out of the default feed."""
    now = dt.datetime.now(dt.UTC)
    old = (now - dt.timedelta(hours=48)).isoformat().replace("+00:00", "Z")
    recent = (now - dt.timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    with patch("apps.activity.workspace_activity.list_opp_cards") as mock_cards:
        mock_cards.return_value = [
            {"slug": "old-complete", "title": "Old", "last_run_id": "r1",
             "current_phase": None, "status": "ok",
             "last_activity_at": old},
            {"slug": "recent-complete", "title": "Recent", "last_run_id": "r2",
             "current_phase": None, "status": "ok",
             "last_activity_at": recent},
            {"slug": "in-progress", "title": "Working", "last_run_id": "r3",
             "current_phase": "scenarios", "status": "ok",
             "last_activity_at": old},  # in-progress kept regardless of age
        ]
        rows = list_workspace_activity(ws)
    slugs = [r.opp_slug for r in rows]
    assert "old-complete" not in slugs
    assert "recent-complete" in slugs
    assert "in-progress" in slugs


@pytest.mark.django_db
def test_list_include_completed_false_drops_all_complete(ws):
    now = dt.datetime.now(dt.UTC)
    recent = (now - dt.timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    with patch("apps.activity.workspace_activity.list_opp_cards") as mock_cards:
        mock_cards.return_value = [
            {"slug": "done", "title": "Done", "last_run_id": "r1",
             "current_phase": None, "status": "ok",
             "last_activity_at": recent},
            {"slug": "working", "title": "Working", "last_run_id": "r2",
             "current_phase": "scenarios", "status": "ok",
             "last_activity_at": recent},
        ]
        rows = list_workspace_activity(ws, include_completed=False)
    slugs = [r.opp_slug for r in rows]
    assert slugs == ["working"]


@pytest.mark.django_db
def test_list_sorts_by_last_activity_desc(ws):
    now = dt.datetime.now(dt.UTC)
    earlier = (now - dt.timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    later = (now - dt.timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    with patch("apps.activity.workspace_activity.list_opp_cards") as mock_cards:
        mock_cards.return_value = [
            {"slug": "earlier", "title": "Earlier", "last_run_id": "r1",
             "current_phase": "p", "status": "ok", "last_activity_at": earlier},
            {"slug": "later", "title": "Later", "last_run_id": "r2",
             "current_phase": "p", "status": "ok", "last_activity_at": later},
        ]
        rows = list_workspace_activity(ws)
    assert [r.opp_slug for r in rows] == ["later", "earlier"]


@pytest.mark.django_db
def test_row_phase_url_points_at_phase_view(ws):
    with patch("apps.activity.workspace_activity.list_opp_cards") as mock_cards:
        mock_cards.return_value = [
            {"slug": "rural-tb", "title": "Rural TB", "last_run_id": "20260515-1830",
             "current_phase": "scenarios", "status": "ok",
             "last_activity_at": "2026-05-15T18:30:00Z"},
        ]
        rows = list_workspace_activity(ws)
    assert len(rows) == 1
    assert rows[0].phase_url.endswith(
        "/w/dimagi-team/opps/rural-tb?run_id=20260515-1830"
    )


@pytest.mark.django_db
def test_row_attributes_ace_web_session_to_actor(ws):
    User = get_user_model()
    jj = User.objects.get(email="jj@dimagi.com")
    Session.create_with_owner(
        owner=jj, workspace=ws,
        opp_slug="rural-tb", opp_run_id="20260515-1830",
        status="active", title="t",
    )
    with patch("apps.activity.workspace_activity.list_opp_cards") as mock_cards:
        mock_cards.return_value = [
            {"slug": "rural-tb", "title": "Rural TB", "last_run_id": "20260515-1830",
             "current_phase": "scenarios", "status": "ok",
             "last_activity_at": "2026-05-15T18:30:00Z"},
        ]
        rows = list_workspace_activity(ws)
    assert rows[0].source_hint == "ace-web"
    assert rows[0].source_actor_email == "jj@dimagi.com"


@pytest.mark.django_db
def test_row_drive_only_when_no_session_match(ws):
    with patch("apps.activity.workspace_activity.list_opp_cards") as mock_cards:
        mock_cards.return_value = [
            {"slug": "laptop-run", "title": "Laptop Run",
             "last_run_id": "20260515-1830",
             "current_phase": "scenarios", "status": "ok",
             "last_activity_at": "2026-05-15T18:30:00Z"},
        ]
        rows = list_workspace_activity(ws)
    assert rows[0].source_hint == "drive-only"
    assert rows[0].source_actor_email is None


@pytest.mark.django_db
def test_to_dict_includes_all_fields(ws):
    row = ActivityRow(
        opp_slug="x", opp_display_name="X", run_id="r",
        last_activity_at="2026-01-01T00:00:00Z",
        current_phase_name="p", current_phase_display="Phase",
        current_step_name="s", current_step_display="Step",
        lifecycle_status="in_progress", last_actor=None,
        source_hint="ace-web", source_actor_email="x@y.com",
        phase_url="https://example.com/x",
    )
    d = row.to_dict()
    assert d["opp_slug"] == "x"
    assert d["source_hint"] == "ace-web"
    assert d["phase_url"] == "https://example.com/x"
