"""canopy's LIVE PROBE at ace-web (canopy SDK 0.4.0, ``apps/canopy/probe.py``).

The SDK tests the probe endpoint's own checks; these test ace-web's WIRING:
the principal is what we say it is (no way in, one empty workspace), the
endpoint is mounted where ``CANOPY_HOST["PROBE"]["ENDPOINT"]`` says, it is
off until it should be on, canopy can obtain and redeem a probe grant through
our real views, and the probe's tool really succeeds AS the probe principal
through the mounted MCP — while the out-of-scope tool is refused.
"""
from __future__ import annotations

import asyncio
from unittest import mock

import jwt
import pytest
from canopy_sdk import contract
from canopy_sdk.conformance import live
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import resolve

from apps.canopy import grant, probe
from apps.workspaces.models import Workspace, WorkspaceMembership
from tests.test_canopy_host_grant import (  # noqa: F401 - fixtures
    CANOPY_CLIENT_ID,
    ISSUER,
    RESOURCE,
    _DPoPAuth,
    _mcp_session,
    grant_on,
    host_key,
)

User = get_user_model()

PROBE_PATH = "/api/canopy/oauth/probe"
PROBE_URL = ISSUER + PROBE_PATH
ORIGIN = "https://labs.connect.dimagi.com"


def _principal():
    return probe.ensure_principal(User, Workspace, WorkspaceMembership)


@pytest.fixture
def probe_on(grant_on, settings):  # noqa: F811 - the imported fixture
    settings.CANOPY_PROBE_ENABLED = True
    return grant_on


def _path(url: str) -> str:
    """A public URL → the path Django sees (the ALB's `/ace` is FORCE_SCRIPT_NAME)."""
    assert url.startswith(ORIGIN), url
    path = url[len(ORIGIN):]
    return path[len("/ace"):] if path.startswith("/ace/") else path


def _fetch_json(url: str) -> dict:
    r = Client().get(_path(url))
    assert r.status_code == 200, (url, r.status_code)
    return r.json()


def _post_form(url, data, headers=None, what=""):
    # canopy's real client: no session, CSRF enforced as for any stranger.
    r = Client(enforce_csrf_checks=True).post(_path(url), data, headers=headers or {})
    return r.status_code, r.json(), dict(r.headers)


def _metadata() -> dict:
    return Client().get("/.well-known/oauth-authorization-server/ace").json()


# --- the principal --------------------------------------------------------------------


@pytest.mark.django_db
def test_the_probe_principal_has_no_way_in_and_one_empty_workspace():
    user, ws = _principal()
    user.refresh_from_db()
    assert user.email == "canopy-probe@probe.invalid" and user.email.endswith(".invalid")
    assert not user.has_usable_password()
    assert user.is_active and not user.is_staff and not user.is_superuser
    assert user.google_sub is None
    assert list(WorkspaceMembership.objects.filter(user=user).values_list(
        "workspace_id", "role")) == [("canopy-probe", "viewer")]
    assert ws.drive_root_folder_id == "" and ws.auto_join_domains == []


@pytest.mark.django_db
def test_ensure_principal_is_idempotent_and_never_widens():
    user, ws = _principal()
    User.objects.filter(pk=user.pk).update(is_staff=True, is_superuser=True)
    WorkspaceMembership.objects.filter(user=user).update(role="owner")
    user.set_password("guessable")
    user.save()
    again, _ = _principal()
    again.refresh_from_db()
    assert again.pk == user.pk and User.objects.filter(email__iexact=probe.PROBE_EMAIL).count() == 1
    assert not again.has_usable_password() and not again.is_staff and not again.is_superuser
    assert WorkspaceMembership.objects.get(user=again).role == "viewer"


@pytest.mark.django_db
def test_the_migration_creates_and_removes_it():
    """Deploying with run_migrations creates the principal (0010); its reverse removes it."""
    from importlib import import_module

    from django.apps import apps as django_apps

    mod = import_module("apps.workspaces.migrations.0010_canopy_probe_principal")
    # A fresh install / test DB (no seeded dimagi-team) is left alone.
    mod.create(django_apps, None)
    assert not User.objects.filter(email=probe.PROBE_EMAIL).exists()
    assert not Workspace.objects.exists()

    # The deployed ace-web has dimagi-team.
    founder = User.objects.create_user(email="founder@dimagi.com")
    Workspace.objects.create(slug="dimagi-team", display_name="Dimagi Team",
                             drive_root_folder_id="folder-dimagi", created_by=founder)
    mod.create(django_apps, None)
    assert User.objects.filter(email=probe.PROBE_EMAIL, is_active=True).exists()
    assert not WorkspaceMembership.objects.filter(workspace_id="dimagi-team").exists()
    memberships = WorkspaceMembership.objects.filter(workspace_id="canopy-probe")
    assert list(memberships.values_list("role", flat=True)) == ["viewer"]
    mod.remove(django_apps, None)
    assert not User.objects.filter(email=probe.PROBE_EMAIL).exists()
    assert not Workspace.objects.filter(slug="canopy-probe").exists()


@pytest.mark.django_db
def test_the_management_command_creates_it_anywhere():
    from django.core.management import call_command

    call_command("ensure_canopy_probe")
    call_command("ensure_canopy_probe")
    user = User.objects.get(email=probe.PROBE_EMAIL)
    assert not user.has_usable_password()
    assert WorkspaceMembership.objects.get(user=user).workspace_id == "canopy-probe"


# --- configuration ----------------------------------------------------------------------


def test_the_endpoint_setting_is_where_the_view_is_mounted(settings):
    from canopy_sdk.django.views import probe_endpoint

    settings.CANOPY_PROBE_ENABLED = True
    settings.ACE_PUBLIC_BASE_URL = ISSUER
    assert settings.CANOPY_HOST["PROBE"]["ENDPOINT"] == PROBE_URL
    assert resolve(PROBE_PATH).func is probe_endpoint


def test_the_probe_tool_is_in_its_scope_and_the_denied_tool_is_a_real_tool_outside_it():
    unlocked = grant.SCOPE_TOOLS[probe.PROBE_SCOPE]
    assert probe.PROBE_TOOL in unlocked and probe.PROBE_DENIED_TOOL not in unlocked
    assert probe.PROBE_PAGE in grant.PAGE_SCOPES
    from apps.api.tests.test_mcp_server import _EXPECTED_TOOL_NAMES

    assert probe.PROBE_DENIED_TOOL in _EXPECTED_TOOL_NAMES


def test_the_subject_resolver_never_touches_the_orm_on_the_event_loop():
    """The DPoP gate builds its config on the event loop; the resolver runs there."""
    async def resolve_it():
        return probe.subject()

    assert asyncio.run(resolve_it()) == probe.PROBE_EMAIL


@pytest.mark.django_db
def test_off_by_default(grant_on, settings):  # noqa: F811 - the imported fixture
    _principal()
    assert settings.CANOPY_PROBE_ENABLED is False
    assert "PROBE" not in dict(settings.CANOPY_HOST)
    assert Client().post(PROBE_PATH).status_code == 404
    assert contract.PROBE_ENDPOINT_METADATA_FIELD not in _metadata()


@pytest.mark.django_db
def test_404_and_unadvertised_until_the_principal_exists(probe_on, canopy_client):
    probe.remove_principal(User, Workspace, WorkspaceMembership)
    assert probe.subject() == ""
    assert contract.PROBE_ENDPOINT_METADATA_FIELD not in _metadata()
    with pytest.raises(live.ProbeError) as exc:
        live.request_probe(ISSUER, canopy_client, fetch_json=_fetch_json, post_form=_post_form,
                           vet=lambda url: None)
    assert exc.value.code == "no_probe_endpoint"
    # Even asked directly.
    form = {"client_id": canopy_client.client_id,
            "client_assertion_type": contract.CLIENT_ASSERTION_TYPE,
            "client_assertion": canopy_client.client_assertion(ISSUER)}
    proof = {"DPoP": canopy_client.dpop_proof("POST", PROBE_URL)}
    assert _post_form(PROBE_URL, form, proof)[0] == 404


# --- the probe, on ------------------------------------------------------------------------


@pytest.mark.django_db
def test_canopy_gets_a_probe_id_jag_and_redeems_it(probe_on, canopy_client):
    _principal()
    assert _metadata()[contract.PROBE_ENDPOINT_METADATA_FIELD] == PROBE_URL

    report, grant_ = live.check_live_grant(ISSUER, RESOURCE, canopy_client,
                                           fetch_json=_fetch_json, post_form=_post_form)
    report.raise_for_failures()
    got = grant_.probe
    assert (got.endpoint, got.subject, got.scope, got.resource) == (
        PROBE_URL, probe.PROBE_EMAIL, "opps:read", RESOURCE)
    assert (got.tool, got.arguments, got.denied_tool, got.page) == (
        "apps_opps_api_list_opps", {"workspace_slug": "canopy-probe"},
        "apps_videos_api_list_programs", "opp-workbench")
    claims = jwt.decode(got.id_jag, options={"verify_signature": False})
    assert claims["canopy_probe"] is True and claims["client_id"] == CANOPY_CLIENT_ID
    assert grant_.token.scope == "opps:read"


@pytest.mark.django_db
def test_only_canopy_may_ask_and_it_may_not_choose_who(probe_on, canopy_client):
    _principal()
    base = {"client_id": canopy_client.client_id,
            "client_assertion_type": contract.CLIENT_ASSERTION_TYPE}

    def ask(extra=None, proof=True):
        form = {**base, "client_assertion": canopy_client.client_assertion(ISSUER), **(extra or {})}
        headers = {"DPoP": canopy_client.dpop_proof("POST", PROBE_URL)} if proof else {}
        return _post_form(PROBE_URL, form, headers)

    status, body, _ = ask(proof=False)
    assert status in (400, 401) and body["error"] == "invalid_dpop_proof"
    status, body, _ = ask({"sub": "alice@dimagi.com"})
    assert status == 400 and body["error"] == "invalid_request"
    status, body, _ = ask({"client_id": "https://evil.test/client.json"})
    assert status == 401 and body["error"] == "invalid_client"
    assert ask()[0] == 200


@pytest.mark.django_db
def test_an_inactive_principal_gets_nothing(probe_on, canopy_client):
    user, _ = _principal()
    User.objects.filter(pk=user.pk).update(is_active=False)
    with pytest.raises(live.ProbeError):
        live.request_probe(ISSUER, canopy_client, fetch_json=_fetch_json, post_form=_post_form,
                           vet=lambda url: None)


# --- the probe's call, through the mounted MCP ---------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_probe_tool_succeeds_as_the_probe_principal(probe_on, canopy_client):
    """(a) and (b) of canopy's check, against the real MCP: the tool runs AS
    the probe user (a member, so not a 404) and — the workspace having no Drive
    root — returns an empty list without any Drive call."""
    from asgiref.sync import sync_to_async

    await sync_to_async(_principal)()
    report, grant_ = await sync_to_async(live.check_live_grant)(
        ISSUER, RESOURCE, canopy_client, fetch_json=_fetch_json, post_form=_post_form)
    report.raise_for_failures()

    app, mcp_client = await _mcp_session(_DPoPAuth(canopy_client, grant_.token.access_token))
    with mock.patch("apps.opps.drive_client.get_drive_client",
                    side_effect=AssertionError("the probe must not reach Drive")):
        async with app.lifespan(app), mcp_client:
            names = {t.name for t in await mcp_client.list_tools()}
            assert probe.PROBE_TOOL in names and probe.PROBE_DENIED_TOOL not in names

            result = await mcp_client.call_tool(grant_.probe.tool, grant_.probe.arguments)
            assert not result.is_error
            assert result.structured_content["items"] == []
            assert result.structured_content["total"] == 0

            refused = await mcp_client.call_tool(grant_.probe.denied_tool, {},
                                                 raise_on_error=False)
            assert refused.is_error

            # It can read no real workspace.
            other = await mcp_client.call_tool(probe.PROBE_TOOL, {"workspace_slug": "dimagi-team"},
                                               raise_on_error=False)
            assert other.is_error
