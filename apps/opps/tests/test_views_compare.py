"""Tests for GET /api/opps/<slug>/compare?from=<a>&to=<b>."""
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
    u.drive_token_cache = "ciphertext"
    u.save()
    c = Client()
    c.force_login(u)
    return c


def _with_fake(authed_client, fake, url):
    with patch("apps.opps.views.get_drive_client_for", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        return authed_client.get(url)


def test_compare_returns_both_runs(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake(
        authed_client, fake,
        "/api/opps/malaria-pilot/compare?from=2026-04-01-001&to=2026-04-06-002",
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["from_run"]["run_id"] == "2026-04-01-001"
    assert data["to_run"]["run_id"] == "2026-04-06-002"
    assert data["opp"]["slug"] == "malaria-pilot"


def test_compare_missing_params_returns_400(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake(
        authed_client, fake, "/api/opps/malaria-pilot/compare?from=2026-04-01-001"
    )
    assert response.status_code == 400
