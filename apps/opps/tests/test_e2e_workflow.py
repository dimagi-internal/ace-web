"""End-to-end happy-path test for the opps Workbench.

Exercises the full flow from the opp list → workbench → step detail → discuss,
using the FakeDriveClient fixture. Proves the modules from Tasks 1–21
compose correctly.
"""
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_tree,
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
    return FakeDriveClient.from_tree(malaria_pilot_tree())


@contextmanager
def _patch_drive(fake):
    with patch("apps.opps.access.get_drive_client", lambda *a, **kw: fake), patch(
        "apps.opps.views._resolve_ace_root_folder_id",
        lambda *a, **kw: fake.folder_id("ACE"),
    ):
        yield


def test_full_workflow_list_to_discuss(authed_client, fake_drive):
    with _patch_drive(fake_drive):
        # 1) Opp list
        list_response = authed_client.get("/api/opps/")
        assert list_response.status_code == 200
        cards = list_response.json()["data"]
        assert any(c["slug"] == "malaria-pilot" for c in cards)

        # 2) Workbench for the opp — flat layout synthesizes a single
        # run "r1" with all canonical skills as rows (count driven by
        # the plugin's agent frontmatter; at least 19 today).
        wb_response = authed_client.get("/api/opps/malaria-pilot")
        assert wb_response.status_code == 200
        wb = wb_response.json()["data"]
        assert wb["current_run"]["run_id"] == "r1"
        assert len(wb["current_run"]["steps"]) >= 19

        # 3) Step detail for idea-to-pdd (has a pdd.md artifact)
        step_response = authed_client.get(
            "/api/opps/malaria-pilot/runs/r1/steps/idea-to-pdd"
        )
        assert step_response.status_code == 200
        step = step_response.json()["data"]
        assert step["skill_name"] == "idea-to-pdd"
        assert any(a["name"] == "pdd.md" for a in step["artifacts"])

        # 4) Discuss — creates a new session with the seed system message
        discuss_response = authed_client.post(
            "/api/opps/malaria-pilot/runs/r1/steps/idea-to-pdd/discuss",
            content_type="application/json",
        )
        assert discuss_response.status_code == 201
        session_slug = discuss_response.json()["data"]["session_slug"]

        session = Session.objects.get(slug=session_slug)
        assert session.opp_slug == "malaria-pilot"
        assert session.opp_run_id == "r1"
        assert session.opp_step_skill == "idea-to-pdd"

        seed = session.messages.filter(role="system").first()
        assert seed is not None
        assert "Discussing `idea-to-pdd`" in seed.plaintext
        assert "Malaria Pilot IDD" in seed.plaintext

        # 5) Linked chats now includes the session we just created
        chats_response = authed_client.get(
            "/api/opps/malaria-pilot/runs/r1/steps/idea-to-pdd/chats"
        )
        assert chats_response.status_code == 200
        chats = chats_response.json()["data"]
        assert any(c["slug"] == session_slug for c in chats)


