"""clone-to-new-workspace, the ace-web half: copy one run whole into another
workspace's Drive root, and record it.

Spec: docs/specs/2026-09-28-clone-and-release-design.md § C.
"""
import datetime as dt

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.models import OppWorkspace
from apps.opps.run_cloner import CloneError, clone_run
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.workspaces.models import RunClone, Workspace, WorkspaceMembership

pytestmark = pytest.mark.django_db

RUN = "20260926-1413"


def _tree():
    return {
        "DT": {
            "spark-facilitator": {
                "opp.yaml": "slug: spark-facilitator\n",
                "pdd.md": "# PDD\n",
                "inputs": {"brief.md": "brief"},
                # ACE's internal working state at the opp root — never cloned.
                "open-questions.md": "internal",
                "eval-calibration": {"known-issues.md": "internal"},
                "inbox-triage_comms-log": "internal",
                "Spark — parked outbound draft for Anne": "internal",
                "runs": {
                    RUN: {
                        "run_state.yaml": "opportunity: spark-facilitator\n",
                        "decisions.yaml": "rows: []\n",
                        "6-qa-and-training": {
                            "screenshots": {"s1.png": "png"},
                            "videos": {"v1.mp4": "mp4"},
                            "guide.md": "guide",
                        },
                        "notes-unrecognised": {"x.md": "x"},
                        # ACE's email records — never cloned, at any depth.
                        "comms-log": {"llo-invite.md": "internal"},
                        "8-solicitation-management": {
                            "solicitation.md": "s",
                            "llo-invite_comms-log": "internal",
                        },
                    },
                    "20260920-0900": {"run_state.yaml": "old run\n"},
                },
            },
        },
        "SPARK": {},
    }


@pytest.fixture
def owner():
    return User.objects.create(email="owner@dimagi.com", display_name="Owner")


@pytest.fixture
def drive():
    return FakeDriveClient.from_tree(_tree())


@pytest.fixture
def source_ws(owner, drive):
    ws = Workspace.objects.create(
        slug="dimagi-team", display_name="Dimagi", created_by=owner,
        drive_root_folder_id=drive.folder_id("DT"),
    )
    WorkspaceMembership.objects.create(workspace=ws, user=owner, role="owner")
    OppWorkspace.objects.create(
        workspace=ws, slug="spark-facilitator", display_name="Spark Facilitator",
        created_by=owner, tenancy={"hq_domain": "connect-ace-prod"},
    )
    return ws


@pytest.fixture
def target_ws(owner, drive):
    ws = Workspace.objects.create(
        slug="spark", display_name="Spark", created_by=owner,
        drive_root_folder_id=drive.folder_id("SPARK"),
        default_tenancy={"hq_domain": "connect-ace-spark", "ocs_team": "spark"},
    )
    WorkspaceMembership.objects.create(workspace=ws, user=owner, role="owner")
    return ws


def _names(drive, path):
    return sorted(f.name for f in drive.list_files(drive.folder_id(path)))


def test_copies_the_whole_run_and_the_opp_files(drive, source_ws, target_ws, owner):
    result = clone_run(drive=drive, source=source_ws, target=target_ws,
                       opp_slug="spark-facilitator", run_id=RUN, owner=owner)

    assert _names(drive, "SPARK/spark-facilitator") == ["inputs", "opp.yaml", "pdd.md", "runs"]
    assert _names(drive, "SPARK/spark-facilitator/inputs") == ["brief.md"]
    # Only the cloned run, under the same run id.
    assert _names(drive, "SPARK/spark-facilitator/runs") == [RUN]
    # Whole run, verbatim — reviewers need the screenshots and videos.
    assert _names(drive, f"SPARK/spark-facilitator/runs/{RUN}") == [
        "6-qa-and-training", "8-solicitation-management", "decisions.yaml",
        "notes-unrecognised", "run_state.yaml",
    ]
    # Comms-logs stay behind: internal, and ACE routes inbound mail by the
    # thread ids in them — a clone carrying them would steal the source's threads.
    assert _names(drive, f"SPARK/spark-facilitator/runs/{RUN}/8-solicitation-management") == [
        "solicitation.md",
    ]
    assert _names(drive, f"SPARK/spark-facilitator/runs/{RUN}/6-qa-and-training") == [
        "guide.md", "screenshots", "videos",
    ]
    assert result.files_copied == 10
    # The source is untouched.
    assert _names(drive, "DT/spark-facilitator/runs") == ["20260920-0900", RUN]


def test_records_clone_and_target_opp_takes_target_default(drive, source_ws, target_ws, owner):
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id=RUN, owner=owner)
    row = OppWorkspace.objects.get(workspace=target_ws, slug="spark-facilitator")
    assert row.tenancy == {"hq_domain": "connect-ace-spark", "ocs_team": "spark"}
    assert row.display_name == "Spark Facilitator"
    clone = RunClone.objects.get()
    assert (clone.source_workspace_id, clone.target_workspace_id) == ("dimagi-team", "spark")
    assert clone.opp_slug == "spark-facilitator"
    assert clone.run_id == RUN
    assert clone.status == "done"
    assert clone.created_by == owner


def test_internal_opp_level_files_are_not_cloned(drive, source_ws, target_ws, owner):
    # The live spark-facilitator root held exactly these: a reviewer-facing
    # clone must not carry ACE's notes, comms-log, or an unsent draft to them.
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id=RUN, owner=owner)
    names = _names(drive, "SPARK/spark-facilitator")
    for internal in ("open-questions.md", "eval-calibration", "inbox-triage_comms-log",
                     "Spark — parked outbound draft for Anne"):
        assert internal not in names


def test_second_run_of_same_opp_reuses_the_opp_folder(drive, source_ws, target_ws, owner):
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id=RUN, owner=owner)
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id="20260920-0900", owner=owner)
    assert _names(drive, "SPARK") == ["spark-facilitator"]
    assert _names(drive, "SPARK/spark-facilitator") == ["inputs", "opp.yaml", "pdd.md", "runs"]
    assert _names(drive, "SPARK/spark-facilitator/runs") == ["20260920-0900", RUN]


def test_refuses_a_run_already_in_the_target(drive, source_ws, target_ws, owner):
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id=RUN, owner=owner)
    with pytest.raises(CloneError) as exc:
        clone_run(drive=drive, source=source_ws, target=target_ws,
                  opp_slug="spark-facilitator", run_id=RUN, owner=owner)
    assert exc.value.code == "already-cloned"


@pytest.mark.parametrize("opp,run,code", [
    ("nope", RUN, "source-not-found"),
    ("spark-facilitator", "20990101-0000", "source-run-not-found"),
])
def test_missing_source(drive, source_ws, target_ws, owner, opp, run, code):
    with pytest.raises(CloneError) as exc:
        clone_run(drive=drive, source=source_ws, target=target_ws,
                  opp_slug=opp, run_id=run, owner=owner)
    assert exc.value.code == code


def test_same_workspace_is_refused(drive, source_ws, owner):
    with pytest.raises(CloneError) as exc:
        clone_run(drive=drive, source=source_ws, target=source_ws,
                  opp_slug="spark-facilitator", run_id=RUN, owner=owner)
    assert exc.value.code == "same-workspace"


def test_run_state_is_copied_before_anything_else(drive, source_ws, target_ws, owner):
    """Like a fork (ace-web#734): the file that makes a folder a run lands
    first, so a stalled clone is resumable rather than a pile of files."""
    order = []
    real_copy = drive.copy_file

    def spy(file_id, parent, name=None):
        order.append(name)
        return real_copy(file_id, parent, name)

    drive.copy_file = spy
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id=RUN, owner=owner)
    watched = ("run_state.yaml", "decisions.yaml", "guide.md", "s1.png")
    run_files = [n for n in order if n in watched]
    assert run_files[0] == "run_state.yaml"


def test_failed_copy_marks_the_record_errored(drive, source_ws, target_ws, owner):
    def boom(*a, **k):
        raise RuntimeError("drive 500")

    drive.copy_file = boom
    with pytest.raises(RuntimeError):
        clone_run(drive=drive, source=source_ws, target=target_ws,
                  opp_slug="spark-facilitator", run_id=RUN, owner=owner)
    clone = RunClone.objects.get()
    assert clone.status == "error"
    assert "drive 500" in clone.error


# --- endpoint -------------------------------------------------------------

URL = f"/api/w/dimagi-team/opps/spark-facilitator/runs/{RUN}/clone"


@pytest.fixture
def patched_drive(monkeypatch, drive):
    monkeypatch.setattr("apps.opps.clone_api.get_drive_client", lambda workspace=None: drive)
    # Run the background copy inline so endpoint tests see its result.
    monkeypatch.setattr("apps.opps.clone_api._run_in_background", lambda fn: fn())
    return drive


def _client(user):
    c = Client()
    c.force_login(user)
    return c


def test_endpoint_clones_for_an_owner_of_both(patched_drive, source_ws, target_ws, owner):
    resp = _client(owner).post(URL, {"to_workspace": "spark"}, content_type="application/json")
    assert resp.status_code == 202, resp.content
    body = resp.json()
    assert body["target_workspace"] == "spark"
    assert body["run_id"] == RUN
    assert body["status"] == "done"
    listing = _client(owner).get(f"/api/w/dimagi-team/opps/spark-facilitator/runs/{RUN}/clones")
    assert [c["target_workspace"] for c in listing.json()] == ["spark"]


def test_endpoint_hides_a_target_you_are_not_in(patched_drive, source_ws, owner):
    other_owner = User.objects.create(email="x@dimagi.com", display_name="X")
    Workspace.objects.create(slug="secret", display_name="S", created_by=other_owner,
                             drive_root_folder_id="root-secret")
    resp = _client(owner).post(URL, {"to_workspace": "secret"}, content_type="application/json")
    assert resp.status_code == 404
    assert not RunClone.objects.exists()


def test_endpoint_requires_owner_of_the_target(patched_drive, source_ws, target_ws, owner):
    editor = User.objects.create(email="ed@dimagi.com", display_name="Ed")
    WorkspaceMembership.objects.create(workspace=source_ws, user=editor, role="owner")
    WorkspaceMembership.objects.create(workspace=target_ws, user=editor, role="editor")
    resp = _client(editor).post(URL, {"to_workspace": "spark"}, content_type="application/json")
    assert resp.status_code == 403


def test_endpoint_requires_owner_of_the_source(patched_drive, source_ws, target_ws):
    viewer = User.objects.create(email="v@dimagi.com", display_name="V")
    WorkspaceMembership.objects.create(workspace=source_ws, user=viewer, role="viewer")
    WorkspaceMembership.objects.create(workspace=target_ws, user=viewer, role="owner")
    resp = _client(viewer).post(URL, {"to_workspace": "spark"}, content_type="application/json")
    assert resp.status_code == 403


def test_endpoint_maps_already_cloned_to_409(patched_drive, source_ws, target_ws, owner):
    _client(owner).post(URL, {"to_workspace": "spark"}, content_type="application/json")
    again = _client(owner).post(URL, {"to_workspace": "spark"}, content_type="application/json")
    assert again.status_code == 409


def test_endpoint_returns_before_the_copy_runs(monkeypatch, drive, source_ws, target_ws, owner):
    # ace-web#823: the first real clone (347 files, ~14 min) 504'd in-request.
    monkeypatch.setattr("apps.opps.clone_api.get_drive_client", lambda workspace=None: drive)
    pending = []
    monkeypatch.setattr("apps.opps.clone_api._run_in_background", pending.append)
    resp = _client(owner).post(URL, {"to_workspace": "spark"}, content_type="application/json")
    assert resp.status_code == 202
    assert resp.json()["status"] == "copying"
    assert len(pending) == 1
    pending[0]()
    assert RunClone.objects.get().status == "done"


def _age(record, minutes):
    RunClone.objects.filter(pk=record.pk).update(
        updated_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=minutes)
    )


def test_a_stale_copying_clone_is_replaced(patched_drive, source_ws, target_ws, owner):
    _client(owner).post(URL, {"to_workspace": "spark"}, content_type="application/json")
    first = RunClone.objects.get()
    RunClone.objects.filter(pk=first.pk).update(status="copying")
    _age(first, 30)  # its worker died: no progress for 30 min
    again = _client(owner).post(URL, {"to_workspace": "spark"}, content_type="application/json")
    assert again.status_code == 202
    first.refresh_from_db()
    assert first.status == "error" and "abandoned" in first.error
    assert RunClone.objects.order_by("-created_at").first().status == "done"
    assert _names(patched_drive, "SPARK/spark-facilitator/runs") == [RUN]


def test_an_errored_clone_is_replaced(patched_drive, source_ws, target_ws, owner):
    _client(owner).post(URL, {"to_workspace": "spark"}, content_type="application/json")
    RunClone.objects.update(status="error", error="drive 500")
    again = _client(owner).post(URL, {"to_workspace": "spark"}, content_type="application/json")
    assert again.status_code == 202


def test_a_live_copying_clone_is_not_replaced(patched_drive, source_ws, target_ws, owner):
    _client(owner).post(URL, {"to_workspace": "spark"}, content_type="application/json")
    RunClone.objects.update(status="copying")  # fresh: still progressing
    again = _client(owner).post(URL, {"to_workspace": "spark"}, content_type="application/json")
    assert again.status_code == 409


# --- the clone points at its own copies ------------------------------------

SRC_RUN = f"DT/spark-facilitator/runs/{RUN}"


def _state_naming(drive, *paths):
    """Make the SOURCE run_state name files by id, as ACE's does."""
    ids = {p: drive.file_id(f"{SRC_RUN}/{p}") for p in paths}
    body = "".join(f"{p}: https://docs.google.com/document/d/{i}/edit\n" for p, i in ids.items())
    drive.update_file(drive.file_id(f"{SRC_RUN}/run_state.yaml"), body, "text/yaml")
    return ids


def test_state_names_the_copies_not_the_source(drive, source_ws, target_ws, owner):
    # First Spark clone: every doc on the reviewer-facing page opened the
    # SOURCE workspace's file (99 ids / 125 occurrences in run_state).
    src = _state_naming(drive, "6-qa-and-training/guide.md", "decisions.yaml",
                        "comms-log/llo-invite.md")
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id=RUN, owner=owner)
    dst_state = drive.file_id(f"SPARK/spark-facilitator/runs/{RUN}/run_state.yaml")
    text = drive.get_content(dst_state, "text/yaml").content
    guide_copy = drive.file_id(f"SPARK/spark-facilitator/runs/{RUN}/6-qa-and-training/guide.md")
    assert guide_copy in text and src["6-qa-and-training/guide.md"] not in text
    assert src["decisions.yaml"] not in text
    # Not cloned (comms-log), so nothing to point at: left as the source id.
    assert src["comms-log/llo-invite.md"] in text
    # The source run is never written to.
    src_text = drive.get_content(drive.file_id(f"{SRC_RUN}/run_state.yaml"), "text/yaml").content
    assert src["6-qa-and-training/guide.md"] in src_text


def test_copies_keep_their_originals_link_sharing(drive, source_ws, target_ws, owner):
    guide = drive.file_id(f"{SRC_RUN}/6-qa-and-training/guide.md")
    shot = drive.file_id(f"{SRC_RUN}/6-qa-and-training/screenshots/s1.png")
    drive.set_anyone_role(guide, "commenter")
    drive.set_anyone_role(shot, "reader")
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id=RUN, owner=owner)
    base = f"SPARK/spark-facilitator/runs/{RUN}/6-qa-and-training"
    roles = drive.anyone_roles([
        drive.file_id(f"{base}/guide.md"),
        drive.file_id(f"{base}/screenshots/s1.png"),
        drive.file_id(f"{base}/videos/v1.mp4"),
    ])
    assert list(roles.values()) == ["commenter", "reader", None]
