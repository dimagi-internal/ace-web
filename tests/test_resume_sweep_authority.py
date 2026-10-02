"""Only the system caller may trigger the post-deploy resume sweep.

`POST /w/{ws}/sessions/resume-interrupted` dispatches every interrupted run AS
ITS OWNER (it continues what a deploy killed). It was gated only on workspace
membership, so any member — partner workspaces hold external reviewers as
members — could make every interrupted run in the workspace execute with its
owner's authority. Now: workspace owners, staff, or an identity named in
`ACE_RESUME_SWEEP_CALLERS`; everyone else gets 403 `resume_sweep_forbidden` and
nothing is touched.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.utils import timezone

from apps.sessions.models import Message, Session
from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()
pytestmark = pytest.mark.django_db

RUN_OWNER = "jjackson@dimagi.com"


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator@example.com"),
    )


@pytest.fixture
def spawned(monkeypatch):
    calls: list[tuple[int, object]] = []
    monkeypatch.setattr(
        "apps.canopy.run_dispatch.start_turn",
        lambda mid, actor=None: calls.append((mid, actor)),
    )
    return calls


def _member(workspace, email, role="editor", **extra):
    user = User.objects.create_user(email=email)
    for k, v in extra.items():
        setattr(user, k, v)
    user.save()
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role)
    return user


def _dead_run(workspace, owner):
    s = Session.create_with_owner(
        owner=owner, workspace=workspace, source="web",
        opp_slug="opp-1", opp_run_id="20261001-0900",
        driver_heartbeat_at=timezone.now() - timedelta(seconds=300),
    )
    dead = Message.objects.create(
        session=s, turn_index=1, role="assistant", status="streaming", content={},
    )
    return s, dead


def _sweep(user):
    c = Client()
    c.force_login(user)
    return c.post("/api/w/ws1/sessions/resume-interrupted")


def test_an_editor_is_refused_and_nothing_is_dispatched(workspace, spawned):
    owner = _member(workspace, RUN_OWNER, role="owner")
    editor = _member(workspace, "reviewer@partner.org")
    session, dead = _dead_run(workspace, owner)

    resp = _sweep(editor)

    assert resp.status_code == 403
    assert resp["Content-Type"].startswith("application/problem+json")
    assert resp.json()["extras"]["code"] == "resume_sweep_forbidden"
    assert spawned == []
    # The dead turn is untouched and no resume turn was appended.
    dead.refresh_from_db()
    assert dead.status == "streaming"
    assert Message.objects.filter(session=session).count() == 1


def test_a_viewer_is_refused(workspace, spawned):
    owner = _member(workspace, RUN_OWNER, role="owner")
    viewer = _member(workspace, "viewer@partner.org", role="viewer")
    _dead_run(workspace, owner)

    assert _sweep(viewer).status_code == 403
    assert spawned == []


def test_a_workspace_owner_still_sweeps(workspace, spawned):
    """The deploy PAT's shape today: a personal token of a workspace owner."""
    owner = _member(workspace, RUN_OWNER, role="owner")
    deployer = _member(workspace, "ace@dimagi-ai.com", role="owner")
    _dead_run(workspace, owner)

    resp = _sweep(deployer)

    assert resp.status_code == 200, resp.content
    assert resp.json()["count"] == 1
    # No actor: the turn still runs as the run's owner, not as the caller.
    assert len(spawned) == 1 and spawned[0][1] is None


def test_staff_may_sweep(workspace, spawned):
    owner = _member(workspace, RUN_OWNER, role="owner")
    staff = _member(workspace, "ops@dimagi.com", is_staff=True)
    _dead_run(workspace, owner)

    assert _sweep(staff).status_code == 200
    assert len(spawned) == 1


@override_settings(ACE_RESUME_SWEEP_CALLERS=["Deploy-Bot@dimagi-ai.com"])
def test_a_configured_deploy_identity_may_sweep_without_being_an_owner(workspace, spawned):
    owner = _member(workspace, RUN_OWNER, role="owner")
    bot = _member(workspace, "deploy-bot@dimagi-ai.com")  # an editor
    _dead_run(workspace, owner)

    assert _sweep(bot).status_code == 200
    assert len(spawned) == 1


@override_settings(ACE_RESUME_SWEEP_CALLERS=["deploy-bot@dimagi-ai.com"])
def test_the_configured_identity_does_not_widen_the_gate_for_anyone_else(workspace, spawned):
    owner = _member(workspace, RUN_OWNER, role="owner")
    editor = _member(workspace, "hal@dimagi-ai.com")
    _dead_run(workspace, owner)

    assert _sweep(editor).status_code == 403
    assert spawned == []


def test_a_non_member_owner_elsewhere_still_gets_404(workspace, spawned):
    """Membership is checked first: workspace existence is never leaked."""
    other = Workspace.objects.create(
        slug="ws2", display_name="WS2", drive_root_folder_id="f2",
        created_by=User.objects.create_user(email="c2@example.com"),
    )
    outsider = _member(other, "boss@elsewhere.org", role="owner")

    assert _sweep(outsider).status_code == 404
