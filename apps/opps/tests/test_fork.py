"""Tests for POST /api/opps/<slug>/runs/<run_id>/fork."""
import json
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
    return User.objects.create(email="jon@dimagi.com", display_name="Jon")


@pytest.fixture
def authed_client(authed_user, db):
    c = Client()
    c.force_login(authed_user)
    return c


@pytest.fixture
def seeded_opp(authed_user, db):
    """Build the structured malaria-pilot fixture and create a matching
    OppWorkspace + initial working session so the fork flow can repoint it."""
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    existing_session = Session.objects.create(
        owner=authed_user,
        opp_slug="malaria-pilot",
        opp_run_id="2026-04-06-002",
        backend_kind="cli",
        status="active",
        source="web",
    )
    OppWorkspace.objects.create(
        slug="malaria-pilot",
        display_name="Malaria",
        working_session=existing_session,
        created_by=authed_user,
    )
    return fake


def _patches(fake):
    return patch.multiple(
        "apps.opps.views",
        get_drive_client=lambda: fake,
        _resolve_ace_root_folder_id=lambda client: fake.folder_id("ACE"),
    )


def test_fork_with_feedback_creates_new_run(authed_client, seeded_opp):
    """Discover a step from the fixture, fork from it, verify new run exists."""
    fake = seeded_opp
    with _patches(fake):
        resp = authed_client.get("/api/opps/malaria-pilot")
        assert resp.status_code == 200
        snap = resp.json()["data"]
        run_id = snap["current_run"]["run_id"]
        steps = snap["current_run"]["steps"]
        assert len(steps) >= 2, "fixture must have 2+ steps"
        # Pick the last step so there's upstream context to inherit.
        from_skill = steps[-1]["skill_name"]

        resp = authed_client.post(
            f"/api/opps/malaria-pilot/runs/{run_id}/fork",
            data=json.dumps({
                "from_skill": from_skill,
                "mode": "with-feedback",
                "feedback": "Make the bed nets bigger.",
            }),
            content_type="application/json",
        )

    assert resp.status_code == 201, resp.json()
    body = resp.json()["data"]
    assert body["new_run_id"] != run_id
    assert body["new_run_id"].startswith("run-")
    new_session_slug = body["working_session_slug"]

    # New session has the feedback seeded.
    session = Session.objects.get(slug=new_session_slug)
    msgs = list(session.messages.order_by("turn_index"))
    assert len(msgs) == 2
    assert msgs[0].role == "system"
    assert msgs[1].role == "user"
    assert "Make the bed nets bigger" in msgs[1].plaintext

    # Workspace working_session repointed to the new session.
    workspace = OppWorkspace.objects.get(slug="malaria-pilot")
    assert workspace.working_session_id == session.pk

    # The new run folder has a steps/ subfolder containing only upstream skills.
    runs_id = fake.folder_id("ACE/malaria-pilot/runs")
    new_run_folder_id = next(
        f.id for f in fake.list_files(runs_id) if f.name == body["new_run_id"]
    )
    children_names = {f.name for f in fake.list_files(new_run_folder_id)}
    assert "steps" in children_names
    new_steps_id = next(
        f.id for f in fake.list_files(new_run_folder_id) if f.name == "steps"
    )
    inherited = sorted(f.name for f in fake.list_files(new_steps_id))
    # Should be ordinals strictly less than the fork step's ordinal.
    fork_ordinal = steps[-1]["ordinal"]
    for name in inherited:
        prefix = int(name.split("-", 1)[0])
        assert prefix < fork_ordinal, f"unexpected inherited step {name}"


def test_fork_empty_creates_minimal_run(authed_client, seeded_opp):
    fake = seeded_opp
    with _patches(fake):
        resp = authed_client.get("/api/opps/malaria-pilot")
        snap = resp.json()["data"]
        run_id = snap["current_run"]["run_id"]
        from_skill = snap["current_run"]["steps"][0]["skill_name"]

        resp = authed_client.post(
            f"/api/opps/malaria-pilot/runs/{run_id}/fork",
            data=json.dumps({
                "from_skill": from_skill,
                "mode": "empty",
            }),
            content_type="application/json",
        )

    assert resp.status_code == 201, resp.json()
    new_run_id = resp.json()["data"]["new_run_id"]

    runs_id = fake.folder_id("ACE/malaria-pilot/runs")
    new_run_folder_id = next(
        f.id for f in fake.list_files(runs_id) if f.name == new_run_id
    )
    children_names = {f.name for f in fake.list_files(new_run_folder_id)}
    # Empty fork inherits only state.yaml — no steps/ folder.
    assert "steps" not in children_names
    assert "state.yaml" in children_names


def test_fork_with_feedback_requires_feedback(authed_client, seeded_opp):
    fake = seeded_opp
    with _patches(fake):
        resp = authed_client.get("/api/opps/malaria-pilot")
        run_id = resp.json()["data"]["current_run"]["run_id"]
        from_skill = resp.json()["data"]["current_run"]["steps"][0]["skill_name"]

        resp = authed_client.post(
            f"/api/opps/malaria-pilot/runs/{run_id}/fork",
            data=json.dumps({"from_skill": from_skill, "mode": "with-feedback"}),
            content_type="application/json",
        )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "feedback-required"


def test_fork_unknown_skill_returns_404(authed_client, seeded_opp):
    fake = seeded_opp
    with _patches(fake):
        resp = authed_client.get("/api/opps/malaria-pilot")
        run_id = resp.json()["data"]["current_run"]["run_id"]

        resp = authed_client.post(
            f"/api/opps/malaria-pilot/runs/{run_id}/fork",
            data=json.dumps({
                "from_skill": "nonexistent-skill",
                "mode": "with-feedback",
                "feedback": "x",
            }),
            content_type="application/json",
        )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "step-not-found"
