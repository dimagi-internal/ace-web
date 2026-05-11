"""Tests for OppWorkspace.tags — filter on GET /api/opps/ and
PATCH /api/opps/<slug> to update tags.

See docs/plans/2026-04-20-drop-multi-run-simplify.md § Tag UI.
"""
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.models import OppWorkspace
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


@pytest.fixture
def authed_user(db):
    return User.objects.create(email="jon@dimagi.com", display_name="Jon")


@pytest.fixture
def authed_client(authed_user):
    c = Client()
    c.force_login(authed_user)
    return c


def _tree_with_three_opps() -> dict:
    return {
        "ACE": {
            "turmeric-v1": {"idea.md": "v1"},
            "turmeric-v2": {"idea.md": "v2"},
            "unrelated": {"idea.md": "something else"},
        }
    }


@contextmanager
def _patch_drive(fake):
    folder_id = fake.folder_id("ACE")
    with (
        patch("apps.opps.access.get_drive_client", lambda *a, **kw: fake),
        patch("apps.opps.access.resolve_ace_root_folder_id", lambda *a, **kw: folder_id),
    ):
        yield


# --- GET /api/opps/?tags=X,Y filter ---


def test_list_includes_tags_on_each_card(authed_client, authed_user):
    """Every card carries a `tags` array (empty if no DB row / no tags)."""
    OppWorkspace.objects.create(
        slug="turmeric-v1", display_name="v1", created_by=authed_user,
        tags=["turmeric", "smoke-test"],
    )
    fake = FakeDriveClient.from_tree(_tree_with_three_opps())
    with _patch_drive(fake):
        resp = authed_client.get("/api/opps/")
    cards = resp.json()["data"]
    by_slug = {c["slug"]: c for c in cards}
    assert by_slug["turmeric-v1"]["tags"] == ["turmeric", "smoke-test"]
    # Opp with no DB row → empty tags, still shows up.
    assert by_slug["turmeric-v2"]["tags"] == []


def test_list_filters_by_single_tag(authed_client, authed_user):
    OppWorkspace.objects.create(
        slug="turmeric-v1", display_name="v1", created_by=authed_user,
        tags=["turmeric"],
    )
    OppWorkspace.objects.create(
        slug="turmeric-v2", display_name="v2", created_by=authed_user,
        tags=["turmeric"],
    )
    # Note: 'unrelated' has no DB row so no tags.
    fake = FakeDriveClient.from_tree(_tree_with_three_opps())
    with _patch_drive(fake):
        resp = authed_client.get("/api/opps/?tags=turmeric")
    cards = resp.json()["data"]
    assert {c["slug"] for c in cards} == {"turmeric-v1", "turmeric-v2"}


def test_list_filters_by_multiple_tags_intersection(authed_client, authed_user):
    """?tags=a,b returns opps whose tags contain BOTH a and b."""
    OppWorkspace.objects.create(
        slug="turmeric-v1", display_name="v1", created_by=authed_user,
        tags=["turmeric", "smoke-test"],
    )
    OppWorkspace.objects.create(
        slug="turmeric-v2", display_name="v2", created_by=authed_user,
        tags=["turmeric"],  # missing smoke-test
    )
    fake = FakeDriveClient.from_tree(_tree_with_three_opps())
    with _patch_drive(fake):
        resp = authed_client.get("/api/opps/?tags=turmeric,smoke-test")
    cards = resp.json()["data"]
    assert {c["slug"] for c in cards} == {"turmeric-v1"}


def test_list_empty_tags_param_does_not_filter(authed_client, authed_user):
    fake = FakeDriveClient.from_tree(_tree_with_three_opps())
    with _patch_drive(fake):
        resp = authed_client.get("/api/opps/?tags=")
    cards = resp.json()["data"]
    assert len(cards) == 3


# --- PATCH /api/opps/<slug> to update tags ---


def test_patch_tags_creates_workspace_lazily_if_missing(authed_client):
    """No OppWorkspace row yet → PATCH creates one (mirrors the lazy
    materialization pattern in opp_working_session)."""
    assert not OppWorkspace.objects.filter(slug="turmeric-v1").exists()
    resp = authed_client.patch(
        "/api/opps/turmeric-v1",
        data={"tags": ["turmeric", "smoke-test"]},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["tags"] == ["turmeric", "smoke-test"]
    ws = OppWorkspace.objects.get(slug="turmeric-v1")
    assert ws.tags == ["turmeric", "smoke-test"]


def test_patch_tags_replaces_existing(authed_client, authed_user):
    OppWorkspace.objects.create(
        slug="turmeric-v1", display_name="v1", created_by=authed_user,
        tags=["old"],
    )
    resp = authed_client.patch(
        "/api/opps/turmeric-v1",
        data={"tags": ["new", "set"]},
        content_type="application/json",
    )
    assert resp.status_code == 200
    OppWorkspace.objects.get(slug="turmeric-v1").refresh_from_db()
    assert OppWorkspace.objects.get(slug="turmeric-v1").tags == ["new", "set"]


def test_patch_tags_trims_and_dedupes(authed_client):
    """Whitespace stripped, blanks dropped, duplicates collapsed in order."""
    resp = authed_client.patch(
        "/api/opps/turmeric-v1",
        data={"tags": ["  turmeric  ", "smoke-test", "", "turmeric", "new "]},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["tags"] == ["turmeric", "smoke-test", "new"]


def test_patch_tags_rejects_non_list(authed_client):
    resp = authed_client.patch(
        "/api/opps/turmeric-v1",
        data={"tags": "not-a-list"},
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid-tags"


def test_patch_tags_requires_auth():
    c = Client()
    resp = c.patch(
        "/api/opps/turmeric-v1",
        data={"tags": ["turmeric"]},
        content_type="application/json",
    )
    assert resp.status_code == 401
