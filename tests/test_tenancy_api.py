"""Per-opp tenancy: model rules, API, copy-on-create.

Spec: docs/specs/2026-09-28-clone-and-release-design.md § Tenancy, § B.
"""

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.models import OppWorkspace
from apps.workspaces.models import TenancyChange, Workspace, WorkspaceMembership

pytestmark = pytest.mark.django_db


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


# --- connect_program_ids (ace-web#914) ------------------------------------
#
# ACE's tenancy guard checks every program-scoped labs write (solicitations,
# supply chain) against this list, and labs keeps no delete for most
# supply-chain records — so the shape is pinned here.


def test_owner_sets_connect_program_ids_and_read_serves_them(owner, viewer, opp):
    resp = _client(owner).patch(URL, {"connect_program_ids": [355, 308, 355]},
                                content_type="application/json")
    assert resp.status_code == 200, resp.content
    # Deduped and sorted: one representation per set of programs.
    assert resp.json()["tenancy"]["connect_program_ids"] == [308, 355]
    assert _client(viewer).get(URL).json()["tenancy"]["connect_program_ids"] == [308, 355]
    change = TenancyChange.objects.get()
    assert change.after["connect_program_ids"] == [308, 355]


def test_unset_connect_program_ids_is_absent_not_empty(viewer, opp):
    """ACE reads an ABSENT key as "not set up"; the read must not invent []."""
    assert "connect_program_ids" not in _client(viewer).get(URL).json()["tenancy"]


@pytest.mark.parametrize("clear", [None, []])
def test_null_or_empty_list_clears_connect_program_ids(owner, opp, clear):
    _client(owner).patch(URL, {"connect_program_ids": [308]}, content_type="application/json")
    resp = _client(owner).patch(URL, {"connect_program_ids": clear},
                                content_type="application/json")
    assert resp.status_code == 200, resp.content
    assert "connect_program_ids" not in resp.json()["tenancy"]
    opp.refresh_from_db()
    assert "connect_program_ids" not in opp.tenancy


def test_patch_replaces_the_program_list(owner, opp):
    _client(owner).patch(URL, {"connect_program_ids": [308]}, content_type="application/json")
    resp = _client(owner).patch(URL, {"connect_program_ids": [412]},
                                content_type="application/json")
    assert resp.json()["tenancy"]["connect_program_ids"] == [412]


def test_unchanged_program_list_is_not_audited(owner, opp):
    _client(owner).patch(URL, {"connect_program_ids": [308, 355]},
                         content_type="application/json")
    _client(owner).patch(URL, {"connect_program_ids": [355, 308]},
                         content_type="application/json")
    assert TenancyChange.objects.count() == 1


@pytest.mark.parametrize("ids", [
    [0], [-4], ["308"], [True], [1.5], "308", [{"id": 308}], list(range(1, 52)),
])
def test_patch_rejects_bad_program_ids(owner, opp, ids):
    resp = _client(owner).patch(URL, {"connect_program_ids": ids},
                                content_type="application/json")
    assert resp.status_code in (400, 422), resp.content
    assert not TenancyChange.objects.exists()


def test_workspace_default_cannot_carry_program_ids(owner, ws):
    """A program belongs to ONE opp; every new opp copies the default."""
    resp = _client(owner).patch(
        "/api/workspaces/spark", {"default_tenancy": {"connect_program_ids": [308]}},
        content_type="application/json",
    )
    assert resp.status_code == 400
    ws.refresh_from_db()
    assert "connect_program_ids" not in ws.default_tenancy
    assert not TenancyChange.objects.exists()


# --- backfill from opp.yaml ---------------------------------------------


def _drive(tree):
    from apps.opps.tests.fixtures.fake_drive import FakeDriveClient

    return FakeDriveClient.from_tree({"root": tree})


def _ws_on(drive, ws):
    ws.drive_root_folder_id = drive.folder_id("root")
    ws.save(update_fields=["drive_root_folder_id"])
    return ws


PROGRAM_YAML = "slug: {slug}\nconnect:\n  program:\n    id: 7c1e\n    connect_int_id: {pid}\n"


def test_backfill_dry_run_reports_and_writes_nothing(owner, ws, opp):
    from apps.opps.tenancy_backfill import backfill_workspace

    drive = _drive({
        "spark-facilitator": {"opp.yaml": PROGRAM_YAML.format(slug="spark", pid=308)},
        "pre-phase-4": {"opp.yaml": "slug: pre-phase-4\n"},
        "_archive": {"opp.yaml": PROGRAM_YAML.format(slug="old", pid=9)},
        "Projects": {"notes.md": "x"},
    })
    results = backfill_workspace(_ws_on(drive, ws), drive, apply=False)
    assert {(r.slug, r.action) for r in results} == {
        ("spark-facilitator", "would-set"), ("pre-phase-4", "no-program"),
    }
    opp.refresh_from_db()
    assert "connect_program_ids" not in opp.tenancy
    assert not TenancyChange.objects.exists()


def test_backfill_apply_fills_empty_only_and_audits(owner, ws, opp):
    from apps.opps.tenancy_backfill import backfill_workspace

    OppWorkspace.objects.create(
        workspace=ws, slug="owner-set", display_name="x", created_by=owner,
        tenancy={"hq_domain": "h", "connect_program_ids": [500]},
    )
    drive = _drive({
        "spark-facilitator": {"opp.yaml": PROGRAM_YAML.format(slug="spark", pid=308)},
        "owner-set": {"opp.yaml": PROGRAM_YAML.format(slug="owner-set", pid=999)},
        "drive-only": {"opp.yaml": PROGRAM_YAML.format(slug="drive-only", pid="'412'")},
    })
    results = {r.slug: r.action for r in
               backfill_workspace(_ws_on(drive, ws), drive, apply=True, user=owner)}
    assert results == {"spark-facilitator": "set", "owner-set": "already-set",
                       "drive-only": "set"}
    opp.refresh_from_db()
    assert opp.tenancy == {"hq_domain": "connect-ace-spark", "ocs_team": "spark",
                           "connect_program_ids": [308]}
    # An owner's edit wins.
    assert OppWorkspace.objects.get(slug="owner-set").tenancy["connect_program_ids"] == [500]
    # A Drive-only opp gets a row seeded from the workspace default, like a PATCH.
    assert OppWorkspace.objects.get(slug="drive-only").tenancy == {
        "hq_domain": "connect-ace-spark", "connect_program_ids": [412],
    }
    assert TenancyChange.objects.filter(changed_by=owner).count() == 2
    # Re-running is a no-op.
    again = backfill_workspace(ws, drive, apply=True, user=owner)
    assert {r.action for r in again} == {"already-set"}
    assert TenancyChange.objects.count() == 2


def test_backfill_apply_requires_an_attributed_user(ws):
    from apps.opps.tenancy_backfill import backfill_workspace

    drive = _drive({})
    with pytest.raises(ValueError):
        backfill_workspace(_ws_on(drive, ws), drive, apply=True)


@pytest.mark.parametrize("raw,expected", [
    ({"connect": {"program": {"connect_int_id": 308}}}, 308),
    ({"connect": {"program": {"connect_int_id": "308"}}}, 308),
    ({"connect": {"program": {"connect_int_id": 0}}}, None),
    ({"connect": {"program": {"connect_int_id": True}}}, None),
    ({"connect": {"program": {"id": "uuid-only"}}}, None),
    ({"connect": {"program": "not-a-dict"}}, None),
    ({}, None),
])
def test_program_id_from_opp_yaml(raw, expected):
    from apps.opps.tenancy_backfill import program_id_from_opp_yaml

    assert program_id_from_opp_yaml(raw) == expected
