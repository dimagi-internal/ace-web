"""canopy-web's workspace ACL in ace-web: owner > admin > editor > viewer.

Every capability boundary the API enforces, end to end through the HTTP
surface (owner decision, 2026-10-07: "lets use the same acl as canopy, owner,
admin, editor, viewer"). The table under test is
`apps/workspaces/permissions.MINIMUM_ROLE`.
"""
from __future__ import annotations

import importlib
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.workspaces import permissions as perms
from apps.workspaces.models import Workspace, WorkspaceInvite, WorkspaceMembership

User = get_user_model()

ROLES = ["owner", "admin", "editor", "viewer"]


@pytest.fixture
def ws(db):
    founder = User.objects.create_user(email="founder@example.com")
    w = Workspace.objects.create(
        slug="acl-ws", display_name="ACL", drive_root_folder_id="folder-acl", created_by=founder,
    )
    WorkspaceMembership.objects.create(workspace=w, user=founder, role="owner")
    return w


def _member(ws, role, email=None):
    u = User.objects.create_user(email=email or f"{role}-{User.objects.count()}@example.com")
    WorkspaceMembership.objects.create(workspace=ws, user=u, role=role)
    return u


def _as(client, user):
    client.force_login(user)
    return client


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------


def test_role_ladder_matches_canopy():
    assert WorkspaceMembership.ROLE_RANK == {"viewer": 0, "editor": 1, "admin": 2, "owner": 3}
    assert [r for r, _ in WorkspaceMembership.ROLE_CHOICES] == ROLES
    assert perms.ROLES == tuple(ROLES)


@pytest.mark.parametrize("capability,minimum", [
    (perms.READ, "viewer"),
    (perms.CONTENT_WRITE, "editor"),
    (perms.DECISIONS_WRITE, "editor"),
    (perms.SUMMARY_TEAM_VIEW, "admin"),
    (perms.LOGS_READ, "admin"),
    (perms.MEMBERS_MANAGE, "admin"),
    (perms.OWN, "owner"),
])
def test_each_capability_starts_at_its_minimum_role(capability, minimum):
    assert perms.MINIMUM_ROLE[capability] == minimum
    for role in ROLES:
        expected = WorkspaceMembership.ROLE_RANK[role] >= WorkspaceMembership.ROLE_RANK[minimum]
        assert perms.role_allows(role, capability) is expected, role
    assert perms.role_allows(None, capability) is False


def test_an_unknown_capability_raises_rather_than_reading_as_no():
    with pytest.raises(KeyError):
        perms.role_allows("owner", "decisions.wrte")


@pytest.mark.parametrize("actor,target,new,ok", [
    ("owner", "owner", "editor", True),
    ("owner", None, "owner", True),
    ("admin", None, "editor", True),
    ("admin", None, "viewer", True),
    ("admin", None, "admin", False),
    ("admin", None, "owner", False),
    ("admin", "editor", "viewer", True),
    ("admin", "viewer", "editor", True),
    ("admin", "viewer", "admin", False),
    ("admin", "admin", "editor", False),
    ("admin", "owner", None, False),
    ("admin", "editor", None, True),
    ("editor", None, "viewer", False),
    ("viewer", None, "viewer", False),
])
def test_may_manage_member_only_strictly_below_yourself(actor, target, new, ok):
    assert perms.may_manage_member(actor, target, new) is ok


# ---------------------------------------------------------------------------
# Members: invite / change / remove / list invites
# ---------------------------------------------------------------------------


def _invite(client, ws, email, role):
    return client.post(
        f"/api/workspaces/{ws.slug}/members/invite", {"email": email, "role": role},
        content_type="application/json",
    )


@pytest.mark.django_db
@pytest.mark.parametrize("role,status", [
    ("editor", 201), ("viewer", 201), ("admin", 403), ("owner", 403),
])
def test_an_admin_invites_below_itself_only(client, ws, role, status):
    admin = _member(ws, "admin")
    resp = _invite(_as(client, admin), ws, f"new-{role}@example.com", role)
    assert resp.status_code == status
    if status == 201:
        assert WorkspaceInvite.objects.get(email=f"new-{role}@example.com").role == role


@pytest.mark.django_db
@pytest.mark.parametrize("role", ROLES)
def test_an_owner_invites_at_any_role(client, ws, role):
    owner = _member(ws, "owner")
    assert _invite(_as(client, owner), ws, f"o-{role}@example.com", role).status_code == 201


@pytest.mark.django_db
@pytest.mark.parametrize("actor", ["editor", "viewer"])
def test_editors_and_viewers_cannot_invite(client, ws, actor):
    user = _member(ws, actor)
    assert _invite(_as(client, user), ws, "x@example.com", "viewer").status_code == 403


@pytest.mark.django_db
def test_invite_rejects_an_unknown_role(client, ws):
    owner = _member(ws, "owner")
    resp = _invite(_as(client, owner), ws, "x@example.com", "superuser")
    assert resp.status_code in (400, 422)


def _set_role(client, ws, user, role):
    return client.patch(
        f"/api/workspaces/{ws.slug}/members/{user.id}", {"role": role},
        content_type="application/json",
    )


@pytest.mark.django_db
def test_an_admin_changes_roles_below_itself_only(client, ws):
    admin = _member(ws, "admin")
    editor = _member(ws, "editor")
    other_admin = _member(ws, "admin")
    owner = User.objects.get(email="founder@example.com")
    c = _as(client, admin)
    assert _set_role(c, ws, editor, "viewer").status_code == 200
    assert _set_role(c, ws, editor, "editor").status_code == 200
    assert _set_role(c, ws, editor, "admin").status_code == 403  # can't mint an admin
    assert _set_role(c, ws, other_admin, "editor").status_code == 403  # can't touch an admin
    assert _set_role(c, ws, owner, "editor").status_code == 403
    assert WorkspaceMembership.objects.get(workspace=ws, user=other_admin).role == "admin"


@pytest.mark.django_db
def test_an_owner_can_make_an_admin(client, ws):
    owner = User.objects.get(email="founder@example.com")
    editor = _member(ws, "editor")
    assert _set_role(_as(client, owner), ws, editor, "admin").status_code == 200
    assert WorkspaceMembership.objects.get(workspace=ws, user=editor).role == "admin"


@pytest.mark.django_db
def test_the_last_owner_cannot_be_demoted(client, ws):
    owner = User.objects.get(email="founder@example.com")
    assert _set_role(_as(client, owner), ws, owner, "admin").status_code == 400


@pytest.mark.django_db
def test_an_admin_removes_below_itself_only(client, ws):
    admin = _member(ws, "admin")
    viewer = _member(ws, "viewer")
    other_admin = _member(ws, "admin")
    c = _as(client, admin)
    assert c.delete(f"/api/workspaces/{ws.slug}/members/{viewer.id}").status_code == 204
    assert c.delete(f"/api/workspaces/{ws.slug}/members/{other_admin.id}").status_code == 403


@pytest.mark.django_db
def test_an_editor_cannot_remove_anyone(client, ws):
    editor = _member(ws, "editor")
    viewer = _member(ws, "viewer")
    resp = _as(client, editor).delete(f"/api/workspaces/{ws.slug}/members/{viewer.id}")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_pending_invites_are_listed_to_admins_without_tokens(client, ws):
    founder = User.objects.get(email="founder@example.com")
    now = timezone.now()
    WorkspaceInvite.objects.create(workspace=ws, email="p@x.org", role="editor",
                                   invited_by=founder, expires_at=now + timedelta(days=3))
    WorkspaceInvite.objects.create(workspace=ws, email="done@x.org", role="editor",
                                   invited_by=founder, expires_at=now + timedelta(days=3),
                                   accepted_at=now)
    WorkspaceInvite.objects.create(workspace=ws, email="old@x.org", role="editor",
                                   invited_by=founder, expires_at=now - timedelta(days=1))
    admin = _member(ws, "admin")
    resp = _as(client, admin).get(f"/api/workspaces/{ws.slug}/invites")
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["email"] for r in rows] == ["p@x.org"]
    assert rows[0]["role"] == "editor" and "token" not in rows[0]
    editor = _member(ws, "editor")
    assert _as(client, editor).get(f"/api/workspaces/{ws.slug}/invites").status_code == 403


@pytest.mark.django_db
def test_accepting_an_invite_never_demotes(client, ws):
    founder = User.objects.get(email="founder@example.com")
    editor = _member(ws, "editor", email="ed@example.com")
    low = WorkspaceInvite.objects.create(workspace=ws, email="ed@example.com", role="viewer",
                                         invited_by=founder,
                                         expires_at=timezone.now() + timedelta(days=3))
    assert _as(client, editor).post(f"/api/invites/{low.token}/accept").json()["role"] == "editor"
    high = WorkspaceInvite.objects.create(workspace=ws, email="ed@example.com", role="admin",
                                          invited_by=founder,
                                          expires_at=timezone.now() + timedelta(days=3))
    assert client.post(f"/api/invites/{high.token}/accept").json()["role"] == "admin"
    assert WorkspaceMembership.objects.get(workspace=ws, user=editor).role == "admin"


# ---------------------------------------------------------------------------
# Audit log, workspace settings
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("role,status", [
    ("owner", 200), ("admin", 200), ("editor", 403), ("viewer", 403),
])
def test_the_audit_log_is_admin_and_above(client, ws, role, status):
    user = _member(ws, role)
    assert _as(client, user).get(f"/api/workspaces/{ws.slug}/activity").status_code == status


@pytest.mark.django_db
@pytest.mark.parametrize("role,status", [
    ("owner", 200), ("admin", 403), ("editor", 403), ("viewer", 403),
])
def test_workspace_settings_stay_owner_only(client, ws, role, status):
    user = _member(ws, role)
    resp = _as(client, user).patch(
        f"/api/workspaces/{ws.slug}", {"name": "Renamed"}, content_type="application/json",
    )
    assert resp.status_code == status


@pytest.mark.django_db
def test_workspace_detail_reports_the_admin_role(client, ws):
    admin = _member(ws, "admin")
    assert _as(client, admin).get(f"/api/workspaces/{ws.slug}").json()["role"] == "admin"


# ---------------------------------------------------------------------------
# Content writes: viewer is read-only
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("role,blocked", [
    ("viewer", True), ("editor", False), ("admin", False), ("owner", False),
])
def test_workbench_decision_overrides_need_decisions_write(
    client, ws, role, blocked, monkeypatch,
):
    """The Workbench's decision editor writes the same store as the run
    summary, so it takes the same capability. A viewer gets 403 with the role
    copy; an editor and above reach the write."""
    monkeypatch.setattr("apps.opps.api.save_decision_overrides_and_return",
                        lambda workspace, slug, body: {"saved": True})
    user = _member(ws, role)
    resp = _as(client, user).post(
        f"/api/w/{ws.slug}/opps/some-opp/decision-overrides",
        {"source_run_id": "20260101-0000"},
        content_type="application/json",
    )
    if blocked:
        assert resp.status_code == 403
        assert resp.json()["detail"] == (
            "Your role in this workspace can view but not change decisions.")
    else:
        assert resp.status_code == 200 and resp.json() == {"saved": True}


@pytest.mark.django_db
@pytest.mark.parametrize("role,blocked", [("viewer", True), ("editor", False)])
def test_creating_an_opp_needs_content_write(client, ws, role, blocked, monkeypatch):
    reached = []
    monkeypatch.setattr("apps.opps.api.create_opp_and_return_card",
                        lambda *a, **kw: reached.append(1) or (_ for _ in ()).throw(
                            RuntimeError("stop after the gate")))
    user = _member(ws, role)
    c = _as(client, user)
    c.raise_request_exception = False
    resp = c.post(
        f"/api/w/{ws.slug}/opps", {"title": "New", "slug": "new-opp"},
        content_type="application/json",
    )
    assert (resp.status_code == 403) is blocked
    assert bool(reached) is not blocked


# ---------------------------------------------------------------------------
# Migration 0012: viewers become editors
# ---------------------------------------------------------------------------

_mig = importlib.import_module("apps.workspaces.migrations.0012_viewers_become_editors")


class _AppShim:
    def get_model(self, app_label, name):
        from django.apps import apps as django_apps
        return django_apps.get_model(app_label, name)


@pytest.mark.django_db
def test_migration_turns_viewer_memberships_and_pending_invites_into_editors(ws):
    founder = User.objects.get(email="founder@example.com")
    viewer = _member(ws, "viewer")
    editor = _member(ws, "editor")
    now = timezone.now()

    def inv(email, **kw):
        return WorkspaceInvite.objects.create(
            workspace=ws, email=email, role="viewer", invited_by=founder,
            expires_at=kw.pop("expires_at", now + timedelta(days=3)), **kw)

    pending = inv("pending@x.org")
    lapsed = inv("lapsed@x.org", expires_at=now - timedelta(days=1))
    accepted = inv("accepted@x.org", accepted_at=now)
    revoked = inv("revoked@x.org", revoked_at=now)
    probe_ws = Workspace.objects.create(slug="canopy-probe", display_name="probe",
                                        drive_root_folder_id="", created_by=founder)
    probe = _member(probe_ws, "viewer", email="canopy-probe@probe.invalid")

    _mig.viewers_to_editors(_AppShim(), schema_editor=None)

    def role(u, w=ws):
        return WorkspaceMembership.objects.get(workspace=w, user=u).role

    assert role(viewer) == "editor"
    assert role(editor) == "editor"
    assert role(founder) == "owner"
    assert role(probe, probe_ws) == "viewer"  # least privilege, by design
    for i, expected in ((pending, "editor"), (lapsed, "editor"),
                        (accepted, "viewer"), (revoked, "viewer")):
        i.refresh_from_db()
        assert i.role == expected, i.email
    assert not WorkspaceMembership.objects.filter(role="viewer").exclude(
        workspace=probe_ws).exists()

    # Idempotent.
    _mig.viewers_to_editors(_AppShim(), schema_editor=None)
    assert role(viewer) == "editor"
