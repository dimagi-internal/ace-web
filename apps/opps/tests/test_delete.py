"""Tests for DELETE /api/opps/<slug>/."""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.models import OppWorkspace
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)
from apps.sessions.models import Session


@pytest.fixture
def authed_user(db):
    return User.objects.create(email="deleter@dimagi.com", display_name="Deleter")


@pytest.fixture
def authed_client(authed_user):
    c = Client()
    c.force_login(authed_user)
    return c


def test_delete_opp_success_returns_204(authed_client, authed_user):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    ace_id = fake.folder_id("ACE")
    # Seed a linked Session so we can assert cascade delete.
    Session.objects.create(
        owner=authed_user, title="linked", backend_kind="cli",
        status="active", source="web", opp_slug="malaria-pilot",
    )
    # Seed a matching OppWorkspace so we can assert cascade delete.
    OppWorkspace.objects.create(
        slug="malaria-pilot",
        display_name="Malaria Pilot",
        created_by=authed_user,
    )
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        response = authed_client.delete("/api/opps/malaria-pilot")

    assert response.status_code == 204
    # Folder is gone from Drive.
    assert "malaria-pilot" not in {f.name for f in fake.list_files(ace_id)}
    # Linked session is deleted.
    assert Session.objects.filter(opp_slug="malaria-pilot").count() == 0
    # OppWorkspace is deleted.
    assert OppWorkspace.objects.filter(slug="malaria-pilot").count() == 0


def test_delete_opp_missing_returns_404(authed_client):
    fake = FakeDriveClient.from_tree({"ACE": {}})
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        response = authed_client.delete("/api/opps/ghost")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "opp-not-found"


def test_delete_opp_unauthenticated_returns_401():
    c = Client()
    response = c.delete("/api/opps/malaria-pilot")
    assert response.status_code == 401
