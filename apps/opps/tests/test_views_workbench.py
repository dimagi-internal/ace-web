"""Tests for GET /api/opps/<slug>."""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)


@pytest.fixture
def authed_user(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    return u


@pytest.fixture
def authed_client(authed_user):
    c = Client()
    c.force_login(authed_user)
    return c


def _with_fake_drive(authed_client, fake, url, **query):
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        return authed_client.get(url, query)


def test_workbench_returns_full_snapshot(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake_drive(authed_client, fake, "/api/opps/malaria-pilot")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["opp"]["slug"] == "malaria-pilot"
    assert data["current_run"]["run_id"] == "2026-04-06-002"
    assert len(data["current_run"]["steps"]) == 4
    assert len(data["runs"]) == 2


def test_workbench_with_run_id_query_param(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake_drive(
        authed_client, fake, "/api/opps/malaria-pilot", run_id="2026-04-01-001"
    )
    data = response.json()["data"]
    assert data["current_run"]["run_id"] == "2026-04-01-001"
    assert len(data["current_run"]["steps"]) == 2


def test_workbench_unknown_opp_returns_404(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake_drive(authed_client, fake, "/api/opps/nonexistent")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "opp-not-found"


def test_workbench_includes_idd_body(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake_drive(authed_client, fake, "/api/opps/malaria-pilot")
    data = response.json()["data"]
    assert "Malaria Pilot IDD" in data["idd_body"]
