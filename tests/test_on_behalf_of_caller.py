"""Accepting canopy's word that an agent is answering one of our users.

This mints an ace-web credential from somebody else's signature, so the refusals
are the feature: a forged or replayed assertion, one minted for a different
site, or one naming a person who does not exist here must all fail, and fail
before a token is made rather than after.
"""

import json
import time
import uuid
from unittest import mock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, override_settings
from django.utils import timezone

from apps.auth.models import PersonalToken
from apps.canopy import client as canopy_client
from apps.canopy import onbehalf

pytestmark = pytest.mark.django_db

CANOPY = "https://canopy.test/canopy"
ON = dict(CANOPY_BASE_URL=CANOPY, CANOPY_APP_NAME="ace-web",
          CANOPY_ASSERTION_AUDIENCE="", CANOPY_WORKSPACE="connect",
          CANOPY_AGENT_SLUG="ace")


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


def _keypair():
    priv = ed25519.Ed25519PrivateKey.generate()
    pem = priv.private_bytes(encoding=serialization.Encoding.PEM,
                             format=serialization.PrivateFormat.PKCS8,
                             encryption_algorithm=serialization.NoEncryption()).decode()
    return pem, priv.public_key()


def _jwk(public_key, kid="canopy-1"):
    from jwt.algorithms import OKPAlgorithm

    d = OKPAlgorithm.to_jwk(public_key, as_dict=True)
    d.update({"use": "sig", "alg": "EdDSA", "kid": kid})
    return d


def _canopy_serves(*jwks):
    """Stand in for canopy's published keys."""
    body = json.dumps({"keys": list(jwks)}).encode()
    resp = mock.MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    return mock.patch("apps.canopy.onbehalf.urllib.request.urlopen", return_value=resp)


def _assertion(priv, *, sub="someone@dimagi.com", aud="ace-web", iss=CANOPY,
               kid="canopy-1", lifetime=120, jti=None):
    now = int(time.time())
    return jwt.encode(
        {"iss": iss, "sub": sub, "aud": aud, "iat": now, "exp": now + lifetime,
         "jti": jti or str(uuid.uuid4()), "act": {"sub": "agent:ace"}},
        priv, algorithm="EdDSA", headers={"kid": kid},
    )


def _user(email="someone@dimagi.com"):
    return get_user_model().objects.create_user(email=email)


def _post(assertion):
    return Client().post("/api/canopy/on-behalf-token",
                         data={"assertion": assertion}, content_type="application/json")


@override_settings(**ON)
def test_a_valid_assertion_yields_a_token_that_acts_as_that_person():
    priv, pub = _keypair()
    user = _user()
    with _canopy_serves(_jwk(pub)):
        r = _post(_assertion(priv))
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["acting_as"] == user.email
    # The token is real, and resolves to THEM — which is what makes the
    # agent's later calls ordinary authenticated ace-web calls.
    assert PersonalToken.lookup(body["token"]).user_id == user.pk


@override_settings(**ON)
def test_the_token_expires_so_it_does_not_outlive_the_answer():
    priv, pub = _keypair()
    _user()
    with _canopy_serves(_jwk(pub)):
        token = _post(_assertion(priv)).json()["token"]
    row = PersonalToken.lookup(token)
    assert row.expires_at is not None
    # And an expiry nothing enforces would be a comment: the lookup every
    # authenticated request goes through must stop honouring it.
    PersonalToken.objects.filter(pk=row.pk).update(
        expires_at=timezone.now() - timezone.timedelta(seconds=1)
    )
    assert PersonalToken.lookup(token) is None


@override_settings(**ON)
def test_a_cli_token_still_never_expires():
    """The long-lived tokens this model was built for must not be swept up."""
    user = _user()
    raw, row = PersonalToken.create_for_user(user=user, label="ace-upload")
    assert row.expires_at is None
    assert PersonalToken.lookup(raw).pk == row.pk


@override_settings(**ON)
def test_an_assertion_signed_by_anyone_else_is_refused():
    """Canopy's signature is the entire credential here."""
    _priv, pub = _keypair()
    other_priv, _ = _keypair()
    _user()
    with _canopy_serves(_jwk(pub)):
        r = _post(_assertion(other_priv))
    assert r.status_code == 401
    assert not PersonalToken.objects.exists()


@override_settings(**ON)
def test_an_assertion_for_a_different_site_is_refused():
    """Canopy mints these per connected site. Without checking `aud`, one minted
    for another site could be replayed here to act as its subject."""
    priv, pub = _keypair()
    _user()
    with _canopy_serves(_jwk(pub)):
        r = _post(_assertion(priv, aud="some-other-site"))
    assert r.status_code == 401
    assert b"different site" in r.content


@override_settings(**ON)
def test_an_assertion_from_another_canopy_is_refused():
    priv, pub = _keypair()
    _user()
    with _canopy_serves(_jwk(pub)):
        r = _post(_assertion(priv, iss="https://someone-elses-canopy.test"))
    assert r.status_code == 401


@override_settings(**ON)
def test_an_expired_assertion_is_refused():
    priv, pub = _keypair()
    _user()
    with _canopy_serves(_jwk(pub)):
        r = _post(_assertion(priv, lifetime=-300))
    assert r.status_code == 401
    assert b"expired" in r.content


@override_settings(**ON)
def test_the_same_assertion_cannot_be_spent_twice():
    """Single use. A copy taken from a log is otherwise a standing grant for as
    long as it has left to live."""
    priv, pub = _keypair()
    _user()
    token = _assertion(priv)
    with _canopy_serves(_jwk(pub)):
        assert _post(token).status_code == 200
        second = _post(token)
    assert second.status_code == 401
    assert b"already been used" in second.content
    assert PersonalToken.objects.count() == 1


@override_settings(**ON)
def test_a_subject_with_no_ace_web_account_is_refused_never_created():
    """This mints a credential for somebody. It must not invent the somebody —
    a signature from canopy is not an account factory."""
    priv, pub = _keypair()
    with _canopy_serves(_jwk(pub)):
        r = _post(_assertion(priv, sub="stranger@partner.org"))
    assert r.status_code == 422
    assert get_user_model().objects.filter(email="stranger@partner.org").count() == 0
    assert not PersonalToken.objects.exists()


@override_settings(**ON)
def test_a_deactivated_person_is_refused():
    priv, pub = _keypair()
    user = _user()
    get_user_model().objects.filter(pk=user.pk).update(is_active=False)
    with _canopy_serves(_jwk(pub)):
        r = _post(_assertion(priv))
    assert r.status_code == 422


@override_settings(**ON)
def test_an_unknown_kid_refetches_so_a_canopy_rotation_is_picked_up():
    """Canopy rotated a minute ago. Waiting out our cache would refuse valid
    assertions in the meantime."""
    old_priv, old_pub = _keypair()
    new_priv, new_pub = _keypair()
    _user()
    with _canopy_serves(_jwk(old_pub, kid="old")):
        onbehalf._keys("old")  # warm the cache with only the old key
    with _canopy_serves(_jwk(old_pub, kid="old"), _jwk(new_pub, kid="new")):
        r = _post(_assertion(new_priv, kid="new"))
    assert r.status_code == 200, r.content


# --- the other direction: what ace-web publishes -------------------------------


@override_settings(**ON)
def test_we_publish_our_public_key_and_sign_with_its_kid(settings):
    """Registering this URL on canopy is what replaces pasting a key: canopy
    follows a rotation by `kid` with nothing to update on its side."""
    priv, _pub = _keypair()
    settings.CANOPY_SIGNING_KEY = priv

    served = Client().get("/api/canopy/jwks").json()["keys"]
    assert len(served) == 1
    assert "d" not in served[0], "public halves only"

    token = canopy_client._assertion("someone@dimagi.com")
    assert jwt.get_unverified_header(token)["kid"] == served[0]["kid"]


@override_settings(**ON)
def test_a_rotation_publishes_the_outgoing_key_too(settings):
    old_priv, old_pub = _keypair()
    new_priv, _ = _keypair()
    old_pem = old_pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    settings.CANOPY_SIGNING_KEY = new_priv
    settings.CANOPY_RETIRED_PUBLIC_KEYS = old_pem

    served = Client().get("/api/canopy/jwks").json()["keys"]
    kids = {k["kid"] for k in served}
    assert len(kids) == 2
    assert canopy_client.active_kid() in kids

    settings.CANOPY_SIGNING_KEY = old_priv
    assert canopy_client.active_kid() in kids, "the outgoing key is still verifiable"
