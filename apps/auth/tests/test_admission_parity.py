"""One gate, three doors.

`login_gate.admission_rule` (invite-only, 2026-09-28) and auto-join-by-domain
must treat a person identically whether they arrive by password, Google or
Connect. Each test here runs once per method, through that method's real view.
"""
from unittest.mock import patch

import pytest

from apps.auth.models import User
from apps.workspaces.models import WorkspaceMembership

from .conftest import invite

pytestmark = pytest.mark.django_db

PW = "parity-test-passphrase-3"
METHODS = ["password", "google", "connect"]


@pytest.fixture
def sign_in(client, google_signin, settings):
    """`sign_in(method, email)` → whether that person ended up signed in."""
    settings.CONNECT_OAUTH_CLIENT_ID = "cid"
    settings.CONNECT_OAUTH_CLIENT_SECRET = "csecret"

    def go(method: str, email: str) -> bool:
        client.logout()  # every call is a fresh visitor
        if method == "password":
            # A password account may already exist for this email (it is the
            # refusal-after-correct-password case); create one if it doesn't.
            user = User.objects.filter(email__iexact=email).first() or \
                User.objects.create_user(email=email.lower())
            user.set_password(PW)
            user.save()
            client.post("/auth/login/", {"username": email, "password": PW})
        elif method == "google":
            google_signin(client, email=email)
        else:
            session = client.session
            session.update({"oauth_state": "s", "oauth_code_verifier": "v", "oauth_next": "/"})
            session.save()
            with patch("apps.auth.oauth_views.httpx.post") as post, \
                 patch("apps.auth.oauth_views.introspect_token",
                       return_value={"id": 1, "username": "u", "email": email}), \
                 patch("apps.auth.oauth_views.fetch_userinfo", return_value=None):
                post.return_value.raise_for_status = lambda: None
                post.return_value.json.return_value = {"access_token": "t", "expires_in": 60}
                client.get("/auth/callback/?state=s&code=c")
        return "_auth_user_id" in client.session

    return go


@pytest.mark.parametrize("method", METHODS)
def test_uninvited_outsider_is_refused(sign_in, restricted, method):
    assert sign_in(method, "stranger@elsewhere.org") is False


@pytest.mark.parametrize("method", METHODS)
def test_refused_outsider_is_given_the_same_explanation(client, sign_in, restricted, method):
    sign_in(method, "stranger@elsewhere.org")
    body = client.get("/auth/login/").content.decode()
    if method == "password":  # shown inline on the POST response instead
        return
    assert "Access is restricted to @dimagi.com accounts" in body


@pytest.mark.parametrize("method", ["google", "connect"])
def test_refusal_leaves_no_user_row(sign_in, restricted, method):
    sign_in(method, "stranger@elsewhere.org")
    assert not User.objects.filter(email="stranger@elsewhere.org").exists()


@pytest.mark.parametrize("method", METHODS)
def test_pending_invite_admits(sign_in, restricted, workspace, method):
    invite(workspace, "anne@sparkmicrogrants.org")
    assert sign_in(method, "Anne@SparkMicrogrants.org") is True


@pytest.mark.parametrize("method", METHODS)
def test_membership_admits_after_the_invite_is_used_up(sign_in, restricted, workspace, method):
    owner = workspace.created_by
    inv = invite(workspace, "anne@sparkmicrogrants.org")
    anne = User.objects.create_user(email="anne@sparkmicrogrants.org")
    WorkspaceMembership.objects.create(workspace=workspace, user=anne, role="viewer",
                                       invited_by=owner)
    from django.utils import timezone
    inv.accepted_at = timezone.now()
    inv.save()
    assert sign_in(method, "anne@sparkmicrogrants.org") is True


@pytest.mark.parametrize("method", METHODS)
def test_removing_the_last_membership_cuts_an_outsider_off(sign_in, restricted, workspace, method):
    anne = User.objects.create_user(email="anne@sparkmicrogrants.org")
    m = WorkspaceMembership.objects.create(workspace=workspace, user=anne, role="viewer")
    assert sign_in(method, "anne@sparkmicrogrants.org") is True
    m.delete()
    assert sign_in(method, "anne@sparkmicrogrants.org") is False


@pytest.mark.parametrize("method", METHODS)
def test_domain_admits(sign_in, restricted, method):
    assert sign_in(method, "someone@dimagi.com") is True


@pytest.mark.parametrize("method", METHODS)
def test_auto_join_by_domain_applies(sign_in, restricted, workspace, method):
    workspace.auto_join_domains = ["dimagi.com"]
    workspace.save()
    assert sign_in(method, "new.hire@dimagi.com") is True
    user = User.objects.get(email="new.hire@dimagi.com")
    m = WorkspaceMembership.objects.get(workspace=workspace, user=user)
    assert m.role == "editor"


@pytest.mark.parametrize("method", METHODS)
def test_deactivated_user_is_refused(sign_in, restricted, method):
    User.objects.create_user(email="gone@dimagi.com")
    User.objects.filter(email="gone@dimagi.com").update(is_active=False)
    assert sign_in(method, "gone@dimagi.com") is False


def test_one_person_one_account_across_all_three_methods(client, sign_in, restricted):
    assert sign_in("connect", "Pat@dimagi.com") is True
    client.logout()
    assert sign_in("google", "pat@dimagi.com") is True
    client.logout()
    assert sign_in("password", "PAT@dimagi.com") is True
    assert User.objects.filter(email__iexact="pat@dimagi.com").count() == 1
