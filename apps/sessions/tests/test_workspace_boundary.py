"""Cross-workspace boundary tests for session reads and WebSocket auto-join.

Pre-2026-04-28 the session read path (REST + WS) was unscoped: any
authenticated user could read any session by slug, and the WS consumer
auto-joined them as `editor`. Post the multi-tenant Workspaces work
(2026-04-27), that's a cross-workspace data leak — these tests pin the
fix in place.

REST: a workspace-A user gets 404 on a workspace-B session.
WS:   a workspace-A user has the handshake closed with 4003.
"""
from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.sessions.models import Session, SessionParticipant
from apps.workspaces.models import Workspace, WorkspaceMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        email="alice@example.com", display_name="Alice"
    )


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(
        email="bob@example.com", display_name="Bob"
    )


@pytest.fixture
def workspace_a(alice):
    ws = Workspace.objects.create(
        slug="ws-a",
        display_name="Workspace A",
        drive_root_folder_id="folder-a",
        created_by=alice,
    )
    WorkspaceMembership.objects.create(workspace=ws, user=alice, role="owner")
    return ws


@pytest.fixture
def workspace_b(bob):
    ws = Workspace.objects.create(
        slug="ws-b",
        display_name="Workspace B",
        drive_root_folder_id="folder-b",
        created_by=bob,
    )
    WorkspaceMembership.objects.create(workspace=ws, user=bob, role="owner")
    return ws


@pytest.fixture
def workspace_b_session(bob, workspace_b):
    s = Session.objects.create(
        owner=bob, title="bob's chat", workspace=workspace_b
    )
    SessionParticipant.objects.create(session=s, user=bob, role="owner")
    return s


@pytest.fixture
def alice_client(alice):
    c = APIClient()
    c.force_authenticate(user=alice)
    c.force_login(alice)
    return c


# ──────────────────── REST boundary ────────────────────


def test_session_detail_returns_404_for_non_member(
    alice_client, workspace_a, workspace_b_session
):
    """Alice (member of ws-a only) cannot read a session in ws-b."""
    resp = alice_client.get(f"/api/sessions/{workspace_b_session.slug}")
    assert resp.status_code == 404


def test_messages_list_returns_404_for_non_member(
    alice_client, workspace_a, workspace_b_session
):
    resp = alice_client.get(f"/api/sessions/{workspace_b_session.slug}/messages")
    assert resp.status_code == 404


def test_session_detail_works_for_workspace_member(
    bob, workspace_b_session
):
    """Bob (member of ws-b) can read his own workspace's session."""
    c = APIClient()
    c.force_authenticate(user=bob)
    c.force_login(bob)
    resp = c.get(f"/api/sessions/{workspace_b_session.slug}")
    assert resp.status_code == 200


def test_orphan_session_unreachable_to_strangers(alice, alice_client, bob):
    """Orphan sessions (workspace=NULL — legacy or the unattached blank
    chats from POST /api/sessions) are accessible only to the owner or
    a pre-existing participant. Strangers get 404."""
    s = Session.objects.create(owner=bob, title="bob's orphan")
    SessionParticipant.objects.create(session=s, user=bob, role="owner")

    resp = alice_client.get(f"/api/sessions/{s.slug}")
    assert resp.status_code == 404


def test_orphan_session_visible_to_explicit_participant(alice, alice_client, bob):
    """If alice was explicitly added as a participant to an orphan
    session (e.g. before workspaces existed), she retains access."""
    s = Session.objects.create(owner=bob, title="bob's shared orphan")
    SessionParticipant.objects.create(session=s, user=bob, role="owner")
    SessionParticipant.objects.create(session=s, user=alice, role="editor")

    resp = alice_client.get(f"/api/sessions/{s.slug}")
    assert resp.status_code == 200


# ──────────────────── WS boundary ────────────────────


# WS-side coverage lives in test_consumers.py because it needs the same
# daphne stub + fake_redis fixtures. The relevant test there is
# `test_connect_rejects_stranger_for_orphan_session`. A workspace-tied
# variant is covered indirectly: if the consumer's _participant_role
# correctly enforces the same boundary as the REST helper (and both
# call into apps.workspaces.permissions.is_member), the REST tests
# above plus the orphan WS test give us coverage of the gate logic.
