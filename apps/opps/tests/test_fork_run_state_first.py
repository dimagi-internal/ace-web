"""Regression tests for dimagi-internal/ace-web#734.

A phase-level fork copied every artifact folder and then stalled without
ever writing ``run_state.yaml``, leaving a folder that is not a run —
``/ace:run <opp>/<run-id>`` derives execution order from
``run_state.yaml.phases.*.status``, so there was nothing to resume. The
companion ``fork/status`` endpoint reported ``unknown`` on every poll
while folders were visibly landing in Drive, so a caller whose POST hung
could not even learn which run had been created.

Three independent defects, one test class each:

1. ``run_state.yaml`` was written LAST, after the whole bulk copy.
2. Every payload the forker emitted through ``progress_cb`` used key
   names (``copied`` / ``total`` / ``current`` / ``opp_slug``) that the
   strict ``ForkProgress`` response schema rejects — the status endpoint
   could never have reported anything but ``unknown``.
3. The POST wrote progress under ``…:<source_run_id>`` while a poll that
   omitted ``?source_run_id=`` read ``…:_latest``.
"""
from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

import pytest
import yaml

from apps.opps.opp_forker import fork_opp
from apps.opps.schemas import ForkProgress

FOLDER_MIME = "application/vnd.google-apps.folder"


class _FakeFile:
    def __init__(self, id, name, mime_type, size=None):
        self.id = id
        self.name = name
        self.mime_type = mime_type
        self.size = size


def _build_drive(*, call_log: list[tuple[str, str]], fail_on_copy_after: int | None = None):
    """Fake DriveClient over ace-root → src-opp → runs → one source run
    holding two phase folders (each with one artifact) + decisions.yaml.

    Every mutating call appends ``(op, name)`` to ``call_log`` so a test
    can assert ORDER, which is the whole point of #734's first defect.
    """
    decisions_body = yaml.safe_dump({"schema_version": 2, "decisions": []})
    files = {
        "ace-root": [_FakeFile("src-opp", "src-opp", FOLDER_MIME)],
        "src-opp": [_FakeFile("runs", "runs", FOLDER_MIME)],
        "runs": [_FakeFile("run-src", "20260101-1000", FOLDER_MIME)],
        "run-src": [
            _FakeFile("p1", "1-design-review", FOLDER_MIME),
            _FakeFile("dec-src", "decisions.yaml", "text/yaml", size=len(decisions_body)),
        ],
        "p1": [
            _FakeFile("a1", "pdd.md", "text/markdown", size=10),
            _FakeFile("a2", "notes.md", "text/markdown", size=10),
        ],
    }
    ids = iter(f"new-{i}" for i in range(200))
    copies = {"n": 0}

    drive = MagicMock()
    drive.list_files.side_effect = lambda fid: files.get(fid, [])

    def _create_folder(parent, name):
        call_log.append(("create_folder", name))
        return next(ids)

    def _copy_file(src_id, dest_parent, name):
        copies["n"] += 1
        if fail_on_copy_after is not None and copies["n"] > fail_on_copy_after:
            raise RuntimeError("drive copy stalled")
        call_log.append(("copy_file", name))
        return next(ids)

    def _upload_file(parent, name, body, mime):
        call_log.append(("upload_file", name))
        return next(ids)

    def _update_file(fid, body, mime):
        call_log.append(("update_file", fid))
        return fid

    drive.create_folder.side_effect = _create_folder
    drive.copy_file.side_effect = _copy_file
    drive.upload_file.side_effect = _upload_file
    drive.update_file.side_effect = _update_file
    drive.get_content.side_effect = lambda fid, mime: MagicMock(
        content=decisions_body if fid == "dec-src" else "",
    )
    return drive


def _stub_session(monkeypatch):
    monkeypatch.setattr(
        "apps.opps.opp_forker.Session.create_with_owner",
        classmethod(lambda cls, **kw: MagicMock(id=1, pk=1, slug="s")),
    )
    monkeypatch.setattr(
        "apps.opps.opp_forker.Message.objects.create", lambda **kw: MagicMock(),
    )


def _fork(drive, monkeypatch, **kw):
    _stub_session(monkeypatch)
    owner = MagicMock()
    owner.email = "someone@dimagi.com"
    return fork_opp(
        drive=drive,
        ace_root_folder_id="ace-root",
        owner=owner,
        source_slug="src-opp",
        fork_at_phase="commcare-setup",
        source_run_id="20260101-1000",
        workspace=None,
        now=dt.datetime(2026, 8, 27, 3, 23, tzinfo=dt.UTC),
        **kw,
    )


# --- Defect 1: run_state.yaml must be written FIRST --------------------


def test_run_state_is_written_before_any_artifact_is_copied(monkeypatch):
    """``run_state.yaml`` is what makes the folder a run. Writing it
    before the bulk copy means a stalled fork yields a resumable-but-
    incomplete run instead of an unrunnable folder (#734)."""
    log: list[tuple[str, str]] = []
    _fork(_build_drive(call_log=log), monkeypatch)

    ops = [f"{op}:{name}" for op, name in log]
    state_at = ops.index("upload_file:run_state.yaml")
    first_copy = next(i for i, o in enumerate(ops) if o.startswith("copy_file:"))
    assert state_at < first_copy, (
        f"run_state.yaml written after the copy began: {ops}"
    )


def test_stalled_copy_still_leaves_a_resumable_run(monkeypatch):
    """The #734 failure mode verbatim: Drive stops responding partway
    through the copy. The new run folder must still carry a
    ``run_state.yaml`` so ``/ace:run <opp>/<run-id>`` has state to read."""
    log: list[tuple[str, str]] = []
    drive = _build_drive(call_log=log, fail_on_copy_after=1)

    with pytest.raises(RuntimeError, match="drive copy stalled"):
        _fork(drive, monkeypatch)

    assert ("upload_file", "run_state.yaml") in log


def test_written_run_state_is_the_synthesized_one_not_a_copy(monkeypatch):
    """Moving the write earlier must not change WHAT is written: a fresh
    phases map seeded from the fork point, not the source's state."""
    bodies: dict[str, str] = {}
    log: list[tuple[str, str]] = []
    drive = _build_drive(call_log=log)
    drive.upload_file.side_effect = lambda parent, name, body, mime: (
        bodies.__setitem__(name, body) or "state-id"
    )

    _fork(drive, monkeypatch)

    state = yaml.safe_load(bodies["run_state.yaml"])
    assert state["run_id"] == "20260827-0323"
    assert state["opportunity"] == "src-opp"
    assert "phases" in state


# --- Defect 2: every emitted payload must satisfy ForkProgress ---------


def test_every_progress_payload_validates_against_the_response_schema(monkeypatch):
    """``GET /fork/status`` returns ``ForkProgress``, a StrictModel with
    ``extra="forbid"``. Payloads the forker emitted used ``copied`` /
    ``total`` / ``current`` / ``opp_slug``, so the endpoint could only
    ever 500 or report ``unknown`` (#734)."""
    seen: list[dict] = []
    _fork(_build_drive(call_log=[]), monkeypatch, progress_cb=seen.append)

    assert seen, "fork emitted no progress at all"
    for payload in seen:
        ForkProgress.model_validate(payload)


def test_new_run_id_is_reported_as_soon_as_the_run_folder_exists(monkeypatch):
    """A caller whose POST hangs has exactly one way to learn what run
    was created. Reporting ``new_run_id`` only in the terminal ``done``
    payload is what turned a slow fork into a duplicate-run hazard."""
    seen: list[dict] = []
    _fork(_build_drive(call_log=[]), monkeypatch, progress_cb=seen.append)

    copying = [p for p in seen if p["status"] == "copying"]
    assert copying, "no copying payloads emitted"
    assert all(p.get("new_run_id") == "20260827-0323" for p in copying)
    assert all(p.get("new_slug") == "src-opp" for p in copying)


def test_a_drive_failure_reports_status_error_with_the_run_id(monkeypatch):
    """``unknown`` while a fork is actively failing invites a retry that
    produces a second partial fork. Report the failure, and report which
    run folder was left behind."""
    seen: list[dict] = []
    drive = _build_drive(call_log=[], fail_on_copy_after=1)

    with pytest.raises(RuntimeError):
        _fork(drive, monkeypatch, progress_cb=seen.append)

    assert seen[-1]["status"] == "error"
    assert seen[-1]["new_run_id"] == "20260827-0323"
    assert seen[-1]["error"]
    ForkProgress.model_validate(seen[-1])


def test_progress_fraction_tracks_copied_over_total(monkeypatch):
    seen: list[dict] = []
    _fork(_build_drive(call_log=[]), monkeypatch, progress_cb=seen.append)

    done = seen[-1]
    assert done["status"] == "done"
    assert done["files_total"] == done["files_copied"]
    assert done["progress"] == 1.0


# --- Defect 3: the poll must find the fork it is polling for ----------
#
# These go through the REAL django cache, unlike
# ``test_fork_status_happy_path`` in test_api.py which monkeypatches
# ``cache.get`` to return a hand-written payload. That stub is why the
# key mismatch AND the shape mismatch both shipped: no test ever ran a
# writer and a reader against each other.


class _WS:
    """``_fork_progress_key`` only reads ``workspace.pk`` (a slug, not an
    int — see docs/learnings/opp-cache-architecture.md)."""

    pk = "dimagi-team"


def _write_and_read(*, wrote_run_id: str, polled_run_id: str):
    workspace = _WS()
    from django.core.cache import cache

    from apps.opps.api import _write_fork_progress
    from apps.opps.views_write import _fork_progress_key

    cache.clear()
    _write_fork_progress(workspace, "opp-1", wrote_run_id)(
        {"status": "copying", "progress": 0.4, "files_copied": 4,
         "files_total": 10, "new_slug": "opp-1", "new_run_id": "20260827-0323"}
    )
    return cache.get(_fork_progress_key(workspace, "opp-1", polled_run_id))


def test_poll_without_source_run_id_finds_a_fork_started_with_one():
    """The POST body carries ``source_run_id``; a caller polling
    ``GET …/fork/status`` with no query param reads the ``_latest`` key.
    Before #734 those were different keys and the poll reported
    ``unknown`` for the entire fork."""
    found = _write_and_read(wrote_run_id="20260824-1404", polled_run_id="")
    assert found is not None, "poll without source_run_id saw nothing"
    assert found["new_run_id"] == "20260827-0323"


def test_poll_with_source_run_id_still_finds_its_own_fork():
    found = _write_and_read(
        wrote_run_id="20260824-1404", polled_run_id="20260824-1404",
    )
    assert found is not None
    assert found["new_run_id"] == "20260827-0323"


@pytest.mark.django_db
def test_fork_status_reports_a_real_forker_payload_end_to_end(
    client, django_user_model, monkeypatch,
):
    """Writer and reader wired together: run the real forker with the
    real cache-writing callback, then read the endpoint. This is the
    assertion #734's `unknown`-forever poll needed."""
    from django.core.cache import cache

    from apps.opps.api import _write_fork_progress
    from apps.workspaces.models import Workspace, WorkspaceMembership

    user = django_user_model.objects.create_user(email="forker@dimagi.com")
    ws = Workspace.objects.filter(slug="ws-fork").first() or Workspace.objects.create(
        slug="ws-fork", display_name="WS Fork",
        drive_root_folder_id="ace-root", created_by=user,
    )
    WorkspaceMembership.objects.get_or_create(
        workspace=ws, user=user, defaults={"role": "owner"},
    )
    client.force_login(user)
    cache.clear()

    _fork(
        _build_drive(call_log=[]), monkeypatch,
        progress_cb=_write_fork_progress(ws, "src-opp", "20260101-1000"),
    )

    response = client.get("/api/w/ws-fork/opps/src-opp/fork/status")
    assert response.status_code == 200, response.content
    body = response.json()
    ForkProgress.model_validate(body)
    assert body["status"] == "done"
    assert body["new_run_id"] == "20260827-0323"
