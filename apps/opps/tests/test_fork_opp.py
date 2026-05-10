"""Smoke tests for opp fork — POST /api/opps/<slug>/fork.

The fork operation does irreversible Drive writes; these tests pin the
contract before bigger features build on top.
"""
from unittest.mock import patch

import pytest
import yaml
from django.core.cache import cache
from django.test import Client

from apps.auth.models import User
from apps.opps.models import OppWorkspace
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


@pytest.fixture(autouse=True)
def _clear_drive_caches():
    """The CachedDriveClient stores DriveFile lookups in Django's cache,
    keyed by folder id. Across tests, FakeDriveClient counter resets to
    1, so a stale cached entry from a prior test will hand back DriveFile
    objects whose ids reference a previous fake's nodes — making the
    second test's ``list_files`` look empty. Flush between tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def authed_client(db):
    User.objects.create(email="jon@dimagi.com", display_name="Jon")
    c = Client()
    c.force_login(User.objects.get(email="jon@dimagi.com"))
    return c


def _source_tree() -> dict:
    """A small but realistic source opp at the multi-run layout. The
    fork should clone the entire subtree and rewrite state.yaml +
    opp.yaml in place."""
    return {
        "ACE": {
            "source-opp": {
                "opp.yaml": (
                    "display_name: Source Opp\n"
                    "slug: source-opp\n"
                    "created_at: 2026-04-01T10:00:00Z\n"
                ),
                "inputs": {
                    "pdd.md": "# PDD\n\nThe design.",
                },
                "runs": {
                    "20260501-1200": {
                        "state.yaml": (
                            "current_phase: ocs-setup\n"
                            "current_step: ocs-agent-setup\n"
                            "started_at: 2026-05-01T12:00:00Z\n"
                            "last_actor: ace@dimagi-ai.com\n"
                            "last_actor_at: 2026-05-01T13:00:00Z\n"
                        ),
                        "1-design": {
                            "idea-to-pdd_decisions.yaml": "decisions: []\n",
                        },
                        "2-commcare": {
                            "pdd-to-learn-app_summary.md": "summary",
                        },
                        "verdicts": {
                            "idea-to-pdd_verdict.yaml": "verdict: pass\n",
                        },
                    },
                },
            },
        },
    }


def test_fork_clones_drive_subtree(authed_client, db):
    """Forking copies opp.yaml + inputs/ + runs/<id>/<phase>/* and patches
    opp.yaml + state.yaml in the new opp."""
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"new_slug": "fork-opp", "fork_at_phase": "design-review"},
            content_type="application/json",
        )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["data"]["slug"] == "fork-opp"

    # Source still exists, fork is a sibling
    children = {c.name for c in fake.list_files(ace_id)}
    assert "source-opp" in children
    assert "fork-opp" in children

    # Recursive copy: phase folders + inputs/ + verdicts/
    fork_root_id = fake.folder_id("ACE/fork-opp")
    fork_children = {c.name for c in fake.list_files(fork_root_id)}
    assert "opp.yaml" in fork_children
    assert "inputs" in fork_children
    assert "runs" in fork_children
    runs_id = fake.folder_id("ACE/fork-opp/runs")
    run_children = {c.name for c in fake.list_files(runs_id)}
    assert "20260501-1200" in run_children
    run_id = fake.folder_id("ACE/fork-opp/runs/20260501-1200")
    sub = {c.name for c in fake.list_files(run_id)}
    assert {"1-design", "2-commcare", "verdicts", "state.yaml"}.issubset(sub)


def test_fork_rewrites_opp_yaml_with_forked_from(authed_client, db):
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"new_slug": "fork-opp", "fork_at_phase": "design-review"},
            content_type="application/json",
        )
    assert resp.status_code == 201

    fork_yaml_id = fake.file_id("ACE/fork-opp/opp.yaml")
    body = fake.get_content(fork_yaml_id, "text/yaml").content
    data = yaml.safe_load(body)
    assert data["slug"] == "fork-opp"
    assert "forked_from" in data
    assert data["forked_from"]["slug"] == "source-opp"
    assert data["forked_from"]["phase"] == "design-review"
    assert data["forked_from"]["run_id"] == "20260501-1200"
    # display_name carries the fork annotation so the list view distinguishes
    assert "fork @ design-review" in data["display_name"]


def test_fork_resets_state_yaml_to_target_phase(authed_client, db):
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"new_slug": "fork-opp", "fork_at_phase": "design-review"},
            content_type="application/json",
        )
    assert resp.status_code == 201

    state_id = fake.file_id("ACE/fork-opp/runs/20260501-1200/state.yaml")
    body = fake.get_content(state_id, "text/yaml").content
    data = yaml.safe_load(body)
    assert data["current_phase"] == "design-review"
    # Reset fields shouldn't carry source's run-time signal forward
    assert "current_step" not in data
    assert "started_at" not in data
    assert "last_actor_at" not in data


def test_fork_creates_workspace_row_and_session(authed_client, db):
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"new_slug": "fork-opp", "fork_at_phase": "design-review"},
            content_type="application/json",
        )
    assert resp.status_code == 201
    body = resp.json()["data"]
    w = OppWorkspace.objects.get(slug="fork-opp")
    assert w.display_name.startswith("source-opp (fork @")
    assert w.working_session is not None
    assert w.working_session.slug == body["working_session_slug"]
    msg = w.working_session.messages.first()
    assert "fork" in msg.plaintext.lower()


def test_fork_rejects_existing_slug(authed_client, db):
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    OppWorkspace.objects.create(
        slug="taken",
        display_name="Taken",
        created_by=User.objects.get(email="jon@dimagi.com"),
    )
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"new_slug": "taken", "fork_at_phase": "design-review"},
            content_type="application/json",
        )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "slug-taken"


def test_fork_rejects_same_slug(authed_client, db):
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"new_slug": "source-opp", "fork_at_phase": "design-review"},
            content_type="application/json",
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "same-slug"


def test_fork_rejects_unknown_source(authed_client, db):
    fake = FakeDriveClient.from_tree({"ACE": {}})
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/no-such/fork",
            data={"new_slug": "fork-x", "fork_at_phase": "design-review"},
            content_type="application/json",
        )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "source-not-found"


def test_fork_rejects_invalid_slug_format(authed_client, db):
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"new_slug": "Bad Slug", "fork_at_phase": "design-review"},
            content_type="application/json",
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid-slug"
