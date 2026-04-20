"""Tests for GET /api/opps/<slug>/runs/<run_id>/steps/<skill>.

Flat layout synthesizes a single implicit run with id "r1"; the URL
pattern still carries `run_id` for back-compat but the value is
ignored by the handler. See docs/plans/2026-04-20-drop-multi-run-simplify.md.
"""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_tree,
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


def test_step_detail_returns_payload_with_primary_body(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_tree())
    response = _with_fake(
        authed_client, fake,
        "/api/opps/malaria-pilot/runs/r1/steps/idea-to-pdd",
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["skill_name"] == "idea-to-pdd"
    # Flat layout: no judge verdicts carried through.
    assert data["judge"] is None
    # idea-to-pdd's artifact is the opp-root pdd.md.
    assert any(a["name"] == "pdd.md" for a in data["artifacts"])
    assert "primary_body" in data
    assert "Malaria Pilot IDD" in data["primary_body"]


def test_step_detail_unknown_step_returns_404(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_tree())
    response = _with_fake(
        authed_client, fake,
        "/api/opps/malaria-pilot/runs/r1/steps/nonexistent",
    )
    assert response.status_code == 404
