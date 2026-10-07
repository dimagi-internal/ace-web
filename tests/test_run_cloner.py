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
                # LEGACY ask stores — never cloned. A run's open asks are a
                # filter of its own decisions.yaml (operator 2026-10-07).
                "open-questions.md": "- **Rate?** Owner: LLO.\n",
                "open-asks.yaml": "schema_version: 1\nasks: []\n",
                # ACE's internal working state at the opp root — never cloned.
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

    assert _names(drive, "SPARK/spark-facilitator") == [
        "inputs", "opp.yaml", "pdd.md", "runs",
    ]
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
    for internal in ("eval-calibration", "inbox-triage_comms-log",
                     "Spark — parked outbound draft for Anne"):
        assert internal not in names


def test_no_legacy_ask_store_is_cloned(drive, source_ws, target_ws, owner):
    # How a never-migrated spark-facilitator ledger reached the `spark`
    # workspace's review page. The new system carries no legacy model: the
    # run's open asks are a filter of its decisions.yaml, copied with the run.
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id=RUN, owner=owner)
    names = _names(drive, "SPARK/spark-facilitator")
    assert "open-questions.md" not in names
    assert "open-asks.yaml" not in names
    assert "decisions.yaml" in _names(drive, f"SPARK/spark-facilitator/runs/{RUN}")


def test_second_run_of_same_opp_reuses_the_opp_folder(drive, source_ws, target_ws, owner):
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id=RUN, owner=owner)
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id="20260920-0900", owner=owner)
    assert _names(drive, "SPARK") == ["spark-facilitator"]
    assert _names(drive, "SPARK/spark-facilitator") == [
        "inputs", "opp.yaml", "pdd.md", "runs",
    ]
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


# --- the clone's preview indexes point at its own frames (ace-web#851) -------

SHOTS = "6-qa-and-training/screenshots"
PREVIEWS = "4-connect/previews/connect-opportunity"
MANIFEST = "6-qa-and-training/app-screenshot-capture_manifest.yaml"
DST_RUN = f"SPARK/spark-facilitator/runs/{RUN}"


@pytest.fixture
def previews_drive(drive):
    """Give the SOURCE run a previews folder and a Phase 6 capture manifest that
    name their frames by id, as ACE's capture skills write them."""
    run = drive.folder_id(SRC_RUN)
    phase = drive.create_folder(run, "4-connect")
    pfolder = drive.create_folder(drive.create_folder(phase, "previews"), "connect-opportunity")
    overview = drive.upload_file(pfolder, "01-overview.png", "png", "image/png")
    verification = drive.upload_file(pfolder, "02-verification.png", "png", "image/png")
    drive.upload_file(pfolder, "_previews.yaml", (
        "captured_by: output-preview-capture\n"
        "phase: connect-setup\n"
        "output_key: connect.opportunity\n"
        "items:\n"
        f"  - file_id: {overview}\n    name: 01-overview.png\n"
        f"  - file_id: {verification}\n    name: 02-verification.png\n"
    ), "application/x-yaml")
    shot = drive.file_id(f"{SRC_RUN}/{SHOTS}/s1.png")
    drive.upload_file(drive.folder_id(f"{SRC_RUN}/6-qa-and-training"),
                      "app-screenshot-capture_manifest.yaml", (
        "journeys:\n  - journey_id: journey-learn-pass\n    app: learn\n    status: pass\n"
        f"captures:\n  - journey_id: journey-learn-pass\n    file_id: {shot}\n"
    ), "application/x-yaml")
    return drive


def _text(drive, path):
    return drive.get_content(drive.file_id(path), "application/x-yaml").content


def _names_id(text, file_id):
    """Whole-id match: fake ids are ``fake-N``, so ``fake-5`` is inside ``fake-55``."""
    import re
    return re.search(rf"(?<![\w-]){re.escape(file_id)}(?![\w-])", text) is not None


def test_preview_indexes_name_the_clones_own_frames(previews_drive, source_ws, target_ws, owner):
    # The first Spark clone showed no screenshots for any of 12 outputs: every
    # copied _previews.yaml still named the SOURCE run's frames, and the viewer
    # drops an id outside the run's own tree.
    drive = previews_drive
    src_overview = drive.file_id(f"{SRC_RUN}/{PREVIEWS}/01-overview.png")
    src_shot = drive.file_id(f"{SRC_RUN}/{SHOTS}/s1.png")
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id=RUN, owner=owner)

    index = _text(drive, f"{DST_RUN}/{PREVIEWS}/_previews.yaml")
    assert _names_id(index, drive.file_id(f"{DST_RUN}/{PREVIEWS}/01-overview.png"))
    assert _names_id(index, drive.file_id(f"{DST_RUN}/{PREVIEWS}/02-verification.png"))
    assert not _names_id(index, src_overview)
    # The rest of the index is what was copied.
    assert index.startswith("captured_by: output-preview-capture\nphase: connect-setup\n")

    manifest = _text(drive, f"{DST_RUN}/{MANIFEST}")
    assert _names_id(manifest, drive.file_id(f"{DST_RUN}/{SHOTS}/s1.png"))
    assert not _names_id(manifest, src_shot)

    # And the viewer now shows them: what ace-web reads off the clone.
    from apps.opps.output_previews import load_output_previews
    records = load_output_previews(drive, drive.folder_id(DST_RUN))
    by_source = {r["source"]: r for r in records}
    assert [i["name"] for i in by_source["index"]["items"]] == [
        "01-overview.png", "02-verification.png",
    ]
    assert len(by_source["legacy"]["items"]) == 1


def test_preview_rewrite_leaves_the_source_and_uncopied_ids_alone(
    previews_drive, source_ws, target_ws, owner
):
    # Negative control: the source index is never written, and an id the clone
    # deliberately leaves behind (a comms-log) has no copy to point at.
    drive = previews_drive
    left_behind = drive.file_id(f"{SRC_RUN}/comms-log/llo-invite.md")
    src_index = f"{SRC_RUN}/{PREVIEWS}/_previews.yaml"
    drive.update_file(drive.file_id(src_index),
                      _text(drive, src_index) + f"note_id: {left_behind}\n", "application/x-yaml")
    before = _text(drive, src_index)
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id=RUN, owner=owner)
    assert _text(drive, src_index) == before
    copied = _text(drive, f"{DST_RUN}/{PREVIEWS}/_previews.yaml")
    assert f"note_id: {left_behind}\n" in copied
    # A copied index keeps its own media type (it is a plain YAML file, not a Doc).
    f = next(f for f in drive.list_files(drive.folder_id(f"{DST_RUN}/{PREVIEWS}"))
             if f.name == "_previews.yaml")
    assert f.mime_type == "application/x-yaml"


# --- markdown companions and Google Docs point at the copies (ace#2607) -----

DOC_MIME = "application/vnd.google-apps.document"
GUIDE = "6-qa-and-training/guide.md"
TRAINING = f"{SRC_RUN}/6-qa-and-training"


def _url(file_id):
    return f"https://docs.google.com/document/d/{file_id}/edit"


def test_markdown_copy_names_the_copies_and_keeps_its_type(drive, source_ws, target_ws, owner):
    # Live: training-onboarding-email.md and the guides' .source.md linked the
    # SOURCE run's FAQ, deck and screenshots — 23 ids in the FLW guide alone.
    guide = drive.file_id(f"{SRC_RUN}/{GUIDE}")
    shot = drive.file_id(f"{SRC_RUN}/6-qa-and-training/screenshots/s1.png")
    left_behind = drive.file_id(f"{SRC_RUN}/comms-log/llo-invite.md")
    email_src = drive.upload_file(
        drive.folder_id(TRAINING), "training-onboarding-email.md",
        f"See the [guide]({_url(guide)}) and ![s1](https://drive.google.com/file/d/{shot}/view)"
        f"\nThread: {left_behind}\n",
        "text/markdown",
    )
    before = drive.get_content(email_src, "text/markdown").content
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id=RUN, owner=owner)

    path = f"{DST_RUN}/6-qa-and-training/training-onboarding-email.md"
    text = drive.get_content(drive.file_id(path), "text/markdown").content
    assert _names_id(text, drive.file_id(f"{DST_RUN}/{GUIDE}"))
    assert _names_id(text, drive.file_id(f"{DST_RUN}/6-qa-and-training/screenshots/s1.png"))
    assert not _names_id(text, guide) and not _names_id(text, shot)
    # Comms-logs are not cloned, so there is no copy to point at.
    assert _names_id(text, left_behind)
    # Written back as itself, not as YAML.
    f = next(f for f in drive.list_files(drive.folder_id(f"{DST_RUN}/6-qa-and-training"))
             if f.name == "training-onboarding-email.md")
    assert f.mime_type == "text/markdown"
    # The source is never written to.
    assert drive.get_content(email_src, "text/markdown").content == before


def test_google_doc_links_are_retargeted_at_the_copies(drive, source_ws, target_ws, owner):
    # Live: the partner-facing onboarding-email Doc linked the source FAQ, deck
    # and quick reference; the FLW guide Doc hid 23 screenshot links behind
    # link text, where a text export shows no id.
    guide = drive.file_id(f"{SRC_RUN}/{GUIDE}")
    left_behind = drive.file_id(f"{SRC_RUN}/comms-log/llo-invite.md")
    doc_src = drive.upload_file(drive.folder_id(TRAINING), "Training — onboarding email",
                                f"Read the guide.\nGuide id: {guide}\n", DOC_MIME)
    drive.set_doc_links(doc_src, [_url(guide), _url(left_behind)])
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id=RUN, owner=owner)

    doc = drive.file_id(f"{DST_RUN}/6-qa-and-training/Training — onboarding email")
    guide_copy = drive.file_id(f"{DST_RUN}/{GUIDE}")
    assert drive.doc_links(doc) == [_url(guide_copy), _url(left_behind)]
    body = drive.get_content(doc, DOC_MIME).content
    assert _names_id(body, guide_copy) and not _names_id(body, guide)
    # Still a Doc — never flattened by a text write.
    assert drive.get_file(doc).mime_type == DOC_MIME
    # The source Doc is untouched.
    assert drive.doc_links(doc_src) == [_url(guide), _url(left_behind)]
    assert _names_id(drive.get_content(doc_src, DOC_MIME).content, guide)


def test_a_doc_holding_yaml_is_still_written_back_as_yaml(drive, source_ws, target_ws, owner):
    # run_state/decisions/verdicts are often Google Docs named *.yaml: they keep
    # the text path (read, rewrite, write text/yaml) they always had.
    guide = drive.file_id(f"{SRC_RUN}/{GUIDE}")
    decisions = drive.file_id(f"{SRC_RUN}/decisions.yaml")
    drive.update_file(decisions, f"rows:\n  - ref: {guide}\n", DOC_MIME)
    retargeted = []
    drive.retarget_doc_ids = lambda fid, ids: retargeted.append(fid) or 0
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id=RUN, owner=owner)
    copy = drive.file_id(f"{DST_RUN}/decisions.yaml")
    text = drive.get_content(copy, "text/yaml").content
    assert _names_id(text, drive.file_id(f"{DST_RUN}/{GUIDE}"))
    assert drive.get_file(copy).mime_type == "text/yaml"
    assert copy not in retargeted


def test_binaries_and_other_google_types_are_not_read(drive, source_ws, target_ws, owner):
    drive.upload_binary(drive.folder_id(TRAINING), "shot.png", b"\x89PNG", "image/png")
    drive.upload_file(drive.folder_id(TRAINING), "Training Deck", "deck",
                      "application/vnd.google-apps.presentation")
    read = []
    real = drive.get_content

    def spy(file_id, mime_type, **kw):
        read.append(drive.get_file(file_id).name)
        return real(file_id, mime_type, **kw)

    drive.get_content = spy
    clone_run(drive=drive, source=source_ws, target=target_ws,
              opp_slug="spark-facilitator", run_id=RUN, owner=owner)
    assert "shot.png" not in read and "Training Deck" not in read
    assert "guide.md" in read
