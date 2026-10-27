"""Archiving a run hides it from the default views and touches nothing else."""
import pytest
from django.contrib.auth import get_user_model

from apps.opps import archive
from apps.opps.models import ArchivedRun
from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()

URL = "/api/w/ws1/opps/smallholder/runs/20261012-1549/archive"
URL2 = "/api/w/ws1/opps/smallholder/runs/20261014-0859/archive"
_RUNS = [
    {"run_id": "20261012-1549", "lifecycle_status": "complete"},
    {"run_id": "20261014-0859", "lifecycle_status": "complete"},
    {"run_id": "20261015-1402", "lifecycle_status": "complete"},
]


def _client(db, client, role="editor"):
    ws = Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator@example.com"),
    )
    user = User.objects.create_user(email="a@example.com")
    WorkspaceMembership.objects.create(workspace=ws, user=user, role=role)
    client.force_login(user)
    return client, ws, user


@pytest.fixture
def ctx(db, client, monkeypatch):
    monkeypatch.setattr(
        "apps.opps.api.list_opp_runs_for_workspace", lambda workspace, slug: list(_RUNS)
    )
    return _client(db, client)


def _ids(resp):
    return [r["run_id"] for r in resp.json()["items"]]


def test_archived_runs_leave_the_default_list_but_stay_listable(ctx):
    client, ws, _ = ctx
    assert client.post(URL).status_code == 204
    assert client.post(URL2).status_code == 204

    assert _ids(client.get("/api/w/ws1/opps/smallholder/runs")) == ["20261015-1402"]
    assert client.get("/api/w/ws1/opps/smallholder/runs").json()["total"] == 1
    assert _ids(client.get("/api/w/ws1/opps/smallholder/runs?archived=only")) == [
        "20261012-1549", "20261014-0859",
    ]
    assert len(_ids(client.get("/api/w/ws1/opps/smallholder/runs?archived=include"))) == 3


def test_archive_is_idempotent_and_records_who(ctx):
    client, ws, user = ctx
    for _ in range(2):
        assert client.post(URL).status_code == 204
    row = ArchivedRun.objects.get()
    assert (row.opp_slug, row.run_id, row.archived_by) == ("smallholder", "20261012-1549", user)


def test_unarchive_restores_the_run_and_404s_when_not_archived(ctx):
    client, ws, _ = ctx
    client.post(URL)
    assert client.delete(URL).status_code == 204
    assert len(_ids(client.get("/api/w/ws1/opps/smallholder/runs"))) == 3
    assert client.delete(URL).status_code == 404


def test_archive_is_scoped_to_the_opp(ctx):
    client, ws, _ = ctx
    client.post(URL)
    # Same run id under another opp is a different run.
    assert len(_ids(client.get("/api/w/ws1/opps/other/runs"))) == 3


def test_archive_page_lists_across_opps(ctx):
    client, ws, user = ctx
    client.post(URL)
    client.post("/api/w/ws1/opps/other/runs/20261014-0859/archive")
    body = client.get("/api/w/ws1/opps/archived-runs").json()
    assert {(i["opp_slug"], i["run_id"]) for i in body["items"]} == {
        ("smallholder", "20261012-1549"), ("other", "20261014-0859"),
    }
    assert body["items"][0]["archived_by"] == "a@example.com"


def test_viewer_cannot_archive(db, client):
    client, ws, _ = _client(db, client, role="viewer")
    assert client.post(URL).status_code == 403
    assert not ArchivedRun.objects.exists()


def test_non_member_cannot_archive_or_list(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator@example.com"),
    )
    client.force_login(User.objects.create_user(email="b@example.com"))
    assert client.post("/api/w/ws1/opps/smallholder/runs/x/archive").status_code == 404
    assert client.get("/api/w/ws1/opps/archived-runs").status_code == 404


def test_hide_archived_runs_filters_snapshot_but_names_the_hidden(db):
    from apps.opps.api import _hide_archived_runs

    ws = Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="f",
        created_by=User.objects.create_user(email="c@example.com"),
    )
    archive.archive_run(ws, "smallholder", "r1", None)
    out = _hide_archived_runs(
        ws, "smallholder", {"runs": [{"run_id": "r1"}, {"run_id": "r2"}]}
    )
    assert [r["run_id"] for r in out["runs"]] == ["r2"]
    assert out["archived_run_ids"] == ["r1"]
