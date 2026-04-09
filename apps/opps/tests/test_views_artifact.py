"""Tests for GET /api/opps/<slug>/runs/<run_id>/steps/<skill>/artifacts/<name>."""
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


def test_artifact_body_returns_content(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake(
        authed_client, fake,
        "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/idea-to-idd/artifacts/idd.md",
    )
    assert response.status_code == 200
    assert "Malaria Pilot IDD" in response.content.decode()
    assert "text/markdown" in response["Content-Type"]


def test_artifact_body_unknown_artifact_returns_404(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake(
        authed_client, fake,
        "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/idea-to-idd/artifacts/nope.md",
    )
    assert response.status_code == 404
