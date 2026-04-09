"""Tests for GET /api/opps/ — the opportunity list endpoint."""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
    nutrition_legacy_flat_tree,
)


@pytest.fixture
def user_with_token(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    u.drive_token_cache = "ciphertext"
    u.save()
    return u


@pytest.fixture
def authed_client(user_with_token):
    c = Client()
    c.force_login(user_with_token)
    return c


def _combined_tree() -> dict:
    """Both fixtures under one ACE folder, to verify the list endpoint returns both."""
    return {
        "ACE": {
            **malaria_pilot_structured_tree()["ACE"],
            **nutrition_legacy_flat_tree()["ACE"],
        }
    }


def test_opp_list_returns_both_structured_and_flat(authed_client):
    fake = FakeDriveClient.from_tree(_combined_tree())
    with patch("apps.opps.views.get_drive_client_for", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    cards = body["data"]
    slugs = {c["slug"] for c in cards}
    assert slugs == {"malaria-pilot", "nutrition-legacy"}


def test_opp_list_malaria_card_fields(authed_client):
    fake = FakeDriveClient.from_tree(_combined_tree())
    with patch("apps.opps.views.get_drive_client_for", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    cards = response.json()["data"]
    malaria = next(c for c in cards if c["slug"] == "malaria-pilot")
    assert malaria["display_name"] == "Malaria Pilot — Northern Mozambique"
    assert malaria["current_run_id"] == "2026-04-06-002"
    assert "malaria" in malaria["labels"]


def test_opp_list_requires_drive_token(db):
    user = User.objects.create(email="no-token@dimagi.com", display_name="Nobody")
    c = Client()
    c.force_login(user)
    response = c.get("/api/opps/")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["message"]
    assert body["data"] == {"reconnect_url": "/auth/drive/start"}


def test_opp_list_unauthenticated_returns_401():
    c = Client()
    response = c.get("/api/opps/")
    assert response.status_code == 401
