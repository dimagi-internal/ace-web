"""ace-web as a canopy HOST, through the canopy SDK (host grant contract v1).

Two halves, tested through ace-web's own wiring (the SDK has its own suite):

* the ARRIVAL — the visitor assertion ace-web has always signed, now signed by
  ``canopy_sdk.host``: the same claims, the same key id, accepted by canopy's
  own verifier; and nothing else in the request while the grant is off;
* the GRANT — off until ``CANOPY_CLIENT_ID`` is set; on, an ID-JAG only for a
  registered page, redeemed at our token endpoint by a stand-in canopy (the
  SDK's conformance fixtures), and a DPoP-bound call to our MCP that sees only
  its scope's tools and runs AS the visitor.
"""
from __future__ import annotations

import base64
import hashlib
import json
from unittest import mock

import httpx
import jwt
import pytest
from canopy_sdk import consumer, contract
from canopy_sdk.django.models import DelegatedToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from django.contrib.auth import get_user_model
from django.test import Client

from apps.canopy import client as canopy_client
from apps.canopy import grant

User = get_user_model()

CANOPY = "https://labs.connect.dimagi.com/canopy"
ISSUER = "https://labs.connect.dimagi.com/ace"
RESOURCE = ISSUER + "/api/mcp/"
TOKEN_ENDPOINT = ISSUER + "/api/canopy/oauth/token"
CANOPY_CLIENT_ID = "https://canopy.test/oauth/client.json"  # the conformance fixtures'
WORKBENCH = "/ace/w/team/opps/field-hep/runs/20260901-1200"


def _pem(key) -> str:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


@pytest.fixture
def host_key(settings):
    key = ed25519.Ed25519PrivateKey.generate()
    settings.CANOPY_SIGNING_KEY = _pem(key)
    settings.CANOPY_BASE_URL = CANOPY
    settings.CANOPY_APP_NAME = "ace-web"
    settings.CANOPY_ASSERTION_AUDIENCE = ""
    settings.CANOPY_AGENT_SLUG = "ace"
    settings.CANOPY_RETIRED_PUBLIC_KEYS = ""
    settings.ACE_PUBLIC_BASE_URL = ISSUER
    settings.CANOPY_CLIENT_ID = ""
    return key


@pytest.fixture
def grant_on(host_key, settings, canopy_client_documents):
    settings.CANOPY_CLIENT_ID = CANOPY_CLIENT_ID
    with mock.patch("canopy_sdk.host.client_keys.fetch.get_json",
                    side_effect=canopy_client_documents.__getitem__):
        yield host_key


# --- the arrival: unchanged -------------------------------------------------------------


def _rfc7638(key) -> str:
    from jwt.algorithms import OKPAlgorithm

    jwk = OKPAlgorithm.to_jwk(key.public_key(), as_dict=True)
    canonical = json.dumps({"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"]},
                           separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(hashlib.sha256(canonical).digest()).decode().rstrip("=")


def test_the_assertion_carries_the_same_claims_and_key_id_as_before(host_key):
    """What canopy's `ace-web` site row has been verifying since #779: EdDSA,
    `kid` = the key's RFC 7638 thumbprint, `sub` = the lower-cased email,
    `email_verified`, 60s. `name` is new and empty (canopy treats "" as absent)."""
    token = canopy_client._assertion("Alice@Dimagi.com")
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "EdDSA" and header["kid"] == _rfc7638(host_key)
    claims = jwt.decode(token, host_key.public_key(), algorithms=["EdDSA"], audience=CANOPY)
    assert set(claims) == {"iss", "sub", "aud", "iat", "exp", "jti", "email",
                           "email_verified", "name"}
    assert claims["iss"] == "ace-web" and claims["sub"] == "alice@dimagi.com"
    assert claims["email"] == "alice@dimagi.com" and claims["email_verified"] is True
    assert claims["exp"] - claims["iat"] == 60 and claims["name"] == ""


def test_canopys_own_verifier_accepts_it_against_our_published_jwks(host_key):
    """The consumer half of the same SDK is what canopy runs on arrival."""
    from jwt import PyJWK

    served = Client().get("/api/canopy/jwks").json()["keys"]
    keys = [PyJWK.from_dict(k).key for k in served]
    claims = consumer.verify_visitor_assertion(canopy_client._assertion("a@dimagi.com"), keys,
                                               audience=CANOPY)
    assert claims["sub"] == "a@dimagi.com"


def test_the_jwks_is_public_only_and_names_the_signing_kid(host_key):
    (served,) = Client().get("/api/canopy/jwks").json()["keys"]
    assert served == {"kty": "OKP", "crv": "Ed25519", "x": served["x"], "use": "sig",
                      "alg": "EdDSA", "kid": _rfc7638(host_key)}


def test_a_malformed_retired_key_never_hides_the_live_one(host_key, settings):
    retired = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    settings.CANOPY_RETIRED_PUBLIC_KEYS = f"not a key|{retired}"
    kids = [k["kid"] for k in Client().get("/api/canopy/jwks").json()["keys"]]
    assert len(kids) == 2 and kids[0] == _rfc7638(host_key)


def test_no_signing_key_publishes_nothing(settings):
    settings.CANOPY_SIGNING_KEY = ""
    assert Client().get("/api/canopy/jwks").json() == {"keys": []}


# --- the grant, off (the merged default) ----------------------------------------------


@pytest.mark.django_db
def test_off_by_default_the_arrival_has_no_id_jag_even_on_a_registered_page(host_key):
    assert not grant.grant_enabled()
    assert grant.scopes_for_page(WORKBENCH) == ()
    assert "id_jag" not in canopy_client.arrival("a@dimagi.com", scopes=("opps:read",))

    user = User.objects.create_user(email="a@dimagi.com")
    c = Client()
    c.force_login(user)
    with mock.patch("canopy_sdk.host.mint_contact_token",
                    return_value={"token": "t", "expires_at": "x", "kind": "user"}) as post:
        r = c.post(f"/api/canopy/token?page={WORKBENCH}")
    assert r.status_code == 200
    assert set(post.call_args.args[1]) == {"assertion", "agent_slug"}


@pytest.mark.django_db
def test_off_by_default_the_token_endpoint_refuses_and_discovery_404s(host_key):
    r = Client().post("/api/canopy/oauth/token",
                      {"grant_type": contract.JWT_BEARER_GRANT, "assertion": "x"})
    assert r.status_code == 400 and r.json()["error"] == "unsupported_grant_type"
    assert Client().get("/.well-known/oauth-authorization-server/ace").status_code == 404
    assert Client().get("/.well-known/oauth-protected-resource/ace/api/mcp").status_code == 404


# --- the registries -----------------------------------------------------------------------


@pytest.mark.parametrize("path,key", [
    ("/ace/w/team/opps/field-hep", "opp-workbench"),
    ("/ace/w/team/opps/field-hep/runs/r1", "opp-workbench"),
    ("/ace/w/team/opps/field-hep/runs/r1/steps/idea-to-pdd", "opp-workbench"),
    ("/w/team/opps/field-hep/", "opp-workbench"),
    ("/ace/w/team/opps", ""),
    ("/ace/w/team/opps/compare/a/b", ""),
    ("/ace/w/team/opps/field-hep/compare", ""),
    ("/ace/w/team/sessions", ""),
    ("/ace/w/team/chat/c/123", ""),
    ("/ace/settings", ""),
    ("", ""),
])
def test_only_the_opp_workbench_is_a_registered_page(path, key):
    assert grant.page_key(path) == key


def test_the_sdk_accepts_the_registries(host_key):
    """The SDK refuses a page naming a scope the server does not offer — and,
    in key mode (an SPA: the browser names its page), any scope that is not
    read-only."""
    from canopy_sdk.django import conf

    registry = conf.page_registry()
    assert registry.mode == "key"
    assert registry.scopes_for("opp-workbench") == ("opps:read",)
    assert registry.scopes_for("opps:read") == (), "a page names scopes; it cannot BE one"


@pytest.mark.asyncio
async def test_every_granted_tool_is_a_real_read_only_mcp_tool():
    """A scope naming a tool that does not exist is worse than none (the agent
    will try it); a scope reaching a write would break "start read-only"."""
    from apps.api.api import api
    from apps.api.mcp_server import build_mcp

    names = {t.name for t in await build_mcp().list_tools()}
    granted = {t for tools in grant.SCOPE_TOOLS.values() for t in tools}
    assert granted <= names
    methods = {op.get("operationId"): method
               for ops in api.get_openapi_schema()["paths"].values()
               for method, op in ops.items() if isinstance(op, dict)}
    assert {methods[t] for t in granted} == {"get"}
    assert "apps_opps_api_seeded_run" not in granted


# --- the grant, on ------------------------------------------------------------------------


def test_on_a_registered_page_the_arrival_carries_an_id_jag_canopy_accepts(grant_on):
    scopes = grant.scopes_for_page(WORKBENCH)
    assert scopes == ("opps:read",)
    body = canopy_client.arrival("Alice@Dimagi.com", scopes=scopes)
    from jwt import PyJWK

    served = [PyJWK.from_dict(k).key for k in Client().get("/api/canopy/jwks").json()["keys"]]
    claims = consumer.check_id_jag(body["id_jag"], served, issuer=ISSUER,
                                   client_id=CANOPY_CLIENT_ID, resource=RESOURCE,
                                   subject="alice@dimagi.com")
    assert claims["scope"] == "opps:read" and claims["aud"] == ISSUER
    # The same `sub` as the assertion it rides with.
    assertion = jwt.decode(body["assertion"], options={"verify_signature": False})
    assert assertion["sub"] == claims["sub"]


def test_an_unregistered_page_gets_no_id_jag(grant_on):
    assert grant.scopes_for_page("/ace/w/team/sessions") == ()


@pytest.mark.django_db
def test_discovery_documents_name_our_issuer_and_endpoints(grant_on):
    from canopy_sdk.conformance import check_metadata

    docs = {
        contract.metadata_url(ISSUER): "/.well-known/oauth-authorization-server/ace",
        contract.protected_resource_metadata_url(RESOURCE):
            "/.well-known/oauth-protected-resource/ace/api/mcp",
    }

    def fetch(url):
        r = Client().get(docs[url])
        assert r.status_code == 200, (url, r.status_code)
        return r.json()

    report = check_metadata(ISSUER, RESOURCE, fetch_json=fetch)
    report.raise_for_failures()
    assert fetch(contract.metadata_url(ISSUER))["token_endpoint"] == TOKEN_ENDPOINT


def _redeem(canopy_redeem, email="alice@dimagi.com"):
    id_jag = canopy_client.arrival(email, scopes=("opps:read",))["id_jag"]
    form, proof = canopy_redeem(id_jag, TOKEN_ENDPOINT, RESOURCE, ISSUER)
    return Client().post("/api/canopy/oauth/token", form, headers={"DPoP": proof})


@pytest.mark.django_db
def test_canopy_redeems_the_id_jag_for_a_dpop_bound_token(grant_on, canopy_redeem):
    User.objects.create_user(email="alice@dimagi.com")
    r = _redeem(canopy_redeem)
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["token_type"] == "DPoP" and body["scope"] == "opps:read"
    assert "refresh_token" not in body and body["expires_in"] <= 900
    row = DelegatedToken.objects.get()
    assert row.subject == "alice@dimagi.com" and row.client_id == CANOPY_CLIENT_ID


@pytest.mark.django_db
def test_no_grant_for_someone_without_an_active_account(grant_on, canopy_redeem):
    """The ID-JAG names a person; redeeming it must never invent one."""
    r = _redeem(canopy_redeem, email="nobody@dimagi.com")
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    assert not User.objects.filter(email="nobody@dimagi.com").exists()


@pytest.mark.django_db
def test_a_grant_works_once(grant_on, canopy_redeem):
    User.objects.create_user(email="alice@dimagi.com")
    id_jag = canopy_client.arrival("alice@dimagi.com", scopes=("opps:read",))["id_jag"]
    first = canopy_redeem(id_jag, TOKEN_ENDPOINT, RESOURCE, ISSUER)
    assert Client().post("/api/canopy/oauth/token", first[0],
                         headers={"DPoP": first[1]}).status_code == 200
    again = canopy_redeem(id_jag, TOKEN_ENDPOINT, RESOURCE, ISSUER)
    r = Client().post("/api/canopy/oauth/token", again[0], headers={"DPoP": again[1]})
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


@pytest.mark.django_db
def test_the_token_endpoint_page_param_reaches_the_arrival(grant_on):
    user = User.objects.create_user(email="alice@dimagi.com")
    c = Client()
    c.force_login(user)
    with mock.patch("canopy_sdk.host.mint_contact_token",
                    return_value={"token": "t", "expires_at": "x", "kind": "user"}) as post:
        assert c.post(f"/api/canopy/token?page={WORKBENCH}").status_code == 200
        assert "id_jag" in post.call_args.args[1]
        assert c.post("/api/canopy/token?page=/ace/w/team/sessions").status_code == 200
        assert "id_jag" not in post.call_args.args[1]


# --- the MCP, end to end ------------------------------------------------------------------


class _DPoPAuth(httpx.Auth):
    """What canopy's gateway sends: a FRESH proof per request (each is single-use),
    bound to the public MCP URL and the token's hash."""

    def __init__(self, client, token):
        self.client, self.token = client, token

    def auth_flow(self, request):
        request.headers["Authorization"] = consumer.dpop_authorization(self.token)
        request.headers["DPoP"] = self.client.dpop_proof(request.method, RESOURCE,
                                                         access_token=self.token)
        request.headers["Canopy-Actor"] = "ace"
        yield request


class _BearerAuth(httpx.Auth):
    def __init__(self, token):
        self.token = token

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {self.token}"
        yield request


async def _mcp_session(auth):
    """A fastmcp client talking to the MOUNTED app (grant gate + FastMCP)
    in-process, as config/asgi.py mounts it."""
    from fastmcp import Client as MCPClient
    from fastmcp.client.transports import StreamableHttpTransport

    from apps.api.mcp_server import mcp

    app = mcp.http_app(path="/", transport="streamable-http")
    mounted = grant.mcp_app(app)

    def factory(**kwargs):
        kwargs.pop("auth", None)
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=mounted), auth=auth, **kwargs)

    transport = StreamableHttpTransport("http://localhost/", httpx_client_factory=factory)
    return app, MCPClient(transport)


@pytest.fixture
def workbench_user(db):
    from apps.workspaces.models import Workspace, WorkspaceMembership

    user = User.objects.create_user(email="alice@dimagi.com")
    ws = Workspace.objects.create(slug="team", display_name="Team",
                                  drive_root_folder_id="folder-team", created_by=user)
    WorkspaceMembership.objects.create(workspace=ws, user=user, role="viewer")
    Workspace.objects.create(slug="other", display_name="Other",
                             drive_root_folder_id="folder-other", created_by=user)
    return user


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_delegated_session_sees_its_tools_and_runs_as_the_visitor(
        grant_on, canopy_client, canopy_redeem, workbench_user):
    from asgiref.sync import sync_to_async

    r = await sync_to_async(_redeem)(canopy_redeem)
    token = r.json()["access_token"]
    app, mcp_client = await _mcp_session(_DPoPAuth(canopy_client, token))
    seen = []

    def cards(workspace):
        seen.append(workspace.slug)
        return [{"slug": "field-hep"}]

    with mock.patch("apps.opps.api.list_opp_cards", side_effect=cards):
        async with app.lifespan(app), mcp_client:
            names = {t.name for t in await mcp_client.list_tools()}
            assert names == set(grant.SCOPE_TOOLS["opps:read"])

            result = await mcp_client.call_tool("apps_opps_api_list_opps",
                                                {"workspace_slug": "team"})
            assert result.structured_content["items"] == [{"slug": "field-hep"}]
            assert seen == ["team"]

            # As the VISITOR: a workspace they are not in is a 404, not ACE's view.
            other = await mcp_client.call_tool("apps_opps_api_list_opps",
                                               {"workspace_slug": "other"},
                                               raise_on_error=False)
            assert other.is_error and seen == ["team"]

            # A tool outside the scope does not exist for this session.
            refused = await mcp_client.call_tool("apps_opps_api_seeded_run", {},
                                                 raise_on_error=False)
            assert refused.is_error


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_bound_token_is_useless_without_its_key(grant_on, canopy_redeem, workbench_user):
    """Copied out of a log and sent as a plain bearer, a delegated token is not a
    credential: the SDK's gate refuses it with a 401 before our app sees it
    (dimagi-canopy 0.4.1, RFC 9449 §7.1). Until 0.4.1 it reached the tool layer
    here and was refused only as a tool error — canopy's live probe caught it."""
    from asgiref.sync import sync_to_async

    token = (await sync_to_async(_redeem)(canopy_redeem)).json()["access_token"]
    inner = mock.AsyncMock()
    app = grant.mcp_app(inner)
    sent = []

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/",
             "headers": [(b"authorization", f"Bearer {token}".encode())]}
    await app(scope, mock.AsyncMock(), send)
    assert sent[0]["status"] == 401
    headers = dict(sent[0].get("headers") or [])
    assert b"invalid_token" in headers.get(b"www-authenticate", b"")
    inner.assert_not_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_dpop_request_with_a_bad_proof_is_refused_at_the_gate(grant_on, canopy_redeem):
    inner = mock.AsyncMock()
    app = grant.mcp_app(inner)
    sent = []

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/",
             "headers": [(b"authorization", b"DPoP whatever"), (b"dpop", b"not-a-proof")]}
    await app(scope, mock.AsyncMock(), send)
    assert sent[0]["status"] == 401
    inner.assert_not_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_personal_tokens_are_unchanged_with_the_grant_on(grant_on, workbench_user):
    """Direct users of the MCP (a PAT) see every tool, exactly as before."""
    from asgiref.sync import sync_to_async

    from apps.api.tests.test_mcp_server import _EXPECTED_TOOL_NAMES
    from apps.auth.models import PersonalToken

    raw, _ = await sync_to_async(PersonalToken.create_for_user)(user=workbench_user, label="t")
    app, mcp_client = await _mcp_session(_BearerAuth(raw))
    with mock.patch("apps.opps.api.list_opp_cards", return_value=[]):
        async with app.lifespan(app), mcp_client:
            assert {t.name for t in await mcp_client.list_tools()} == _EXPECTED_TOOL_NAMES
            result = await mcp_client.call_tool("apps_opps_api_list_opps",
                                                {"workspace_slug": "team"})
            assert result.structured_content["items"] == []


@pytest.mark.asyncio
async def test_off_the_mounted_mcp_refuses_dpop_401_and_passes_bearers(host_key):
    """The SDK's gate is installed unconditionally: with the grant off, a DPoP
    request is a 401 (never a 500) and a PAT reaches the app with no principal."""
    seen = []

    async def app(scope, receive, send):
        seen.append(scope.get(grant.PRINCIPAL_SCOPE_KEY, "missing"))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    assert not grant.grant_enabled()
    transport = httpx.ASGITransport(app=grant.mcp_app(app))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.post("/", headers={"Authorization": "DPoP abc", "DPoP": "x.y.z"})
        assert r.status_code == 401 and r.json()["error"] == "invalid_dpop_proof"
        assert (await c.post("/", headers={"Authorization": "Bearer pat"})).status_code == 200
    assert seen == [None]
