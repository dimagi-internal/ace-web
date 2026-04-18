"""Tests for POST /api/opps/<slug>/runs/<run_id>/steps/<skill>/discuss
and GET /api/opps/<slug>/runs/<run_id>/steps/<skill>/chats."""
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


def _with_fake(authed_client, fake):
    return patch.multiple(
        "apps.opps.views",
        get_drive_client=lambda: fake,
        _resolve_ace_root_folder_id=lambda client: fake.folder_id("ACE"),
    )


def test_discuss_creates_session_with_pointer_fields(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    with _with_fake(authed_client, fake):
        response = authed_client.post(
            "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/idea-to-pdd/discuss",
            content_type="application/json",
        )
    assert response.status_code == 201
    data = response.json()["data"]
    session = Session.objects.get(slug=data["session_slug"])
    assert session.opp_slug == "malaria-pilot"
    assert session.opp_run_id == "2026-04-06-002"
    assert session.opp_step_skill == "idea-to-pdd"
    assert session.idd_ref  # populated with the pdd.md drive file id


def test_discuss_seeds_a_system_message(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    with _with_fake(authed_client, fake):
        response = authed_client.post(
            "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/idea-to-pdd/discuss",
            content_type="application/json",
        )
    session = Session.objects.get(slug=response.json()["data"]["session_slug"])
    system_message = session.messages.filter(role="system").first()
    assert system_message is not None
    assert system_message.turn_index == 0
    assert "Discussing `idea-to-pdd`" in system_message.plaintext
    assert "Malaria Pilot IDD" in system_message.plaintext


def test_discuss_auto_titles_the_session(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    with _with_fake(authed_client, fake):
        response = authed_client.post(
            "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/app-deploy/discuss",
            content_type="application/json",
        )
    session = Session.objects.get(slug=response.json()["data"]["session_slug"])
    assert "app-deploy" in session.title
    assert "malaria-pilot" in session.title


def test_linked_chats_list_returns_prior_sessions(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    # Create two prior chats linked to the same step.
    user = User.objects.get(email="jon@dimagi.com")
    Session.objects.create(
        owner=user, title="old discussion",
        opp_slug="malaria-pilot",
        opp_run_id="2026-04-06-002",
        opp_step_skill="app-deploy",
    )
    Session.objects.create(
        owner=user, title="older discussion",
        opp_slug="malaria-pilot",
        opp_run_id="2026-04-06-002",
        opp_step_skill="app-deploy",
    )
    with _with_fake(authed_client, fake):
        response = authed_client.get(
            "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/app-deploy/chats"
        )
    assert response.status_code == 200
    chats = response.json()["data"]
    assert len(chats) == 2
    titles = [c["title"] for c in chats]
    assert "old discussion" in titles
