"""Per-opp tenancy: model rules, API, copy-on-create, backfill.

Spec: docs/specs/2026-09-28-clone-and-release-design.md § Tenancy, § B.
"""
import importlib

import pytest
from django.apps import apps as django_apps
from django.test import Client

from apps.auth.models import User
from apps.opps.models import OppWorkspace
from apps.workspaces.models import TenancyChange, Workspace, WorkspaceMembership

pytestmark = pytest.mark.django_db

SHARED = {
    "hq_domain": "connect-ace-prod",
    "connect_holding_org": "ace-nm-org",
    "ocs_team": "connect-ace",
}


@pytest.fixture
def owner():
    return User.objects.create(email="owner@dimagi.com", display_name="Owner")


@pytest.fixture
def viewer():
    return User.objects.create(email="viewer@dimagi.com", display_name="Viewer")


@pytest.fixture
def outsider():
    return User.objects.create(email="out@dimagi.com", display_name="Out")


@pytest.fixture
def ws(owner, viewer):
    w = Workspace.objects.create(
        slug="spark", display_name="Spark", drive_root_folder_id="root-spark",
        created_by=owner, default_tenancy={"hq_domain": "connect-ace-spark"},
    )
    WorkspaceMembership.objects.create(workspace=w, user=owner, role="owner")
    WorkspaceMembership.objects.create(workspace=w, user=viewer, role="viewer")
    return w


@pytest.fixture
def opp(ws, owner):
    return OppWorkspace.objects.create(
        workspace=ws, slug="spark-facilitator", display_name="Spark", created_by=owner,
        tenancy={"hq_domain": "connect-ace-spark", "ocs_team": "spark"},
    )


def _client(user):
    c = Client()
    c.force_login(user)
    return c


URL = "/api/w/spark/opps/spark-facilitator/tenancy"


# --- read ---------------------------------------------------------------


def test_member_reads_opp_tenancy_with_drive_root(viewer, opp):
    resp = _client(viewer).get(URL)
    assert resp.status_code == 200
    body = resp.json()
    assert body["tenancy"] == {"hq_domain": "connect-ace-spark", "ocs_team": "spark"}
    assert body["drive_root_folder_id"] == "root-spark"
    assert body["source"] == "opp"


def test_opp_without_row_reads_workspace_default(viewer, ws):
    """Drive-only opps (no OppWorkspace row yet) report the default rather
    than 404 — ACE must be able to bind to any opp."""
    resp = _client(viewer).get("/api/w/spark/opps/drive-only/tenancy")
    assert resp.status_code == 200
    assert resp.json()["tenancy"] == {"hq_domain": "connect-ace-spark"}
    assert resp.json()["source"] == "workspace-default"
    assert not OppWorkspace.objects.filter(slug="drive-only").exists()


def test_non_member_gets_404(outsider, opp):
    assert _client(outsider).get(URL).status_code == 404


# --- write --------------------------------------------------------------


def test_owner_patches_and_change_is_audited(owner, opp):
    resp = _client(owner).patch(
        URL,
        {"connect_pm_org": "spark-pm", "ocs_team": None},
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    expected = {
        "hq_domain": "connect-ace-spark",
        "connect_pm_org": "spark-pm",
    }
    assert resp.json()["tenancy"] == expected
    opp.refresh_from_db()
    assert opp.tenancy == expected
    change = TenancyChange.objects.get()
    assert change.opp_slug == "spark-facilitator"
    assert change.changed_by == owner
    assert change.before == {"hq_domain": "connect-ace-spark", "ocs_team": "spark"}
    assert change.after == expected


def test_viewer_cannot_patch(viewer, opp):
    resp = _client(viewer).patch(URL, {"ocs_team": "x"}, content_type="application/json")
    assert resp.status_code == 403
    opp.refresh_from_db()
    assert opp.tenancy["ocs_team"] == "spark"
    assert not TenancyChange.objects.exists()


@pytest.mark.parametrize("body", [
    {"hq_domain": "has space"},
    {"hq_domain": "https://www.commcarehq.org/a/x/"},
    {"labs_allowed_domains": ["@partner.org"]},  # removed 2026-10-08: now an unknown field
    {"unknown_field": "x"},
])
def test_patch_rejects_invalid_values(owner, opp, body):
    resp = _client(owner).patch(URL, body, content_type="application/json")
    assert resp.status_code in (400, 422)
    assert not TenancyChange.objects.exists()


def test_patch_materialises_row_for_drive_only_opp(owner, ws):
    resp = _client(owner).patch(
        "/api/w/spark/opps/drive-only/tenancy", {"ocs_team": "spark"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    row = OppWorkspace.objects.get(workspace=ws, slug="drive-only")
    assert row.tenancy == {"hq_domain": "connect-ace-spark", "ocs_team": "spark"}


def test_workspace_default_patch_is_owner_only_and_audited(owner, viewer, ws, opp):
    denied = _client(viewer).patch(
        "/api/workspaces/spark", {"default_tenancy": {"ocs_team": "x"}},
        content_type="application/json",
    )
    assert denied.status_code == 403
    resp = _client(owner).patch(
        "/api/workspaces/spark", {"default_tenancy": {"ocs_team": "spark"}},
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    assert resp.json()["default_tenancy"] == {"hq_domain": "connect-ace-spark", "ocs_team": "spark"}
    change = TenancyChange.objects.get()
    assert change.opp_slug == ""
    # The default never rewrites existing opps.
    opp.refresh_from_db()
    assert opp.tenancy == {"hq_domain": "connect-ace-spark", "ocs_team": "spark"}


def test_tenancy_changes_appear_in_workspace_activity(owner, opp):
    _client(owner).patch(URL, {"ocs_team": "spark2"}, content_type="application/json")
    items = _client(owner).get("/api/workspaces/spark/activity").json()["items"]
    assert any(i["action"] == "tenancy.changed" and i["subject"] == "spark-facilitator"
               for i in items)


# --- copy on create -----------------------------------------------------


def test_default_is_copied_once_not_linked(owner, ws):
    _client(owner).patch("/api/w/spark/opps/brand-new/tenancy", {},
                         content_type="application/json")
    row = OppWorkspace.objects.get(workspace=ws, slug="brand-new")
    assert row.tenancy == {"hq_domain": "connect-ace-spark"}
    ws.default_tenancy = {"hq_domain": "changed"}
    ws.save()
    row.refresh_from_db()
    assert row.tenancy == {"hq_domain": "connect-ace-spark"}


# --- backfill -----------------------------------------------------------


def test_backfill_fills_only_empty_fields(owner):
    team = Workspace.objects.create(
        slug="dimagi-team", display_name="Dimagi", drive_root_folder_id="root-dt",
        created_by=owner,
    )
    other = Workspace.objects.create(
        slug="other", display_name="Other", drive_root_folder_id="root-o", created_by=owner,
    )
    blank = OppWorkspace.objects.create(workspace=team, slug="a", display_name="A",
                                        created_by=owner)
    edited = OppWorkspace.objects.create(workspace=other, slug="b", display_name="B",
                                         created_by=owner, tenancy={"ocs_team": "mine"})

    migration = importlib.import_module("apps.opps.migrations.0006_backfill_shared_tenancy")
    migration.backfill(django_apps, None)

    blank.refresh_from_db()
    edited.refresh_from_db()
    team.refresh_from_db()
    other.refresh_from_db()
    # 0006 predates the removal of labs_allowed_domains, so it still seeds it;
    # 0008 strips it again (test below).
    seeded = {**SHARED, "labs_allowed_domains": ["@dimagi.com", "@dimagi-ai.com"]}
    assert blank.tenancy == seeded
    assert edited.tenancy == {**seeded, "ocs_team": "mine"}
    assert team.default_tenancy == seeded
    assert other.default_tenancy == {}
    assert "connect_pm_org" not in blank.tenancy


def test_pm_org_backfill_fills_only_empty(owner):
    team = Workspace.objects.create(
        slug="dimagi-team", display_name="Dimagi", drive_root_folder_id="root-dt",
        created_by=owner,
    )
    blank = OppWorkspace.objects.create(workspace=team, slug="a", display_name="A",
                                        created_by=owner, tenancy={"hq_domain": "x"})
    edited = OppWorkspace.objects.create(workspace=team, slug="b", display_name="B",
                                         created_by=owner,
                                         tenancy={"connect_pm_org": "ai-demo-space"})
    migration = importlib.import_module("apps.opps.migrations.0007_backfill_connect_pm_org")
    migration.backfill(django_apps, None)
    blank.refresh_from_db()
    edited.refresh_from_db()
    team.refresh_from_db()
    assert blank.tenancy == {"hq_domain": "x", "connect_pm_org": "ace-pm-org"}
    assert edited.tenancy == {"connect_pm_org": "ai-demo-space"}
    assert team.default_tenancy == {"connect_pm_org": "ace-pm-org"}


def test_drop_labs_allowed_domains_strips_only_that_key(owner):
    team = Workspace.objects.create(
        slug="dimagi-team", display_name="Dimagi", drive_root_folder_id="root-dt",
        created_by=owner, default_tenancy={**SHARED, "labs_allowed_domains": ["@dimagi.com"]},
    )
    opp = OppWorkspace.objects.create(
        workspace=team, slug="a", display_name="A", created_by=owner,
        tenancy={**SHARED, "labs_allowed_domains": ["@partner.org"]},
    )
    untouched = OppWorkspace.objects.create(
        workspace=team, slug="b", display_name="B", created_by=owner, tenancy={"ocs_team": "x"},
    )

    migration = importlib.import_module("apps.opps.migrations.0008_drop_labs_allowed_domains")
    migration.strip(django_apps, None)

    opp.refresh_from_db()
    team.refresh_from_db()
    untouched.refresh_from_db()
    assert opp.tenancy == SHARED
    assert team.default_tenancy == SHARED
    assert untouched.tenancy == {"ocs_team": "x"}
