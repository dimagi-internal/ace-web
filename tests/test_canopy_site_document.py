"""ace-web's signed ``site.json`` (``canopy_sdk.site``), served beside its JWKS.

canopy's Connected sites page fills the ``ace-web`` registration from this
document ("Fill from the site's own documents") instead of an owner typing
URLs. It is checked here the way canopy checks it: fetched beside the
registered JWKS URL and verified with ``verify_site_document`` against the keys
that JWKS serves.
"""
from __future__ import annotations

import pytest
from canopy_sdk.site import MEDIA_TYPE, SITE_DOCUMENT_NAME, SITE_TYP, verify_site_document
from django.test import Client
from jwt import PyJWK, get_unverified_header

# The fixtures (signing key, issuer, grant on/off) are the host-grant suite's.
from tests.test_canopy_host_grant import (  # noqa: F401 - pytest fixtures
    ISSUER,
    RESOURCE,
    grant_on,
    host_key,
)

JWKS_PATH = "/api/canopy/jwks"
SITE_PATH = "/api/canopy/site.json"


def _beside(jwks_url: str) -> str:
    """canopy's rule for a `…/jwks` route (host_grants.site_needs.document_url)."""
    head, _, name = jwks_url.rstrip("/").rpartition("/")
    assert name == "jwks"
    return f"{head}/{SITE_DOCUMENT_NAME}"


def _verified(client: Client):
    response = client.get(SITE_PATH)
    assert response.status_code == 200, response.content
    keys = [PyJWK.from_dict(k).key for k in client.get(JWKS_PATH).json()["keys"]]
    return response, verify_site_document(response.content.decode(), keys, site_name="ace-web")


def test_site_json_is_served_beside_the_jwks():
    assert _beside(ISSUER + JWKS_PATH) == ISSUER + SITE_PATH


@pytest.mark.django_db
def test_canopy_verifies_it_with_our_jwks_and_reads_our_facts(grant_on):  # noqa: F811
    response, needs = _verified(Client())
    assert response["Content-Type"] == MEDIA_TYPE
    assert get_unverified_header(response.content.decode())["typ"] == SITE_TYP
    assert needs.site_name == "ace-web"
    site = needs.site
    assert site.origins == ("https://labs.connect.dimagi.com",)
    assert site.jwks_url == ISSUER + JWKS_PATH
    assert site.issuer == ISSUER
    assert site.mcp_resource == RESOURCE
    assert [(p.key, p.scopes) for p in needs.pages] == [("opp-workbench", ("opps:read",))]
    assert needs.pages[0].title


@pytest.mark.django_db
def test_while_the_grant_is_off_it_names_no_issuer_or_mcp_server(host_key):  # noqa: F811
    _, needs = _verified(Client())
    assert needs.site.jwks_url == ISSUER + JWKS_PATH
    assert needs.site.issuer == "" and needs.site.mcp_resource == ""


def test_no_signing_key_is_a_503_not_an_unsigned_document(settings):
    settings.CANOPY_SIGNING_KEY = ""
    assert Client().get(SITE_PATH).status_code == 503
