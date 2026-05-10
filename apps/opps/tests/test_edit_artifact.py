"""Tests for PUT /api/opps/<slug>/runs/<run_id>/steps/<skill>/artifacts/<name>/write."""
import json
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)


@pytest.fixture
def authed_client(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    c = Client()
    c.force_login(u)
    return c


def test_write_artifact(authed_client):
    """Smoke: PUT updates the file content via DriveClient.update_file."""
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    ace_id = fake.folder_id("ACE")

    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        # Discover the actual run/skill/artifact via the workbench endpoint.
        resp = authed_client.get("/api/opps/malaria-pilot")
        assert resp.status_code == 200
        snap = resp.json()["data"]
        run_id = snap["current_run"]["run_id"]
        step = next(s for s in snap["current_run"]["steps"] if s["artifacts"])
        artifact = step["artifacts"][0]
        skill = step["skill_name"]

        resp = authed_client.put(
            f"/api/opps/malaria-pilot/runs/{run_id}/steps/{skill}"
            f"/artifacts/{artifact['name']}/write",
            data=json.dumps({"content": "# UPDATED CONTENT\n"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["ok"] is True

    # Verify the Drive file got the new content.
    new_body = fake.get_content(artifact["drive_file_id"], artifact["mime_type"]).content
    assert new_body == "# UPDATED CONTENT\n"


def test_unknown_opp_returns_404(authed_client):
    fake = FakeDriveClient.from_tree({"ACE": {}})
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.put(
            "/api/opps/no-such-opp/runs/run-001/steps/idea-to-pdd"
            "/artifacts/pdd.md/write",
            data=json.dumps({"content": "x"}),
            content_type="application/json",
        )
    assert resp.status_code == 404


def test_missing_content_returns_400(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.get("/api/opps/malaria-pilot")
        snap = resp.json()["data"]
        run_id = snap["current_run"]["run_id"]
        step = next(s for s in snap["current_run"]["steps"] if s["artifacts"])
        artifact = step["artifacts"][0]
        skill = step["skill_name"]

        resp = authed_client.put(
            f"/api/opps/malaria-pilot/runs/{run_id}/steps/{skill}"
            f"/artifacts/{artifact['name']}/write",
            data=json.dumps({}),  # no content key
            content_type="application/json",
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "missing-content"


def test_unknown_step_returns_404(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.get("/api/opps/malaria-pilot")
        run_id = resp.json()["data"]["current_run"]["run_id"]
        resp = authed_client.put(
            f"/api/opps/malaria-pilot/runs/{run_id}/steps/no-such-skill"
            f"/artifacts/anything.md/write",
            data=json.dumps({"content": "x"}),
            content_type="application/json",
        )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "step-not-found"


def test_unknown_artifact_returns_404(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.get("/api/opps/malaria-pilot")
        snap = resp.json()["data"]
        run_id = snap["current_run"]["run_id"]
        step = next(s for s in snap["current_run"]["steps"] if s["artifacts"])
        skill = step["skill_name"]

        resp = authed_client.put(
            f"/api/opps/malaria-pilot/runs/{run_id}/steps/{skill}"
            f"/artifacts/no-such-artifact.md/write",
            data=json.dumps({"content": "x"}),
            content_type="application/json",
        )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "artifact-not-found"
