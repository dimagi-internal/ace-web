"""Smoke tests for DELETE /api/opps/<slug>/runs/<run_id> — trash a single run."""
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


@pytest.fixture(autouse=True)
def _clear_drive_caches():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def authed_client(db):
    User.objects.create(email="jon@dimagi.com", display_name="Jon")
    c = Client()
    c.force_login(User.objects.get(email="jon@dimagi.com"))
    return c


def _opp_with_two_runs() -> dict:
    return {
        "ACE": {
            "stale-opp": {
                "opp.yaml": "display_name: Stale Opp\nslug: stale-opp\n",
                "runs": {
                    "20260501-1200": {
                        "state.yaml": "current_phase: ocs\n",
                        "1-design": {"x.md": "x"},
                    },
                    "20260502-1200": {
                        "state.yaml": "current_phase: closeout\n",
                        "1-design": {"y.md": "y"},
                    },
                },
            },
        },
    }


def test_delete_run_trashes_only_named_run(authed_client):
    fake = FakeDriveClient.from_tree(_opp_with_two_runs())
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.delete(
            "/api/opps/stale-opp/runs/20260501-1200",
        )
    assert resp.status_code == 204, resp.content

    # Source opp + the OTHER run still exist on Drive
    runs_id = fake.folder_id("ACE/stale-opp/runs")
    children = {c.name for c in fake.list_files(runs_id)}
    assert "20260501-1200" not in children
    assert "20260502-1200" in children


def test_delete_run_404_on_unknown_run(authed_client):
    fake = FakeDriveClient.from_tree(_opp_with_two_runs())
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.delete(
            "/api/opps/stale-opp/runs/no-such-run",
        )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "run-not-found"


def test_delete_run_404_on_unknown_opp(authed_client):
    fake = FakeDriveClient.from_tree(_opp_with_two_runs())
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.delete(
            "/api/opps/no-such-opp/runs/20260501-1200",
        )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "run-not-found"


def test_delete_run_unauthenticated_returns_401(db):
    fake = FakeDriveClient.from_tree(_opp_with_two_runs())
    ace_id = fake.folder_id("ACE")
    c = Client()
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        resp = c.delete("/api/opps/stale-opp/runs/20260501-1200")
    assert resp.status_code == 401
