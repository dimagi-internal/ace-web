"""The build memo on the public run summary (ace-web#767).

ACE's ``skills/build-memo`` (ace#2371) writes one programme-level memo per
run and records it at
``phases.connect-setup.products.connect.build_memo = {file_id, title,
web_view_link, complete, gaps[]}``. The PDD defines it as THE review
artifact — "humans review the memo and spot-check the apps, rather than
reviewing every screen" — so the page carries its text, not just a link.

The two fixture bodies are not hand-written. They are Drive's own exports
of one Google Doc, created with ACE's ``drive_create_doc_from_markdown``
from a memo shaped exactly as the skill's Process step 2 prescribes, then
read back with ``exportAs: text/markdown`` and ``text/plain``
(2026-09-11). The plain export is the control: it has no tables at all,
and the memo is mostly tables.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from apps.opps.drive_export import GOOGLE_DOC_MIME, MARKDOWN_EXPORT
from apps.opps.summary import build_summary_payload
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.opps.tests.test_summary import _FakeWorkspace, _full_tree, _state_yaml

_FIXTURES = Path(__file__).parent / "fixtures"
MD_EXPORT = (_FIXTURES / "build_memo_markdown_export.md").read_text(encoding="utf-8")
PLAIN_EXPORT = (_FIXTURES / "build_memo_plain_export.txt").read_text(encoding="utf-8")

OPP = "turmeric"
RUN = "20260503-0835"
RUN_PATH = f"ACE/{OPP}/runs/{RUN}"


def _with_memo(state_yaml: str, memo: dict | None) -> str:
    state = yaml.safe_load(state_yaml)
    if memo is not None:
        state["phases"]["connect-setup"]["products"]["connect"]["build_memo"] = memo
    return yaml.safe_dump(state)


def _drive_with_memo_doc(
    memo: dict | None = None, *, mime_type: str = GOOGLE_DOC_MIME,
) -> tuple[FakeDriveClient, str]:
    """A run whose ``4-connect/build-memo.md`` is a Google Doc, as the skill
    writes it, with the state pointer aimed at the doc's real id.

    ``memo`` entries may use the literal ``"<id>"``, which is replaced with
    the doc's id once it exists.
    """
    drive = FakeDriveClient.from_tree(_full_tree())
    connect_folder = drive.create_folder(drive.folder_id(RUN_PATH), "4-connect")
    body = PLAIN_EXPORT if mime_type == GOOGLE_DOC_MIME else MD_EXPORT
    memo_id = drive.upload_file(connect_folder, "build-memo.md", body, mime_type)
    if mime_type == GOOGLE_DOC_MIME:
        drive.set_export_body(memo_id, MARKDOWN_EXPORT, MD_EXPORT)

    if memo is None:
        memo = {
            "file_id": "<id>",
            "title": "Build memo",
            "web_view_link": "https://docs.google.com/document/d/<id>/edit",
            "complete": True,
            "gaps": [],
        }
    memo = {
        k: (v.replace("<id>", memo_id) if isinstance(v, str) else v)
        for k, v in memo.items()
    }
    drive.update_file(
        drive.file_id(f"{RUN_PATH}/run_state.yaml"),
        _with_memo(_state_yaml(), memo),
        "application/x-yaml",
    )
    return drive, memo_id


def _payload(drive: FakeDriveClient, **kw) -> dict:
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(drive, workspace=ws, opp_slug=OPP, run_id=RUN, **kw)
    assert p is not None
    return p


def test_a_run_with_a_memo_carries_its_text_not_just_a_link():
    drive, memo_id = _drive_with_memo_doc()
    drive.set_link_shared(memo_id, True)

    memo = _payload(drive)["build_memo"]

    assert memo["title"] == "Build memo"
    assert memo["url"] == f"https://docs.google.com/document/d/{memo_id}/edit"
    assert memo["access"] == "public"
    assert memo["complete"] is True
    assert memo["gaps"] == []
    assert memo["body"] == MD_EXPORT


def test_the_body_is_the_markdown_export_so_the_tables_survive():
    """The control: Drive's default plain export has NO tables. A reader
    that took it would hand the page §1 — the whole review — as a column
    of loose words."""
    assert "|" not in PLAIN_EXPORT, "fixture drift: the plain export gained a table"

    drive, _ = _drive_with_memo_doc()
    body = _payload(drive)["build_memo"]["body"]

    table_rows = [line for line in body.splitlines() if line.startswith("|")]
    assert len(table_rows) >= 10
    assert any("Deliver app → Household visit → Roster" in r for r in table_rows)


def test_the_body_is_passed_through_verbatim_not_unescaped():
    """Drive's markdown export escapes punctuation; the page's CommonMark
    renderer resolves those escapes itself. ``unescape_markdown`` here
    would turn an escaped ``1\\.`` heading into a list and an escaped
    ``\\|`` inside a table cell into a column break."""
    drive, _ = _drive_with_memo_doc()
    body = _payload(drive)["build_memo"]["body"]

    assert "## 1\\. Every \\[ACE\\] latitude" in body
    assert "consent\\_confirmed" in body


def test_an_incomplete_memo_carries_its_gaps():
    drive, _ = _drive_with_memo_doc({
        "file_id": "<id>",
        "web_view_link": "https://docs.google.com/document/d/<id>/edit",
        "complete": False,
        "gaps": [
            "4-connect/connect-opp-setup.md: section missing",
            "  ",
            "GPS radius 200 m: NOT STATED by connect-opp-setup",
        ],
    })

    memo = _payload(drive)["build_memo"]

    assert memo["complete"] is False
    assert memo["gaps"] == [
        "4-connect/connect-opp-setup.md: section missing",
        "GPS radius 200 m: NOT STATED by connect-opp-setup",
    ]
    # No `title` recorded: the reader supplies the skill's own.
    assert memo["title"] == "Build memo"


def test_complete_is_null_when_the_run_did_not_say():
    """Absence must not be dressed up as reassurance in either direction."""
    drive, _ = _drive_with_memo_doc({"file_id": "<id>"})
    memo = _payload(drive)["build_memo"]
    assert memo["complete"] is None
    assert memo["gaps"] == []


def test_a_run_without_a_memo_has_no_section_at_all():
    """Every run before ace#2371 — including the live poverty-graduation
    run 20260908-0510. The page must render exactly as before."""
    drive = FakeDriveClient.from_tree(_full_tree())
    p = _payload(drive)
    assert p["build_memo"] is None
    assert p["design"] and p["connect"], "the rest of the page is untouched"


def test_the_pointer_can_be_a_link_alone():
    """The skill writes both, but ``DocPointer`` makes each optional."""
    drive, _ = _drive_with_memo_doc({
        "web_view_link": "https://docs.google.com/document/d/<id>/edit?usp=drivesdk",
    })
    memo = _payload(drive)["build_memo"]
    # The producer's own link is served as-is, never rebuilt. (The fake's
    # short ids are below `drive_file_id`'s 10-char floor, so the body read
    # through a derived id is covered by `drive_file_id`'s own tests.)
    assert memo["url"].endswith("/edit?usp=drivesdk")


def test_an_unreadable_memo_keeps_its_link_and_gaps():
    """The pointer exists but the text cannot be fetched. The section
    stays, with ``body`` null, so the reader still gets the link and any
    gaps instead of silence."""
    drive = FakeDriveClient.from_tree(_full_tree())
    drive.update_file(
        drive.file_id(f"{RUN_PATH}/run_state.yaml"),
        _with_memo(_state_yaml(), {
            "file_id": "gone-1234567890",
            "complete": False,
            "gaps": ["Learn memo absent"],
        }),
        "application/x-yaml",
    )

    memo = _payload(drive)["build_memo"]

    assert memo["body"] is None
    assert memo["url"] == "https://docs.google.com/document/d/gone-1234567890/edit"
    assert memo["gaps"] == ["Learn memo absent"]
    assert memo["access"] == "unknown"


def test_a_raw_markdown_upload_reads_without_an_export():
    """If the pointer ever names the ``.source.md`` twin (a plain
    ``text/markdown`` blob), it reads directly — the export path is keyed
    on the file's real type, not on its name."""
    drive, _ = _drive_with_memo_doc(mime_type="text/markdown")
    assert _payload(drive)["build_memo"]["body"] == MD_EXPORT


def test_the_memo_link_is_measured_in_the_same_batch_as_every_other_link():
    """ace-web#740 batching: the memo's ACL read rides the one up-front
    prime rather than costing a sequential round-trip mid-render."""
    drive, memo_id = _drive_with_memo_doc()
    drive.set_link_shared(memo_id, False)

    memo = _payload(drive)["build_memo"]

    assert memo["access"] == "admin"
    assert memo_id in drive.link_shared_calls[0]
