"""release, the ace-web half: record that a run was released to reviewers,
and optionally forward the source run's public summary link to it.

Spec: docs/specs/2026-09-28-clone-and-release-design.md § E2 (step 3).
"""
import pytest
from django.test import Client

from apps.auth.models import User
from apps.workspaces.models import RunClone, RunRelease, Workspace, WorkspaceMembership

pytestmark = pytest.mark.django_db

RUN = "20260926-1413"
URL = f"/api/w/spark/opps/spark-facilitator/runs/{RUN}/release"
SOURCE_SUMMARY = f"/api/opps/public/dimagi-team/spark-facilitator/runs/{RUN}/summary"


@pytest.fixture
def owner():
    return User.objects.create(email="owner@dimagi.com", display_name="Owner")


@pytest.fixture
def spaces(owner):
    dt = Workspace.objects.create(slug="dimagi-team", display_name="D", created_by=owner,
                                  drive_root_folder_id="root-dt")
    spark = Workspace.objects.create(slug="spark", display_name="S", created_by=owner,
                                     drive_root_folder_id="root-spark")
    for ws in (dt, spark):
        WorkspaceMembership.objects.create(workspace=ws, user=owner, role="owner")
    return dt, spark


@pytest.fixture
def clone(spaces, owner):
    dt, spark = spaces
    return RunClone.objects.create(source_workspace=dt, target_workspace=spark,
                                   opp_slug="spark-facilitator", run_id=RUN, status="done",
                                   created_by=owner)


def _client(user):
    c = Client()
    c.force_login(user)
    return c


def test_release_records_reviewers_and_is_idempotent(spaces, owner):
    c = _client(owner)
    r1 = c.post(URL, {"reviewers": ["Anne@SparkMicrogrants.org"]}, content_type="application/json")
    assert r1.status_code == 200, r1.content
    r2 = c.post(URL, {"reviewers": ["sasha@sparkmicrogrants.org"]},
                content_type="application/json")
    assert r2.status_code == 200
    body = r2.json()
    assert body["reviewers"] == ["anne@sparkmicrogrants.org", "sasha@sparkmicrogrants.org"]
    assert body["forwards_from"] is None
    assert RunRelease.objects.count() == 1
    assert c.get(URL).json()["reviewers"] == body["reviewers"]


def test_forward_needs_a_finished_clone(spaces, owner):
    resp = _client(owner).post(URL, {"forward_source": True}, content_type="application/json")
    assert resp.status_code == 400


def test_forward_redirects_the_source_public_summary(clone, owner):
    resp = _client(owner).post(URL, {"forward_source": True}, content_type="application/json")
    assert resp.status_code == 200, resp.content
    assert resp.json()["forwards_from"] == {
        "workspace": "dimagi-team", "opp_slug": "spark-facilitator", "run_id": RUN,
    }
    anon = Client().get(SOURCE_SUMMARY)
    assert anon.status_code == 308
    assert anon["Location"].endswith(
        f"/api/opps/public/spark/spark-facilitator/runs/{RUN}/summary"
    )


def test_unforwarded_source_summary_is_not_redirected(clone, owner, monkeypatch):
    _client(owner).post(URL, {"reviewers": ["a@b.org"]}, content_type="application/json")
    sentinel = {"ok": True}
    monkeypatch.setattr("apps.opps.summary.build_summary_payload", lambda *a, **k: sentinel)
    monkeypatch.setattr("apps.opps.drive_client.get_drive_client", lambda workspace=None: object())
    resp = Client().get(SOURCE_SUMMARY)
    assert resp.status_code == 200


def test_forward_can_be_turned_off(clone, owner):
    c = _client(owner)
    c.post(URL, {"forward_source": True}, content_type="application/json")
    c.post(URL, {"forward_source": False}, content_type="application/json")
    assert RunRelease.objects.get().forwards_from is None


def test_release_is_owner_only(spaces, owner):
    dt, spark = spaces
    editor = User.objects.create(email="ed@dimagi.com", display_name="Ed")
    WorkspaceMembership.objects.create(workspace=spark, user=editor, role="editor")
    assert _client(editor).post(URL, {"reviewers": []},
                                content_type="application/json").status_code == 403
    outsider = User.objects.create(email="o@dimagi.com", display_name="O")
    assert _client(outsider).post(URL, {"reviewers": []},
                                  content_type="application/json").status_code == 404


def test_source_clone_listing_says_the_link_forwards(clone, owner):
    listing = f"/api/w/dimagi-team/opps/spark-facilitator/runs/{RUN}/clones"
    assert _client(owner).get(listing).json()[0]["forwards_public_link"] is False
    _client(owner).post(URL, {"forward_source": True}, content_type="application/json")
    assert _client(owner).get(listing).json()[0]["forwards_public_link"] is True
