"""Tests for POST /api/opps/ — web-native opp creation."""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.models import OppWorkspace
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


@pytest.fixture
def authed_client(db):
    User.objects.create(email="jon@dimagi.com", display_name="Jon")
    c = Client()
    c.force_login(User.objects.get(email="jon@dimagi.com"))
    return c


def test_create_opp_happy_path(authed_client, db):
    fake = FakeDriveClient.from_tree({"ACE": {}})
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/",
            data={
                "slug": "malaria-pilot",
                "display_name": "Malaria Pilot 2026",
                "idea": "Use ACE to pilot bed-net distribution...",
                "mode": "review",
            },
            content_type="application/json",
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["error"] is None
    assert body["data"]["slug"] == "malaria-pilot"
    assert body["data"]["working_session_slug"]

    w = OppWorkspace.objects.get(slug="malaria-pilot")
    assert w.display_name == "Malaria Pilot 2026"
    assert w.working_session is not None

    session = w.working_session
    assert session.opp_slug == "malaria-pilot"
    messages = list(session.messages.order_by("turn_index"))
    assert len(messages) == 2
    assert "malaria-pilot" in messages[0].plaintext
    assert "idea-to-pdd" in messages[1].plaintext.lower()

    children = fake.list_files(ace_id)
    assert any(f.name == "malaria-pilot" for f in children)


def test_create_opp_slug_collision(authed_client, db):
    fake = FakeDriveClient.from_tree({"ACE": {"malaria-pilot": {}}})
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/",
            data={
                "slug": "malaria-pilot",
                "display_name": "X",
                "idea": "Y",
                "mode": "review",
            },
            content_type="application/json",
        )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "slug-taken"


def test_create_opp_invalid_slug(authed_client, db):
    resp = authed_client.post(
        "/api/opps/",
        data={
            "slug": "Malaria Pilot",
            "display_name": "X",
            "idea": "Y",
            "mode": "review",
        },
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid-slug"
