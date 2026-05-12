"""Tests for GET /api/opps/<slug>."""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_tree,
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
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        return authed_client.get(url, query)


def _with_fake_drive_headers(authed_client, fake, url, headers=None, **query):
    """Like _with_fake_drive but also passes extra HTTP headers (e.g. If-None-Match)."""
    headers = headers or {}
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        return authed_client.get(url, query, **headers)


def test_workbench_returns_full_snapshot(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_tree())
    response = _with_fake_drive(authed_client, fake, "/api/opps/malaria-pilot")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["opp"]["slug"] == "malaria-pilot"
    # Flat layout always synthesizes a single run with id "r1".
    assert data["current_run"]["run_id"] == "r1"
    # All canonical skills emitted as rows (status depends on which
    # subfolders carry artifacts). Count is driven by plugin agent
    # frontmatter; at least 19 today.
    assert len(data["current_run"]["steps"]) >= 19


def test_workbench_unknown_opp_returns_404(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_tree())
    response = _with_fake_drive(authed_client, fake, "/api/opps/nonexistent")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "opp-not-found"


def test_workbench_includes_pdd_body(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_tree())
    response = _with_fake_drive(authed_client, fake, "/api/opps/malaria-pilot")
    data = response.json()["data"]
    assert "Malaria Pilot IDD" in data["pdd_body"]


# ── ETag / 304 tests ──────────────────────────────────────────────────────


def test_workbench_returns_etag_header_when_flag_on(settings, authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_tree())
    resp = _with_fake_drive(authed_client, fake, "/api/opps/malaria-pilot")
    assert resp.status_code == 200
    assert resp.headers.get("ETag", "").startswith("sha256:")


def test_workbench_returns_304_when_if_none_match_matches(settings, authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_tree())
    first = _with_fake_drive(authed_client, fake, "/api/opps/malaria-pilot")
    etag = first.headers["ETag"]

    second = _with_fake_drive_headers(
        authed_client, fake, "/api/opps/malaria-pilot",
        headers={"HTTP_IF_NONE_MATCH": etag},
    )
    assert second.status_code == 304
    assert second.content == b""


def test_workbench_returns_200_after_drive_mutation(settings, authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_tree())
    first = _with_fake_drive(authed_client, fake, "/api/opps/malaria-pilot")
    etag1 = first.headers["ETag"]

    state_id = fake.file_id("ACE/malaria-pilot/run_state.yaml")
    fake.update_file(
        state_id, "current_step: ocs-agent-setup\n", "application/x-yaml",
    )

    second = _with_fake_drive_headers(
        authed_client, fake, "/api/opps/malaria-pilot",
        headers={"HTTP_IF_NONE_MATCH": etag1},
    )
    assert second.status_code == 200
    assert second.headers["ETag"] != etag1


def test_workbench_force_param_bypasses_cache(settings, authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_tree())
    first = _with_fake_drive(authed_client, fake, "/api/opps/malaria-pilot")
    etag = first.headers["ETag"]

    forced = _with_fake_drive_headers(
        authed_client, fake, "/api/opps/malaria-pilot?force=1",
        headers={"HTTP_IF_NONE_MATCH": etag},
    )
    assert forced.status_code == 200
