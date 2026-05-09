"""Tests for apps.auth.cli_authorize_views — gh-style loopback PAT mint flow."""
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client
from django.urls import reverse

from apps.auth.cli_authorize_views import _validate_callback
from apps.auth.models import PersonalToken

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="op@example.com", display_name="op"
    )


@pytest.fixture
def client(user):
    c = Client()
    c.force_login(user)
    return c


def _qs(label="my-laptop", cb="http://127.0.0.1:54321/cb", state="abc123"):
    return {"label": label, "cb": cb, "state": state}


# --- _validate_callback unit tests --------------------------------------------

@pytest.mark.parametrize("cb", [
    "http://127.0.0.1:54321/cb",
    "http://localhost:8080/cb",
    "http://127.0.0.1:65535/anything",
    "http://[::1]:54321/cb",
])
def test_validate_callback_accepts_loopback(cb):
    assert _validate_callback(cb) == cb


@pytest.mark.parametrize("cb,reason", [
    ("", "empty"),
    ("https://127.0.0.1:54321/cb", "https"),
    ("http://example.com:54321/cb", "remote host"),
    ("http://192.168.1.5:54321/cb", "non-loopback IP"),
    ("file:///tmp/cb", "file scheme"),
    ("ftp://127.0.0.1:54321/cb", "ftp scheme"),
    ("http://user:pw@127.0.0.1:54321/cb", "userinfo"),
    ("http://127.0.0.1/cb", "no port"),
    ("http://127.0.0.1:80/cb", "privileged port"),
    ("http://127.0.0.1:1023/cb", "below 1024"),
    ("not a url at all", "garbage"),
])
def test_validate_callback_rejects(cb, reason):
    assert _validate_callback(cb) is None, f"should reject {reason}: {cb!r}"


# --- view tests ---------------------------------------------------------------

def test_get_renders_authorize_page(client):
    resp = client.get(reverse("auth:cli_authorize"), _qs())
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Authorize CLI access" in body
    assert "my-laptop" in body
    assert "127.0.0.1:54321" in body
    assert "op@example.com" in body
    assert "csrfmiddlewaretoken" in body  # Django's CSRF input field


def test_post_creates_token_and_redirects(client, user):
    assert PersonalToken.objects.filter(user=user).count() == 0

    resp = client.post(reverse("auth:cli_authorize") + "?" + _urlencode(_qs()))
    assert resp.status_code == 302

    # Token row exists for this user.
    tokens = PersonalToken.objects.filter(user=user)
    assert tokens.count() == 1
    token = tokens.first()
    assert token.label == "my-laptop"
    assert token.revoked_at is None

    # Redirect target preserves cb host + path, includes token + state, omits cb/label.
    location = urlparse(resp["Location"])
    assert location.scheme == "http"
    assert location.netloc == "127.0.0.1:54321"
    assert location.path == "/cb"
    qs = parse_qs(location.query)
    assert qs["state"] == ["abc123"]
    raw = qs["token"][0]
    assert len(raw) >= 32

    # The raw token actually authenticates.
    assert PersonalToken.lookup(raw) is not None


def test_unauthenticated_redirects_to_login():
    c = Client()
    resp = c.get(reverse("auth:cli_authorize"), _qs())
    # @login_required → 302 to login page, ?next= preserves the query string.
    assert resp.status_code == 302
    location = urlparse(resp["Location"])
    assert location.path == reverse("auth:login")
    next_param = parse_qs(location.query)["next"][0]
    assert "/auth/cli/authorize/" in next_param
    # cb + state + label survive the round-trip via ?next=.
    assert "cb=" in next_param
    assert "state=" in next_param
    assert "label=" in next_param


def test_get_rejects_non_loopback_cb(client):
    resp = client.get(reverse("auth:cli_authorize"), _qs(cb="https://evil.com/cb"))
    assert resp.status_code == 400


def test_post_rejects_non_loopback_cb(client, user):
    bad_qs = _urlencode(_qs(cb="https://evil.com/cb"))
    resp = client.post(reverse("auth:cli_authorize") + "?" + bad_qs)
    assert resp.status_code == 400
    # No token minted on a rejected request.
    assert PersonalToken.objects.filter(user=user).count() == 0


def test_get_rejects_missing_cb(client):
    resp = client.get(reverse("auth:cli_authorize"), {"state": "abc", "label": "x"})
    assert resp.status_code == 400


def test_get_rejects_missing_state(client):
    resp = client.get(
        reverse("auth:cli_authorize"),
        {"cb": "http://127.0.0.1:54321/cb", "label": "x"},
    )
    assert resp.status_code == 400


def test_default_label_when_omitted(client, user):
    qs = _urlencode({"cb": "http://127.0.0.1:54321/cb", "state": "abc123"})
    resp = client.post(reverse("auth:cli_authorize") + "?" + qs)
    assert resp.status_code == 302
    token = PersonalToken.objects.filter(user=user).first()
    assert token.label == "ace-cli"


def test_label_truncated_to_64_chars(client, user):
    long_label = "x" * 200
    qs = _urlencode(_qs(label=long_label))
    resp = client.post(reverse("auth:cli_authorize") + "?" + qs)
    assert resp.status_code == 302
    token = PersonalToken.objects.filter(user=user).first()
    assert len(token.label) == 64
    assert token.label == "x" * 64


def test_post_without_csrf_is_rejected(user):
    # Django's CsrfViewMiddleware kicks in only when enforce_csrf_checks=True
    # on the test client (force_login bypasses by default for ergonomics).
    c = Client(enforce_csrf_checks=True)
    c.force_login(user)
    qs = _urlencode(_qs())
    resp = c.post(reverse("auth:cli_authorize") + "?" + qs)
    assert resp.status_code == 403


def test_token_round_trips_via_bearer_auth(client, user):
    """End-to-end: the token minted via the redirect actually authenticates Bearer-auth requests."""
    resp = client.post(reverse("auth:cli_authorize") + "?" + _urlencode(_qs()))
    raw = parse_qs(urlparse(resp["Location"]).query)["token"][0]

    from rest_framework.test import APIClient
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    resp = api.get("/api/auth/tokens")
    assert resp.status_code == 200
    items = resp.json()["data"]
    labels = [it["label"] for it in items]
    assert "my-laptop" in labels


# --- helpers ------------------------------------------------------------------

def _urlencode(params: dict) -> str:
    from urllib.parse import urlencode
    return urlencode(params)
