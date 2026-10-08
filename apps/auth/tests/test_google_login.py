"""Sign in with Google: OIDC code + PKCE, with state, nonce and email_verified checked."""
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from apps.auth.models import User

from .conftest import GOOGLE_CLIENT_ID, invite

pytestmark = pytest.mark.django_db


# --- configuration: hidden until set ------------------------------------------

def test_button_hidden_and_routes_404_when_unconfigured(client, settings):
    settings.GOOGLE_OAUTH_CLIENT_ID = ""
    settings.GOOGLE_OAUTH_CLIENT_SECRET = ""
    assert b"Sign in with Google" not in client.get("/auth/login/").content
    assert client.get("/auth/google/initiate/").status_code == 404
    assert client.get("/auth/google/callback/?state=x&code=y").status_code == 404


def test_button_needs_both_id_and_secret(client, settings):
    settings.GOOGLE_OAUTH_CLIENT_ID = "id"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = ""
    assert b"Sign in with Google" not in client.get("/auth/login/").content


def test_button_shown_when_configured(client, google_cfg):
    assert b"Sign in with Google" in client.get("/auth/login/").content


# --- initiate -----------------------------------------------------------------

def test_initiate_builds_pkce_state_nonce_request(client, google_cfg):
    resp = client.get("/auth/google/initiate/")
    assert resp.status_code == 302
    url = urlparse(resp.url)
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert q["client_id"] == GOOGLE_CLIENT_ID
    assert q["response_type"] == "code"
    assert q["scope"] == "openid email profile"
    assert q["code_challenge_method"] == "S256"
    assert q["redirect_uri"].endswith("/auth/google/callback/")
    flow = client.session["google_oauth"]
    assert q["state"] == flow["state"] and q["nonce"] == flow["nonce"]
    # The verifier never leaves the server; only its challenge does.
    assert flow["verifier"] not in resp.url


# --- callback: the happy path and linking -------------------------------------

def test_signs_in_and_creates_user(client, google_signin, settings):
    settings.ACE_ALLOWED_EMAIL_DOMAINS = []  # open
    resp = google_signin(client, email="new@example.com", sub="g-new", name="New Person")
    assert resp.status_code == 302 and resp.url == "/"
    user = User.objects.get(email="new@example.com")
    assert user.google_sub == "g-new" and user.display_name == "New Person"
    assert client.session["_auth_user_id"] == str(user.pk)
    # The PKCE verifier is what Google was sent, so the code can't be replayed.
    sent = google_signin.last_post.call_args.kwargs["data"]
    assert sent["code_verifier"] and sent["grant_type"] == "authorization_code"


def test_links_to_existing_user_by_email_case_insensitively(client, google_signin):
    existing = User.objects.create_user(email="jane@example.com", display_name="Jane (Connect)")
    resp = google_signin(client, email="Jane@Example.COM", sub="g-jane", name="Jane G")
    assert resp.status_code == 302
    assert User.objects.count() == 1
    existing.refresh_from_db()
    assert existing.google_sub == "g-jane"
    assert existing.display_name == "Jane (Connect)"  # not clobbered
    assert client.session["_auth_user_id"] == str(existing.pk)


def test_returning_google_user_found_by_sub(client, google_signin):
    u = User.objects.create_user(email="a@example.com", google_sub="g-1")
    google_signin(client, email="a@example.com", sub="g-1")
    assert client.session["_auth_user_id"] == str(u.pk)


def test_refuses_when_a_different_google_account_is_linked(client, google_signin):
    User.objects.create_user(email="a@example.com", google_sub="g-original")
    resp = google_signin(client, email="a@example.com", sub="g-attacker")
    assert resp.url == "/auth/login/"
    assert "_auth_user_id" not in client.session
    assert User.objects.get(email="a@example.com").google_sub == "g-original"


def test_session_key_rotates_on_login(client, google_signin):
    client.get("/auth/login/")
    before = client.session.session_key
    google_signin(client, email="r@example.com")
    assert client.session.session_key != before


def test_next_is_honoured_and_open_redirects_are_not(client, google_signin):
    resp = google_signin(client, flow_next="/w/spark/opps")
    assert resp.url == "/w/spark/opps"
    client.logout()
    resp = google_signin(client, flow_next="https://evil.example/steal")
    assert resp.url == "/"


# --- callback: every OIDC check fails closed ----------------------------------

@pytest.mark.parametrize("claims", [
    {"email_verified": False},
    {"email_verified": None},          # claim absent
    {"email_verified": "false"},
    {"email": None},
], ids=["unverified", "no-claim", "string-false", "no-email"])
def test_requires_a_verified_email(client, google_signin, claims):
    resp = google_signin(client, **claims)
    assert resp.url == "/auth/login/"
    assert "_auth_user_id" not in client.session
    assert User.objects.count() == 0


def test_accepts_string_true_email_verified(client, google_signin):
    google_signin(client, email_verified="true")
    assert "_auth_user_id" in client.session


@pytest.mark.parametrize("claims", [
    {"nonce": "not-the-nonce"},
    {"nonce": None},
    {"aud": "someone-elses-client"},
    {"iss": "https://evil.example"},
    {"exp": 1},
], ids=["nonce", "no-nonce", "aud", "iss", "expired"])
def test_rejects_bad_id_token_claims(client, google_signin, claims):
    resp = google_signin(client, **claims)
    assert resp.url == "/auth/login/"
    assert "_auth_user_id" not in client.session
    assert User.objects.count() == 0


def test_rejects_token_signed_by_another_key(client, google_signin):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    resp = google_signin(client, key=other)
    assert resp.url == "/auth/login/"
    assert User.objects.count() == 0


def test_rejects_wrong_state(client, google_signin):
    resp = google_signin(client, state="forged")
    assert resp.url == "/auth/login/"
    assert User.objects.count() == 0


def test_callback_without_initiate_is_refused(client, google_cfg):
    resp = client.get("/auth/google/callback/?state=x&code=y")
    assert resp.url == "/auth/login/"


def test_flow_is_single_use(client, google_signin, google_cfg):
    google_signin(client, email="once@example.com")
    client.logout()
    resp = client.get("/auth/google/callback/?state=anything&code=y")
    assert resp.url == "/auth/login/"  # session flow was consumed


def test_user_declining_at_google_is_handled(client, google_cfg):
    client.get("/auth/google/initiate/")
    state = client.session["google_oauth"]["state"]
    resp = client.get(f"/auth/google/callback/?state={state}&error=access_denied")
    assert resp.url == "/auth/login/"


# --- linking from a signed-in account ------------------------------------------

def test_link_requires_sign_in(client, google_cfg):
    assert client.get("/auth/google/initiate/?mode=link").url == "/auth/login/"


def test_signed_in_user_links_google_with_matching_verified_email(client, google_signin):
    user = User.objects.create_user(email="me@example.com")
    client.force_login(user)
    resp = google_signin(client, mode="link", email="ME@example.com", sub="g-me")
    assert resp.url == "/auth/account/"
    user.refresh_from_db()
    assert user.google_sub == "g-me"


def test_link_refuses_a_google_account_with_a_different_email(client, google_signin):
    user = User.objects.create_user(email="me@example.com")
    client.force_login(user)
    google_signin(client, mode="link", email="other@example.com", sub="g-other")
    user.refresh_from_db()
    assert user.google_sub is None


def test_link_refuses_unverified_email(client, google_signin):
    user = User.objects.create_user(email="me@example.com")
    client.force_login(user)
    google_signin(client, mode="link", email="me@example.com", email_verified=False)
    user.refresh_from_db()
    assert user.google_sub is None


def test_link_refuses_a_google_account_already_on_another_user(client, google_signin):
    User.objects.create_user(email="first@example.com", google_sub="g-shared")
    user = User.objects.create_user(email="me@example.com")
    client.force_login(user)
    google_signin(client, mode="link", email="me@example.com", sub="g-shared")
    user.refresh_from_db()
    assert user.google_sub is None


# --- the admission gate ---------------------------------------------------------

def test_uninvited_outsider_is_refused_and_leaves_no_row(client, google_signin, restricted):
    resp = google_signin(client, email="stranger@elsewhere.org")
    assert resp.url == "/auth/login/"
    assert "_auth_user_id" not in client.session
    assert not User.objects.filter(email="stranger@elsewhere.org").exists()


def test_invited_outsider_is_admitted(client, google_signin, restricted, workspace):
    invite(workspace, "anne@sparkmicrogrants.org")
    google_signin(client, email="Anne@SparkMicrogrants.org")
    assert User.objects.get(email="anne@sparkmicrogrants.org")
    assert "_auth_user_id" in client.session
