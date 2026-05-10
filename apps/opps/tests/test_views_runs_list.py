"""Tests for GET /api/opps/<slug>/runs and ?run_id= on workbench."""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.sync import RunSummary


@pytest.fixture
def authed_user(db):
    u = User.objects.create(email="u@example.com", display_name="U")
    return u


@pytest.fixture
def authed_client(authed_user):
    c = Client()
    c.force_login(authed_user)
    return c


@pytest.mark.django_db
def test_runs_list_returns_runs_newest_first(authed_client):
    fake_runs = [
        RunSummary(
            run_id="20260502-1830",
            folder_id="r1830",
            current_phase="ocs",
            current_step="ocs-agent-setup",
            mode="default",
            last_actor="u@example.com",
            last_actor_at="2026-05-02T18:42:00Z",
        ),
        RunSummary(
            run_id="20260502-1430",
            folder_id="r1430",
            current_phase="closeout",
            current_step="cycle-grade",
            mode="default",
            last_actor="u@example.com",
            last_actor_at="2026-05-02T16:01:00Z",
        ),
    ]

    with patch("apps.opps.views.list_opp_runs", return_value=fake_runs), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value="ACE"), \
         patch("apps.opps.access.get_drive_client", return_value=object()):
        resp = authed_client.get("/api/opps/turmeric/runs")

    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    assert [r["run_id"] for r in body["data"]] == ["20260502-1830", "20260502-1430"]


@pytest.mark.django_db
def test_runs_list_includes_all_fields(authed_client):
    fake_runs = [
        RunSummary(
            run_id="20260502-1830",
            folder_id="r1830",
            current_phase="ocs",
            current_step="ocs-agent-setup",
            mode="review",
            last_actor="ace@dimagi.com",
            last_actor_at="2026-05-02T18:42:00Z",
        ),
    ]

    with patch("apps.opps.views.list_opp_runs", return_value=fake_runs), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value="ACE"), \
         patch("apps.opps.access.get_drive_client", return_value=object()):
        resp = authed_client.get("/api/opps/turmeric/runs")

    assert resp.status_code == 200
    row = resp.json()["data"][0]
    assert row["run_id"] == "20260502-1830"
    assert row["folder_id"] == "r1830"
    assert row["current_phase"] == "ocs"
    assert row["current_step"] == "ocs-agent-setup"
    assert row["mode"] == "review"
    assert row["last_actor"] == "ace@dimagi.com"
    assert row["last_actor_at"] == "2026-05-02T18:42:00Z"
    # Display-name + ordinal fields are present in the response shape
    # (values may be null when the slug isn't in the plugin registry —
    # the inline runs UI on /opps falls back gracefully in that case).
    assert "current_phase_display" in row
    assert "current_step_display" in row
    assert "current_phase_ordinal" in row


@pytest.mark.django_db
def test_runs_list_empty_when_no_runs(authed_client):
    with patch("apps.opps.views.list_opp_runs", return_value=[]), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value="ACE"), \
         patch("apps.opps.access.get_drive_client", return_value=object()):
        resp = authed_client.get("/api/opps/turmeric/runs")

    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.django_db
def test_workbench_with_run_id_forwards_to_load_opp(authed_client):
    """?run_id=20260502-1430 is forwarded to load_opp(run_id=...)."""
    captured = {}

    def fake_load_opp(drive, *, ace_folder_id=None, slug=None,
                      ace_root_folder_id=None, opp_slug=None, run_id=None):
        captured["run_id"] = run_id
        # Raise so the view returns 404 rather than serializing a None snapshot.
        raise FileNotFoundError("no opp")

    with patch("apps.opps.views.load_opp", side_effect=fake_load_opp), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value="ACE"), \
         patch("apps.opps.access.get_drive_client", return_value=object()):
        authed_client.get("/api/opps/turmeric?run_id=20260502-1430")

    assert captured["run_id"] == "20260502-1430"


@pytest.mark.django_db
def test_workbench_without_run_id_passes_none(authed_client):
    """Without ?run_id=, load_opp receives run_id=None (latest)."""
    captured = {}

    def fake_load_opp(drive, *, ace_folder_id=None, slug=None,
                      ace_root_folder_id=None, opp_slug=None, run_id=None):
        captured["run_id"] = run_id
        raise FileNotFoundError("no opp")

    with patch("apps.opps.views.load_opp", side_effect=fake_load_opp), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value="ACE"), \
         patch("apps.opps.access.get_drive_client", return_value=object()):
        authed_client.get("/api/opps/turmeric")

    assert captured["run_id"] is None


@pytest.mark.django_db
def test_runs_list_unauthenticated_returns_401():
    c = Client()
    resp = c.get("/api/opps/turmeric/runs")
    assert resp.status_code == 401
