"""Email + password: Django's own views, the shared gate, and the brute-force ceiling."""
import re

import pytest
from django.contrib.auth.hashers import check_password, make_password
from django.core import mail
from django.urls import reverse

from apps.auth.models import User

from .conftest import invite

pytestmark = pytest.mark.django_db

PW = "correct-horse-battery-staple-9"


def make_user(email="pat@dimagi.com", password=PW, **kw):
    u = User.objects.create_user(email=email, display_name="Pat")
    if password:
        u.set_password(password)
    for k, v in kw.items():
        setattr(u, k, v)
    u.save()
    return u


def post_login(client, email="pat@dimagi.com", password=PW, **extra):
    return client.post("/auth/login/", {"username": email, "password": password, **extra})


# --- settings: hashers + validators ----------------------------------------------

def test_argon2_is_first_hasher_and_pbkdf2_still_verifies(settings):
    from config.settings import base

    assert base.PASSWORD_HASHERS[0] == "django.contrib.auth.hashers.Argon2PasswordHasher"
    assert "django.contrib.auth.hashers.PBKDF2PasswordHasher" in base.PASSWORD_HASHERS
    settings.PASSWORD_HASHERS = base.PASSWORD_HASHERS
    assert make_password("x" * 12).startswith("argon2$")
    legacy = make_password("legacy-password-1", hasher="pbkdf2_sha256")
    assert check_password("legacy-password-1", legacy)


def test_old_pbkdf2_hash_signs_in_and_is_upgraded_to_argon2(client, settings):
    from config.settings import base

    settings.PASSWORD_HASHERS = base.PASSWORD_HASHERS
    user = make_user(password=None)
    user.password = make_password(PW, hasher="pbkdf2_sha256")
    user.save()
    assert post_login(client).status_code == 302
    user.refresh_from_db()
    assert user.password.startswith("argon2$")


def test_stock_password_validators_are_configured():
    from config.settings import base

    names = {v["NAME"].rsplit(".", 1)[1] for v in base.AUTH_PASSWORD_VALIDATORS}
    assert names == {
        "UserAttributeSimilarityValidator", "MinimumLengthValidator",
        "CommonPasswordValidator", "NumericPasswordValidator",
    }


# --- sign in ----------------------------------------------------------------------

def test_login_page_offers_all_three_ways(client, google_cfg):
    body = client.get("/auth/login/").content.decode()
    assert "Sign in with email" in body
    assert "Sign in with Google" in body
    assert "Sign in with CommCare" in body


def test_password_sign_in(client):
    user = make_user()
    resp = post_login(client)
    assert resp.status_code == 302 and resp.url == "/"
    assert client.session["_auth_user_id"] == str(user.pk)
    assert client.session["ace_login_method"] == "password"


def test_email_is_case_insensitive(client):
    make_user(email="pat@dimagi.com")
    assert post_login(client, email="  Pat@Dimagi.COM ").status_code == 302


def test_session_key_rotates_on_login(client):
    make_user()
    client.get("/auth/login/")
    before = client.session.session_key
    post_login(client)
    assert client.session.session_key != before


def test_wrong_password_and_unknown_email_look_identical(client):
    make_user()
    wrong = post_login(client, password="nope-nope-nope-1")
    unknown = post_login(client, email="ghost@dimagi.com")
    assert wrong.status_code == unknown.status_code == 200
    assert "_auth_user_id" not in client.session
    err = lambda r: re.sub(r"\s+", " ", " ".join(r.context["form"].non_field_errors()))  # noqa: E731
    assert err(wrong) == err(unknown) != ""


def test_connect_only_account_has_no_password_to_guess(client):
    make_user(password=None)  # unusable password
    assert post_login(client, password="").status_code == 200
    assert post_login(client, password="anything-at-all-1").status_code == 200
    assert "_auth_user_id" not in client.session


def test_inactive_user_cannot_sign_in(client):
    make_user(is_active=False)
    assert post_login(client).status_code == 200
    assert "_auth_user_id" not in client.session


def test_next_honoured_open_redirect_not(client):
    make_user()
    assert post_login(client, next="/w/spark/opps").url == "/w/spark/opps"
    client.logout()
    assert post_login(client, next="https://evil.example/").url == "/"


def test_default_destination_carries_the_script_prefix(client, settings):
    settings.FORCE_SCRIPT_NAME = "/ace"
    make_user()
    assert post_login(client).url == "/ace/"


def test_already_signed_in_visitor_skips_the_form(client):
    client.force_login(make_user())
    assert client.get("/auth/login/?next=/w/x").status_code == 302


# --- the admission gate -----------------------------------------------------------

def test_uninvited_outsider_with_a_password_is_refused(client, restricted):
    make_user(email="stranger@elsewhere.org")
    resp = post_login(client, email="stranger@elsewhere.org")
    assert resp.status_code == 200
    assert "Access is restricted" in resp.content.decode()
    assert "_auth_user_id" not in client.session


def test_invited_and_member_outsiders_are_admitted(client, restricted, workspace):
    from apps.workspaces.models import WorkspaceMembership

    make_user(email="anne@sparkmicrogrants.org")
    invite(workspace, "anne@sparkmicrogrants.org")
    assert post_login(client, email="anne@sparkmicrogrants.org").status_code == 302
    client.logout()

    bob = make_user(email="bob@partner.org")
    WorkspaceMembership.objects.create(workspace=workspace, user=bob, role="viewer")
    assert post_login(client, email="bob@partner.org").status_code == 302


def test_auto_join_by_domain_applies_to_password_logins(client, workspace):
    from apps.workspaces.models import WorkspaceMembership

    workspace.auto_join_domains = ["dimagi.com"]
    workspace.save()
    user = make_user(email="new.hire@dimagi.com")
    post_login(client, email="new.hire@dimagi.com")
    assert WorkspaceMembership.objects.filter(workspace=workspace, user=user).exists()


# --- brute-force ceiling ----------------------------------------------------------

def test_repeated_failures_lock_the_email_even_for_the_right_password(client, settings):
    settings.ACE_LOGIN_RATE_LIMIT_EMAIL = (3, 900)
    make_user()
    for i in range(3):
        # a fresh address each time: only the per-email bucket can be tripping
        post_login(client, password="wrong-wrong-1", HTTP_X_FORWARDED_FOR=f"10.0.0.{i}")
    resp = client.post(
        "/auth/login/", {"username": "pat@dimagi.com", "password": PW},
        HTTP_X_FORWARDED_FOR="10.0.9.9",
    )
    assert resp.status_code == 200 and "Too many attempts" in resp.content.decode()
    assert "_auth_user_id" not in client.session


def test_one_address_spraying_many_emails_is_stopped(client, settings):
    settings.ACE_LOGIN_RATE_LIMIT_IP = (3, 900)
    make_user()
    for i in range(3):
        client.post("/auth/login/", {"username": f"user{i}@dimagi.com", "password": "x"})
    resp = post_login(client)
    assert "Too many attempts" in resp.content.decode()


# --- password reset ---------------------------------------------------------------

@pytest.fixture
def reset_on(settings):
    settings.ACE_PASSWORD_RESET_ENABLED = True


def test_reset_is_off_by_default(client):
    assert client.get("/auth/password/reset/").status_code == 404
    assert client.post("/auth/password/reset/", {"email": "pat@dimagi.com"}).status_code == 404
    assert b"Forgot" not in client.get("/auth/login/").content


def test_reset_link_shown_when_enabled(client, reset_on):
    assert b"Forgot your password?" in client.get("/auth/login/").content


def request_reset(client, email):
    return client.post("/auth/password/reset/", {"email": email})


def test_reset_reveals_nothing_about_who_has_an_account(client, reset_on, restricted):
    make_user()                                            # real, admitted
    make_user(email="connect.only@dimagi.com", password=None)   # no password
    make_user(email="out@elsewhere.org")                   # not admitted
    results = []
    for email in ("pat@dimagi.com", "ghost@dimagi.com", "connect.only@dimagi.com",
                  "out@elsewhere.org"):
        r = request_reset(client, email)
        results.append((r.status_code, r.url))
    assert len(set(results)) == 1                          # same answer for all four
    assert [m.to for m in mail.outbox] == [["pat@dimagi.com"]]


def test_reset_end_to_end(client, reset_on):
    user = make_user()
    request_reset(client, "pat@dimagi.com")
    body = mail.outbox[0].body
    link = re.search(r"https?://\S+/auth/password/reset/\S+/\S+/", body).group(0)
    path = "/" + link.split("/", 3)[3]
    page = client.get(path, follow=True)                   # token -> set-password form
    assert page.status_code == 200
    new = "a-brand-new-passphrase-77"
    done = client.post(page.request["PATH_INFO"], {"new_password1": new, "new_password2": new})
    assert done.status_code == 302
    user.refresh_from_db()
    assert user.check_password(new)
    assert post_login(client, password=new).status_code == 302
    # single use
    assert client.get(path, follow=True).context["validlink"] is False


def test_reset_rejects_weak_passwords(client, reset_on):
    make_user()
    request_reset(client, "pat@dimagi.com")
    link = re.search(r"/auth/password/reset/\S+/\S+/", mail.outbox[0].body).group(0)
    page = client.get(link, follow=True)
    r = client.post(page.request["PATH_INFO"], {"new_password1": "12345678",
                                                "new_password2": "12345678"})
    assert r.status_code == 200 and r.context["form"].errors


def test_reset_requests_are_rate_limited_without_saying_so(client, reset_on, settings):
    settings.ACE_RESET_RATE_LIMIT_EMAIL = (1, 3600)
    make_user()
    first = request_reset(client, "pat@dimagi.com")
    second = request_reset(client, "pat@dimagi.com")
    assert first.url == second.url
    assert len(mail.outbox) == 1


# --- set / change a password --------------------------------------------------------

def test_connect_first_user_can_add_a_password_later(client):
    user = make_user(password=None)
    client.force_login(user)
    new = "added-after-connect-123"
    r = client.post("/auth/password/", {"new_password1": new, "new_password2": new})
    assert r.status_code == 302
    user.refresh_from_db()
    assert user.has_usable_password()
    client.logout()
    assert post_login(client, password=new).status_code == 302          # same User
    assert User.objects.filter(email="pat@dimagi.com").count() == 1


def test_changing_a_password_needs_the_old_one_and_keeps_the_session(client):
    user = make_user()
    client.force_login(user)
    bad = client.post("/auth/password/", {"old_password": "wrong", "new_password1": "x" * 14,
                                          "new_password2": "x" * 14})
    assert bad.status_code == 200
    new = "changed-my-passphrase-42"
    ok = client.post("/auth/password/", {"old_password": PW, "new_password1": new,
                                         "new_password2": new})
    assert ok.status_code == 302
    assert client.get("/auth/account/").status_code == 200            # still signed in


def test_password_and_account_pages_need_sign_in(client):
    assert client.get("/auth/password/").status_code == 302
    assert client.get("/auth/account/").status_code == 302


# --- admin ----------------------------------------------------------------------------

def test_admin_login_goes_through_the_one_login_page(client):
    resp = client.get("/admin/login/")
    assert resp.status_code == 302 and resp.url.startswith(reverse("auth:login"))


def test_admin_login_does_not_loop_for_signed_in_non_staff(client):
    client.force_login(make_user())
    assert client.get("/admin/login/").status_code == 403


def test_admin_creates_a_user_with_a_password(client):
    admin = make_user(email="root@dimagi.com", is_staff=True, is_superuser=True)
    client.force_login(admin)
    pw = "admin-set-passphrase-55"
    r = client.post("/admin/ace_auth/user/add/", {
        "email": "Agent@Dimagi-AI.com", "display_name": "Agent",
        "password1": pw, "password2": pw,
    })
    assert r.status_code == 302, r.context["adminform"].form.errors if r.context else r
    created = User.objects.get(email="agent@dimagi-ai.com")
    assert created.check_password(pw)
    client.logout()
    assert post_login(client, email="agent@dimagi-ai.com", password=pw).status_code == 302
