"""Tests for GET /api/opps/<slug>/runs/<run_id>/steps/<skill>."""
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


def _with_fake(authed_client, fake, url):
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        return authed_client.get(url)


def test_step_detail_returns_full_payload(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake(
        authed_client, fake,
        "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/idea-to-pdd",
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["skill_name"] == "idea-to-pdd"
    assert data["judge"]["score"] == 9.2
    assert len(data["artifacts"]) == 1
    assert "primary_body" in data
    assert "Malaria Pilot IDD" in data["primary_body"]


def test_step_detail_app_deploy_has_gates_no_judge(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake(
        authed_client, fake,
        "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/app-deploy",
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["judge"] is None
    assert len(data["gates"]) == 1
    assert data["gates"][0]["decision"] == "pending"


def test_step_detail_unknown_step_returns_404(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake(
        authed_client, fake,
        "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/nonexistent",
    )
    assert response.status_code == 404
