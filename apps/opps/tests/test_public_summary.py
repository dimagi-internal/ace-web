"""Tests for the public per-run summary endpoint.

GET /api/opps/public/<workspace>/<slug>/runs/<run_id>/summary

Auth-exempt by design — anonymous Django Client requests must succeed.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import Client

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


def _make_tree() -> dict:
    return {
        "ACE": {
            "smoke-pilot": {
                "opp.yaml": "display_name: Smoke Pilot\nslug: smoke-pilot\n",
                "inputs": {"pdd.md": "# Smoke Pilot\n\nA short description.\n"},
                "runs": {
                    "20260415-1430": {
                        "2-commcare": {
                            "pdd-to-learn-app_summary.md": (
                                "---\n"
                                "nova_app_id: x\n"
                                "nova_app_url: https://commcare.app/apps/x\n"
                                "title: Smoke Learn\n"
                                "---\n# Smoke Learn\n"
                            ),
                            "app-deploy_summary.md": (
                                "---\n"
                                "learn_app_url: https://www.commcarehq.org/a/smoke/apps/view/abc/\n"
                                "---\n"
                            ),
                        },
                    },
                },
            },
        }
    }


@pytest.fixture
def fake_drive():
    return FakeDriveClient.from_tree(_make_tree())


@pytest.fixture
def workspace(db):
    """Workspace with a real drive_root_folder_id (placeholder, since the
    drive client is mocked in tests)."""
    from apps.auth.models import User
    from apps.workspaces.models import Workspace, WorkspaceMembership

    owner = User.objects.first() or User.objects.create(
        email="placeholder@test", display_name="Placeholder",
    )
    ws, _created = Workspace.objects.get_or_create(
        slug="smoke-team",
        defaults={
            "display_name": "Smoke Team",
            "drive_root_folder_id": "smoke-team-root",
            "created_by": owner,
        },
    )
    WorkspaceMembership.objects.get_or_create(
        workspace=ws, user=owner, defaults={"role": "owner"},
    )
    return ws


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_anonymous_request_succeeds(fake_drive, workspace):
    """A Client with no login can hit the public summary endpoint and
    receive the JSON envelope (no auth redirect)."""
    workspace.drive_root_folder_id = fake_drive.folder_id("ACE")
    workspace.save()
    c = Client()
    with patch("apps.opps.views.get_drive_client", return_value=fake_drive):
        response = c.get(
            "/api/opps/public/smoke-team/smoke-pilot/runs/20260415-1430/summary"
        )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["error"] is None
    payload = body["data"]
    assert payload["opp"]["slug"] == "smoke-pilot"
    assert payload["opp"]["display_name"] == "Smoke Pilot"
    assert payload["apps"][0]["kind"] == "Learn"


def test_unknown_run_returns_404(fake_drive, workspace):
    workspace.drive_root_folder_id = fake_drive.folder_id("ACE")
    workspace.save()
    c = Client()
    with patch("apps.opps.views.get_drive_client", return_value=fake_drive):
        response = c.get(
            "/api/opps/public/smoke-team/smoke-pilot/runs/does-not-exist/summary"
        )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not-found"


def test_unknown_workspace_returns_404(fake_drive):
    """No workspace named 'no-such-workspace' exists; same 404 envelope
    so existence isn't leaked."""
    c = Client()
    response = c.get(
        "/api/opps/public/no-such-workspace/anything/runs/anything/summary"
    )
    assert response.status_code == 404


def test_unknown_opp_returns_404(fake_drive, workspace):
    workspace.drive_root_folder_id = fake_drive.folder_id("ACE")
    workspace.save()
    c = Client()
    with patch("apps.opps.views.get_drive_client", return_value=fake_drive):
        response = c.get(
            "/api/opps/public/smoke-team/no-such-opp/runs/r1/summary"
        )
    assert response.status_code == 404


def test_response_is_cached(fake_drive, workspace):
    """Second call within the TTL should NOT hit the drive client."""
    workspace.drive_root_folder_id = fake_drive.folder_id("ACE")
    workspace.save()
    c = Client()
    call_count = {"n": 0}

    def _track(*args, **kwargs):
        call_count["n"] += 1
        return fake_drive

    with patch("apps.opps.views.get_drive_client", side_effect=_track):
        r1 = c.get(
            "/api/opps/public/smoke-team/smoke-pilot/runs/20260415-1430/summary"
        )
        r2 = c.get(
            "/api/opps/public/smoke-team/smoke-pilot/runs/20260415-1430/summary"
        )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert call_count["n"] == 1, "second call should be cached"


def test_404_is_not_cached(fake_drive, workspace):
    """A 404 must not poison the cache — once the run is published it
    should become visible immediately."""
    workspace.drive_root_folder_id = fake_drive.folder_id("ACE")
    workspace.save()
    c = Client()
    call_count = {"n": 0}

    def _track(*args, **kwargs):
        call_count["n"] += 1
        return fake_drive

    with patch("apps.opps.views.get_drive_client", side_effect=_track):
        c.get("/api/opps/public/smoke-team/smoke-pilot/runs/missing/summary")
        c.get("/api/opps/public/smoke-team/smoke-pilot/runs/missing/summary")

    assert call_count["n"] == 2, "404s should not be cached"


def test_spa_shell_anonymous_does_not_redirect():
    """The SPA shell at /opps/<workspace>/<slug>/runs/<id>/summary must
    serve index.html anonymously rather than redirecting to /auth/login.
    """
    c = Client()
    response = c.get("/opps/anything/anything/runs/anything/summary")
    # 200 OK serving index.html (the React app), NOT a 302 to login.
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
