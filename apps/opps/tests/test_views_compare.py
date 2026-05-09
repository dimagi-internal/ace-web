"""Tests for GET /api/opps/compare/<a>/<b> — side-by-side opp comparison.

Covers the happy path (two opps, summary deltas correct), the same-opp
guard, the unknown-opp 404, and the workspace-membership boundary
(unauthenticated request, opp from another workspace).
"""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    compare_pair_tree,
    malaria_pilot_tree,
)


@pytest.fixture
def authed_user(db):
    return User.objects.create(email="jon@dimagi.com", display_name="Jon")


@pytest.fixture
def authed_client(authed_user):
    c = Client()
    c.force_login(authed_user)
    return c


def _with_fake_drive(authed_client, fake, url):
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        return authed_client.get(url)


def test_compare_returns_both_snapshots_and_summary(authed_client):
    fake = FakeDriveClient.from_tree(compare_pair_tree())
    response = _with_fake_drive(
        authed_client, fake, "/api/opps/compare/idea-v1/idea-v2"
    )
    assert response.status_code == 200, response.content
    data = response.json()["data"]

    assert data["a"]["opp"]["slug"] == "idea-v1"
    assert data["b"]["opp"]["slug"] == "idea-v2"
    # Both snapshots carry full step lists.
    assert len(data["a"]["current_run"]["steps"]) >= 1
    assert len(data["b"]["current_run"]["steps"]) >= 1


def test_compare_summary_score_delta(authed_client):
    fake = FakeDriveClient.from_tree(compare_pair_tree())
    response = _with_fake_drive(
        authed_client, fake, "/api/opps/compare/idea-v1/idea-v2"
    )
    summary = response.json()["data"]["summary"]
    assert summary["score_a"] == 70
    assert summary["score_b"] == 82
    assert summary["score_delta"] == 12
    assert summary["passed_a"] is False
    assert summary["passed_b"] is True


def test_compare_score_delta_is_null_when_one_opp_unscored(authed_client):
    """Compare should not 500 when one opp has no opp-eval verdict."""
    tree = compare_pair_tree()
    # Strip v2's verdict — score_b becomes None, delta becomes None.
    del tree["ACE"]["idea-v2"]["verdicts"]
    fake = FakeDriveClient.from_tree(tree)
    response = _with_fake_drive(
        authed_client, fake, "/api/opps/compare/idea-v1/idea-v2"
    )
    assert response.status_code == 200
    summary = response.json()["data"]["summary"]
    assert summary["score_a"] == 70
    assert summary["score_b"] is None
    assert summary["score_delta"] is None


def test_compare_same_opp_returns_400(authed_client):
    fake = FakeDriveClient.from_tree(compare_pair_tree())
    response = _with_fake_drive(
        authed_client, fake, "/api/opps/compare/idea-v1/idea-v1"
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "same-opp"


def test_compare_unknown_left_returns_404(authed_client):
    fake = FakeDriveClient.from_tree(compare_pair_tree())
    response = _with_fake_drive(
        authed_client, fake, "/api/opps/compare/nope-v1/idea-v2"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "opp-not-found"


def test_compare_unknown_right_returns_404(authed_client):
    fake = FakeDriveClient.from_tree(compare_pair_tree())
    response = _with_fake_drive(
        authed_client, fake, "/api/opps/compare/idea-v1/nope-v2"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "opp-not-found"


def test_compare_unauthenticated_returns_401():
    """No login → no compare. Workspace boundary is enforced via
    _require_drive → _resolve_workspace, which returns 401 for
    unauthenticated callers."""
    fake = FakeDriveClient.from_tree(compare_pair_tree())
    c = Client()
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        r = c.get("/api/opps/compare/idea-v1/idea-v2")
    assert r.status_code == 401


def test_compare_with_malaria_fixture_works_too(authed_client):
    """Sanity: the malaria fixture only has one opp; comparing it to a
    non-existent one should 404 the second slug, not crash on the first."""
    fake = FakeDriveClient.from_tree(malaria_pilot_tree())
    response = _with_fake_drive(
        authed_client, fake, "/api/opps/compare/malaria-pilot/idea-v2"
    )
    assert response.status_code == 404
