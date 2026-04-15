"""End-to-end happy-path test for the opps Workbench.

Exercises the full flow from the opp list → workbench → step detail → discuss,
using the FakeDriveClient fixture. Proves the modules from Tasks 1–21
compose correctly.
"""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)
from apps.sessions.models import Session


@pytest.fixture
def authed_client(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    c = Client()
    c.force_login(u)
    return c


@pytest.fixture
def fake_drive():
    return FakeDriveClient.from_tree(malaria_pilot_structured_tree())


def _patch_drive(fake):
    return patch.multiple(
        "apps.opps.views",
        get_drive_client=lambda: fake,
        _resolve_ace_root_folder_id=lambda client: fake.folder_id("ACE"),
    )


def test_full_workflow_list_to_discuss(authed_client, fake_drive):
    with _patch_drive(fake_drive):
        # 1) Opp list
        list_response = authed_client.get("/api/opps/")
        assert list_response.status_code == 200
        cards = list_response.json()["data"]
        assert any(c["slug"] == "malaria-pilot" for c in cards)

        # 2) Workbench for the opp
        wb_response = authed_client.get("/api/opps/malaria-pilot")
        assert wb_response.status_code == 200
        wb = wb_response.json()["data"]
        assert wb["current_run"]["run_id"] == "2026-04-06-002"
        assert len(wb["current_run"]["steps"]) >= 4

        # 3) Step detail for app-deploy (the gate-pending step)
        step_response = authed_client.get(
            "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/app-deploy"
        )
        assert step_response.status_code == 200
        step = step_response.json()["data"]
        assert "is_gate" not in step  # gate badge is dropped to match the System tab
        assert len(step["gates"]) == 1
        assert step["gates"][0]["decision"] == "pending"

        # 4) Discuss — creates a new session with the seed system message
        discuss_response = authed_client.post(
            "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/app-deploy/discuss",
            content_type="application/json",
        )
        assert discuss_response.status_code == 201
        session_slug = discuss_response.json()["data"]["session_slug"]

        session = Session.objects.get(slug=session_slug)
        assert session.opp_slug == "malaria-pilot"
        assert session.opp_run_id == "2026-04-06-002"
        assert session.opp_step_skill == "app-deploy"

        seed = session.messages.filter(role="system").first()
        assert seed is not None
        assert "Discussing `app-deploy`" in seed.plaintext
        assert "Malaria Pilot IDD" in seed.plaintext
        assert "Gate history" in seed.plaintext

        # 5) Linked chats now includes the session we just created
        chats_response = authed_client.get(
            "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/app-deploy/chats"
        )
        assert chats_response.status_code == 200
        chats = chats_response.json()["data"]
        assert any(c["slug"] == session_slug for c in chats)


def test_full_workflow_compare_runs(authed_client, fake_drive):
    with _patch_drive(fake_drive):
        response = authed_client.get(
            "/api/opps/malaria-pilot/compare?from=2026-04-01-001&to=2026-04-06-002"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["from_run"]["run_id"] == "2026-04-01-001"
        assert data["to_run"]["run_id"] == "2026-04-06-002"
        # The fixture has idd-to-learn-app with judge 7.1 in v1 and 8.5 in v2
        from_lla = next(
            s for s in data["from_run"]["steps"] if s["skill_name"] == "idd-to-learn-app"
        )
        to_lla = next(
            s for s in data["to_run"]["steps"] if s["skill_name"] == "idd-to-learn-app"
        )
        assert from_lla["judge"]["score"] == 7.1
        assert to_lla["judge"]["score"] == 8.5
