"""Every change to who is in a workspace lands in its activity feed, and a
pending invite can be revoked.

Membership decides what a person may see and do, so an admin reading the
feed must be able to answer "who let them in, as what, and who took them
out" — for every way that happens: invite, resend, revoke, accept, role
change, removal, leaving.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.workspaces.models import (
    MembershipChange,
    Workspace,
    WorkspaceInvite,
    WorkspaceMembership,
)

User = get_user_model()


@pytest.fixture
def ws(db):
    founder = User.objects.create_user(email="founder@example.com")
    w = Workspace.objects.create(
        slug="audit-ws", display_name="Audit", drive_root_folder_id="folder-audit",
        created_by=founder,
    )
    WorkspaceMembership.objects.create(workspace=w, user=founder, role="owner")
    return w


@pytest.fixture
def owner(ws):
    return User.objects.get(email="founder@example.com")


def _member(ws, role, email):
    u = User.objects.create_user(email=email)
    WorkspaceMembership.objects.create(workspace=ws, user=u, role=role)
    return u


def _invite_row(ws, email, role, by):
    return WorkspaceInvite.objects.create(
        workspace=ws, email=email, role=role, invited_by=by,
        expires_at=timezone.now() + timedelta(days=3),
    )


def _changes(ws):
    return [
        (c.action, c.email, c.actor.email if c.actor else None, c.before_role, c.after_role)
        for c in MembershipChange.objects.filter(workspace=ws).order_by("id")
    ]


def test_an_invite_is_recorded_with_who_sent_it(client, ws, owner):
    client.force_login(owner)
    resp = client.post(f"/api/workspaces/{ws.slug}/members/invite",
                       {"email": "new@example.com", "role": "editor"},
                       content_type="application/json")
    assert resp.status_code == 201
    assert _changes(ws) == [
        ("invite.sent", "new@example.com", "founder@example.com", "", "editor")]


def test_a_resend_is_recorded(client, ws, owner):
    invite = _invite_row(ws, "new@example.com", "viewer", owner)
    client.force_login(owner)
    assert client.post(
        f"/api/workspaces/{ws.slug}/invites/{invite.id}/resend").status_code == 200
    assert _changes(ws) == [
        ("invite.resent", "new@example.com", "founder@example.com", "", "viewer")]


def test_accepting_records_the_role_granted(client, ws, owner):
    invite = _invite_row(ws, "joiner@example.com", "editor", owner)
    joiner = User.objects.create_user(email="joiner@example.com")
    client.force_login(joiner)
    assert client.post(f"/api/invites/{invite.token}/accept").status_code == 200
    assert _changes(ws) == [
        ("invite.accepted", "joiner@example.com", "joiner@example.com", "", "editor")]


def test_accepting_as_an_existing_member_records_the_upgrade(client, ws, owner):
    member = _member(ws, "viewer", "m@example.com")
    invite = _invite_row(ws, "m@example.com", "editor", owner)
    client.force_login(member)
    assert client.post(f"/api/invites/{invite.token}/accept").status_code == 200
    assert _changes(ws) == [
        ("invite.accepted", "m@example.com", "m@example.com", "viewer", "editor")]


def test_a_role_change_records_before_and_after(client, ws, owner):
    member = _member(ws, "viewer", "m@example.com")
    client.force_login(owner)
    assert client.patch(f"/api/workspaces/{ws.slug}/members/{member.id}", {"role": "admin"},
                        content_type="application/json").status_code == 200
    assert _changes(ws) == [
        ("member.role_changed", "m@example.com", "founder@example.com", "viewer", "admin")]


def test_setting_the_same_role_records_nothing(client, ws, owner):
    member = _member(ws, "editor", "m@example.com")
    client.force_login(owner)
    client.patch(f"/api/workspaces/{ws.slug}/members/{member.id}", {"role": "editor"},
                 content_type="application/json")
    assert _changes(ws) == []


def test_a_removal_is_recorded(client, ws, owner):
    member = _member(ws, "editor", "m@example.com")
    client.force_login(owner)
    assert client.delete(f"/api/workspaces/{ws.slug}/members/{member.id}").status_code == 204
    assert _changes(ws) == [
        ("member.removed", "m@example.com", "founder@example.com", "editor", "")]


def test_leaving_is_recorded(client, ws):
    member = _member(ws, "editor", "m@example.com")
    client.force_login(member)
    assert client.post(f"/api/workspaces/{ws.slug}/leave").status_code == 204
    assert _changes(ws) == [("member.left", "m@example.com", "m@example.com", "editor", "")]


def test_a_refused_change_records_nothing(client, ws):
    admin = _member(ws, "admin", "a@example.com")
    other_admin = _member(ws, "admin", "b@example.com")
    client.force_login(admin)
    assert client.delete(
        f"/api/workspaces/{ws.slug}/members/{other_admin.id}").status_code == 403
    assert _changes(ws) == []


# ---------------------------------------------------------------------------
# Revoking a pending invite
# ---------------------------------------------------------------------------


def test_a_revoked_invite_link_stops_working(client, ws, owner):
    invite = _invite_row(ws, "new@example.com", "editor", owner)
    client.force_login(owner)
    assert client.delete(f"/api/workspaces/{ws.slug}/invites/{invite.id}").status_code == 204
    invite.refresh_from_db()
    assert invite.revoked_at is not None
    assert client.get(f"/api/workspaces/{ws.slug}/invites").json() == []
    assert client.get(f"/api/invites/{invite.token}").status_code == 410
    assert _changes(ws) == [
        ("invite.revoked", "new@example.com", "founder@example.com", "editor", "")]


def test_an_admin_cannot_revoke_an_invite_at_its_own_level(client, ws, owner):
    invite = _invite_row(ws, "peer@example.com", "admin", owner)
    admin = _member(ws, "admin", "a@example.com")
    client.force_login(admin)
    assert client.delete(f"/api/workspaces/{ws.slug}/invites/{invite.id}").status_code == 403
    invite.refresh_from_db()
    assert invite.revoked_at is None


def test_an_editor_cannot_revoke(client, ws, owner):
    invite = _invite_row(ws, "new@example.com", "viewer", owner)
    editor = _member(ws, "editor", "e@example.com")
    client.force_login(editor)
    assert client.delete(f"/api/workspaces/{ws.slug}/invites/{invite.id}").status_code == 403


def test_an_accepted_invite_cannot_be_revoked(client, ws, owner):
    invite = _invite_row(ws, "new@example.com", "viewer", owner)
    invite.accepted_at = timezone.now()
    invite.save()
    client.force_login(owner)
    assert client.delete(f"/api/workspaces/{ws.slug}/invites/{invite.id}").status_code == 404


def test_another_workspace_s_invite_is_not_found(client, ws, owner):
    other = Workspace.objects.create(slug="other-ws", display_name="Other",
                                     drive_root_folder_id="folder-other", created_by=owner)
    invite = _invite_row(other, "new@example.com", "viewer", owner)
    client.force_login(owner)
    assert client.delete(f"/api/workspaces/{ws.slug}/invites/{invite.id}").status_code == 404


# ---------------------------------------------------------------------------
# The feed
# ---------------------------------------------------------------------------


def test_the_activity_feed_shows_membership_changes_to_admins(client, ws, owner):
    member = _member(ws, "viewer", "m@example.com")
    client.force_login(owner)
    client.patch(f"/api/workspaces/{ws.slug}/members/{member.id}", {"role": "editor"},
                 content_type="application/json")
    items = client.get(f"/api/workspaces/{ws.slug}/activity").json()["items"]
    row = next(i for i in items if i["action"] == "member.role_changed")
    assert row["subject"] == "m@example.com"
    assert row["context"]["changed_by"] == "founder@example.com"
    assert (row["context"]["before"], row["context"]["after"]) == ("viewer", "editor")


def test_editors_cannot_read_the_feed(client, ws):
    editor = _member(ws, "editor", "e@example.com")
    client.force_login(editor)
    assert client.get(f"/api/workspaces/{ws.slug}/activity").status_code == 403
