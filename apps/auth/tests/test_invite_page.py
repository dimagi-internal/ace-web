"""The invite page: set a password, or use Google / CommCare."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.auth.models import User
from apps.workspaces.models import WorkspaceMembership

from .conftest import invite

pytestmark = pytest.mark.django_db

PW = "invitee-chosen-passphrase-8"


def test_anonymous_invite_link_lands_on_the_choice_page(client, workspace):
    inv = invite(workspace, "anne@sparkmicrogrants.org")
    resp = client.get(f"/invite/{inv.token}")
    assert resp.status_code == 302 and resp.url == f"/auth/invite/{inv.token}/"


def test_signed_in_invitee_gets_the_spa_accept_page(client, workspace):
    inv = invite(workspace, "anne@sparkmicrogrants.org")
    client.force_login(User.objects.create_user(email="anne@sparkmicrogrants.org"))
    resp = client.get(f"/invite/{inv.token}")
    assert resp.status_code == 200
    assert client.get(f"/auth/invite/{inv.token}/").url == f"/invite/{inv.token}"


def test_page_offers_password_google_and_commcare(client, workspace, google_cfg):
    inv = invite(workspace, "anne@sparkmicrogrants.org")
    body = client.get(f"/auth/invite/{inv.token}/").content.decode()
    assert "Set password and join" in body
    assert "Google" in body and "CommCare" in body
    assert "You don't need a CommCare account" in body
    assert "anne@sparkmicrogrants.org" in body


def test_google_option_hidden_until_configured(client, workspace):
    inv = invite(workspace, "anne@sparkmicrogrants.org")
    body = client.get(f"/auth/invite/{inv.token}/").content.decode()
    assert "auth/google/initiate" not in body


def test_set_password_creates_account_membership_and_session(client, workspace, restricted):
    inv = invite(workspace, "Anne@SparkMicrogrants.org", role="editor")
    resp = client.post(f"/auth/invite/{inv.token}/", {"password1": PW, "password2": PW})
    assert resp.status_code == 302 and resp.url == "/w/spark/opps"
    user = User.objects.get(email="anne@sparkmicrogrants.org")
    assert user.check_password(PW)
    assert WorkspaceMembership.objects.get(workspace=workspace, user=user).role == "editor"
    inv.refresh_from_db()
    assert inv.accepted_at is not None
    assert client.session["_auth_user_id"] == str(user.pk)
    assert client.session["ace_login_method"] == "invite-password"


def test_the_invite_is_used_up(client, workspace):
    inv = invite(workspace, "anne@sparkmicrogrants.org")
    client.post(f"/auth/invite/{inv.token}/", {"password1": PW, "password2": PW})
    client.logout()
    again = client.post(
        f"/auth/invite/{inv.token}/", {"password1": "x" * 15, "password2": "x" * 15}
    )
    assert again.status_code == 410
    assert User.objects.get(email="anne@sparkmicrogrants.org").check_password(PW)


@pytest.mark.parametrize("make", [
    lambda ws: invite(ws, "a@x.org", expires_at=timezone.now() - timedelta(days=1)),
    lambda ws: invite(ws, "a@x.org", revoked_at=timezone.now()),
    lambda ws: invite(ws, "a@x.org", accepted_at=timezone.now()),
], ids=["expired", "revoked", "accepted"])
def test_dead_invites_are_gone(client, workspace, make):
    inv = make(workspace)
    assert client.get(f"/auth/invite/{inv.token}/").status_code == 410
    r = client.post(f"/auth/invite/{inv.token}/", {"password1": PW, "password2": PW})
    assert r.status_code == 410
    assert not User.objects.filter(email="a@x.org").exists()


def test_unknown_token_is_gone(client):
    assert client.get("/auth/invite/nope/").status_code == 410


@pytest.mark.parametrize("p1,p2", [
    ("short", "short"),
    ("1234567890123", "1234567890123"),
    ("anne@sparkmicrogrants.org", "anne@sparkmicrogrants.org"),
    (PW, PW + "x"),
], ids=["short", "numeric", "similar-to-email", "mismatch"])
def test_bad_passwords_create_nothing(client, workspace, p1, p2):
    inv = invite(workspace, "anne@sparkmicrogrants.org")
    r = client.post(f"/auth/invite/{inv.token}/", {"password1": p1, "password2": p2})
    assert r.status_code == 200 and r.context["form"].errors
    assert not User.objects.filter(email="anne@sparkmicrogrants.org").exists()
    inv.refresh_from_db()
    assert inv.accepted_at is None


def test_an_invite_link_cannot_reset_an_existing_accounts_password(client, workspace):
    """Whoever holds the link must not be able to take over a user that already exists."""
    victim = User.objects.create_user(email="anne@sparkmicrogrants.org")
    victim.set_password("victims-own-passphrase-1")
    victim.save()
    inv = invite(workspace, "anne@sparkmicrogrants.org")
    page = client.get(f"/auth/invite/{inv.token}/")
    assert page.context["form"] is None and page.context["existing_account"]
    client.post(f"/auth/invite/{inv.token}/", {"password1": PW, "password2": PW})
    victim.refresh_from_db()
    assert victim.check_password("victims-own-passphrase-1")
    assert "_auth_user_id" not in client.session
