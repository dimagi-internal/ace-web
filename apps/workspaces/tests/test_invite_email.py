"""Invite emails: sent on invite and on resend, never blocking the invite."""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone

from apps.workspaces.models import Workspace, WorkspaceInvite, WorkspaceMembership

User = get_user_model()


@pytest.fixture
def email_on(settings):
    settings.ACE_EMAIL_ENABLED = True
    settings.ACE_PUBLIC_BASE_URL = "https://labs.example.com/ace"
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


@pytest.fixture
def ws(db):
    owner = User.objects.create_user(email="owner@example.com", display_name="Olive Owner")
    workspace = Workspace.objects.create(
        slug="spark", display_name="Spark Microgrants",
        drive_root_folder_id="folder-abc", created_by=owner,
    )
    WorkspaceMembership.objects.create(workspace=workspace, user=owner, role="owner")
    return workspace, owner


def _as(client, user):
    client.force_login(user)
    return client


def _invite(client, ws, email="new@partner.org", role="editor"):
    return client.post(
        f"/api/workspaces/{ws.slug}/members/invite",
        data={"email": email, "role": role}, content_type="application/json",
    )


def test_inviting_emails_the_accept_link(client, ws, email_on):
    workspace, owner = ws
    resp = _invite(_as(client, owner), workspace)

    assert resp.status_code == 201
    body = resp.json()
    assert body["email_sent"] is True
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["new@partner.org"]
    assert msg.reply_to == ["owner@example.com"]
    assert "Spark Microgrants" in msg.subject
    assert f"https://labs.example.com/ace/invite/{body['token']}/" in msg.body


def test_invite_still_succeeds_when_email_is_off(client, ws, settings):
    settings.ACE_EMAIL_ENABLED = False
    workspace, owner = ws
    resp = _invite(_as(client, owner), workspace)

    assert resp.status_code == 201
    assert resp.json()["email_sent"] is False
    assert mail.outbox == []
    assert WorkspaceInvite.objects.filter(email="new@partner.org").exists()


def test_a_failing_send_does_not_fail_the_invite(client, ws, email_on, monkeypatch):
    def boom(self, fail_silently=False):
        raise RuntimeError("SES said no")

    monkeypatch.setattr("django.core.mail.EmailMessage.send", boom)
    workspace, owner = ws
    resp = _invite(_as(client, owner), workspace)

    assert resp.status_code == 201
    assert resp.json()["email_sent"] is False


def _pending(workspace, owner, role="editor", **kw):
    return WorkspaceInvite.objects.create(
        workspace=workspace, email="later@partner.org", role=role, invited_by=owner,
        expires_at=kw.pop("expires_at", timezone.now() + timedelta(days=2)), **kw,
    )


def test_resend_emails_the_same_link_and_extends_expiry(client, ws, email_on):
    workspace, owner = ws
    invite = _pending(workspace, owner)
    token = invite.token

    resp = _as(client, owner).post(f"/api/workspaces/spark/invites/{invite.id}/resend")

    assert resp.status_code == 200
    assert resp.json()["email_sent"] is True
    invite.refresh_from_db()
    assert invite.token == token
    assert invite.expires_at > timezone.now() + timedelta(days=13)
    assert len(mail.outbox) == 1
    assert f"/invite/{token}/" in mail.outbox[0].body


def test_resend_revives_an_expired_invite(client, ws, email_on):
    workspace, owner = ws
    invite = _pending(workspace, owner, expires_at=timezone.now() - timedelta(days=1))

    resp = _as(client, owner).post(f"/api/workspaces/spark/invites/{invite.id}/resend")

    assert resp.status_code == 200
    invite.refresh_from_db()
    assert invite.is_pending()


@pytest.mark.parametrize("field", ["accepted_at", "revoked_at"])
def test_resend_refuses_a_used_invite(client, ws, email_on, field):
    workspace, owner = ws
    invite = _pending(workspace, owner, **{field: timezone.now()})

    resp = _as(client, owner).post(f"/api/workspaces/spark/invites/{invite.id}/resend")

    assert resp.status_code == 404
    assert mail.outbox == []


def test_editors_cannot_resend(client, ws, email_on):
    workspace, owner = ws
    editor = User.objects.create_user(email="ed@example.com")
    WorkspaceMembership.objects.create(workspace=workspace, user=editor, role="editor")
    invite = _pending(workspace, owner)

    resp = _as(client, editor).post(f"/api/workspaces/spark/invites/{invite.id}/resend")

    assert resp.status_code == 403
    assert mail.outbox == []


def test_an_admin_cannot_resend_an_admin_invite(client, ws, email_on):
    workspace, owner = ws
    admin = User.objects.create_user(email="ad@example.com")
    WorkspaceMembership.objects.create(workspace=workspace, user=admin, role="admin")
    invite = _pending(workspace, owner, role="admin")

    resp = _as(client, admin).post(f"/api/workspaces/spark/invites/{invite.id}/resend")

    assert resp.status_code == 403


def test_pending_invites_carry_their_id(client, ws):
    workspace, owner = ws
    invite = _pending(workspace, owner)

    rows = _as(client, owner).get("/api/workspaces/spark/invites").json()

    assert [r["id"] for r in rows] == [invite.id]
