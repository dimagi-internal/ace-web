"""Unit tests for ``apps.opps.feedback`` — the reviewer-feedback reader.

Shapes are taken from the real record at
``ACE/hh-poverty-targeting/feedback/20260727-sophie-feintuch.yaml`` and its
rendered ledger, so a change to the plugin's output shape fails here rather
than rendering an empty panel in production.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from apps.opps import feedback

FOLDER = "application/vnd.google-apps.folder"
GDOC = "application/vnd.google-apps.document"

RECORD_YAML = """\
schema_version: 1
slug: 20260727-sophie-feintuch
reviewer: Sophie Feintuch
reviewer_email: sfeintuch@dimagi-associate.com
received_at: 2026-07-27
channel: gdoc-comments
artifact: "PDD — Household Poverty Targeting Survey"
artifact_url: https://docs.google.com/document/d/abc/edit
against_run: 20260722-1341
items:
  - id: a
    anchor: "§3 Instrument — implement Annex A verbatim"
    verbatim: Fields must be required rather than optional
  - id: d
    anchor: "§5 [ACE] Visit flow"
    verbatim: |-
      visit_outcome is the first question in the form, which is impossible
      for an FLW to answer at that point.
"""

LEDGER_BODY = """\
Feedback ledger — Sophie Feintuch, 2026-07-27

9 comments — 8 shipped, 1 need a human, 0 unrouted.

[a] §3 Instrument
* SHIPPED · decision — decisions.yaml § required-vs-optional-fields
[d] §5 [ACE] Visit flow
* SHIPPED · skill fix — ace#979
"""


@dataclass
class FakeFile:
    id: str
    name: str
    mime_type: str
    web_view_link: str = ""


@dataclass
class FakeContent:
    content: str


class FakeDrive:
    """Minimal DriveClient: a folder tree plus file bodies."""

    def __init__(self, tree, bodies, *, markdown_bodies=None):
        self.tree = tree
        self.bodies = bodies
        self.markdown_bodies = markdown_bodies or {}
        self.exports: list[tuple[str, str | None]] = []

    def list_folder(self, folder_id):
        if folder_id not in self.tree:
            raise KeyError(folder_id)
        return self.tree[folder_id]

    def get_content(self, file_id, mime_type, export_as=None):
        self.exports.append((file_id, export_as))
        if export_as == "text/markdown" and file_id in self.markdown_bodies:
            return FakeContent(self.markdown_bodies[file_id])
        return FakeContent(self.bodies[file_id])


def _drive(**overrides):
    record = FakeFile("rec-1", "20260727-sophie-feintuch.yaml", "text/yaml", "u/record")
    ledger = FakeFile("led-1", "20260727-sophie-feintuch-ledger", GDOC, "u/ledger")
    tree = {
        "opp-1": [
            FakeFile("fb-1", "feedback", FOLDER),
            FakeFile("runs-1", "runs", FOLDER),
        ],
        "fb-1": [record, ledger],
    }
    bodies = {"rec-1": RECORD_YAML, "led-1": "FLATTENED PLAIN TEXT"}
    markdown = {"led-1": LEDGER_BODY}
    tree.update(overrides.pop("tree", {}))
    return FakeDrive(tree, bodies, markdown_bodies=markdown, **overrides)


# --------------------------------------------------------------------------- #
# the happy path
# --------------------------------------------------------------------------- #
def test_reads_the_record_and_its_rendered_ledger():
    payload = feedback.build_feedback_payload(_drive(), "opp-1")
    assert payload["schema_version"] == feedback.SCHEMA_VERSION
    (rec,) = payload["records"]
    assert rec["reviewer"] == "Sophie Feintuch"
    assert rec["received_at"] == "2026-07-27"
    assert rec["channel"] == "gdoc-comments"
    assert rec["against_run"] == "20260722-1341"
    assert rec["ledger_url"] == "u/ledger"


def test_keeps_each_comment_verbatim_with_its_anchor():
    """A comment detached from the section it was about is harder to act on."""
    (rec,) = feedback.build_feedback_payload(_drive(), "opp-1")["records"]
    assert rec["item_count"] == 2
    first, second = rec["items"]
    assert first["id"] == "a"
    assert first["anchor"].startswith("§3 Instrument")
    assert "required rather than optional" in first["verbatim"]
    assert "visit_outcome is the first question" in second["verbatim"]


def test_exports_the_ledger_as_markdown_not_flattened_plain_text():
    """The ledger doc carries no .md suffix, so the default export would
    flatten its bold and bullets. It must be asked for as markdown."""
    drive = _drive()
    (rec,) = feedback.build_feedback_payload(drive, "opp-1")["records"]
    assert ("led-1", "text/markdown") in drive.exports
    assert "FLATTENED" not in rec["ledger_body"]
    assert "SHIPPED" in rec["ledger_body"]


def test_reports_the_plugins_own_tally_rather_than_recomputing_it():
    """The counts come from the GitHub join ace-web deliberately does not
    reimplement, so they are READ from the rendered line."""
    (rec,) = feedback.build_feedback_payload(_drive(), "opp-1")["records"]
    assert rec["tally"] == {
        "comments": 9,
        "shipped": 8,
        "needs_human": 1,
        "unrouted": 0,
    }


# --------------------------------------------------------------------------- #
# honest degradation
# --------------------------------------------------------------------------- #
def test_no_feedback_folder_is_not_an_error():
    drive = FakeDrive({"opp-1": [FakeFile("runs-1", "runs", FOLDER)]}, {})
    assert feedback.build_feedback_payload(drive, "opp-1") == {
        "schema_version": feedback.SCHEMA_VERSION,
        "records": [],
    }


def test_a_record_with_no_ledger_yet_still_renders():
    """The inbound record is written when the review lands; the ledger is
    rendered later. The gap must show the comments, not nothing."""
    record = FakeFile("rec-1", "20260727-sophie-feintuch.yaml", "text/yaml")
    drive = FakeDrive(
        {"opp-1": [FakeFile("fb-1", "feedback", FOLDER)], "fb-1": [record]},
        {"rec-1": RECORD_YAML},
    )
    (rec,) = feedback.build_feedback_payload(drive, "opp-1")["records"]
    assert rec["item_count"] == 2
    assert rec["ledger_body"] == ""
    assert rec["tally"] is None


def test_tally_absent_rather_than_guessed_when_the_line_is_missing():
    assert feedback.parse_tally("Feedback ledger — no counts here") is None
    assert feedback.parse_tally("") is None


@pytest.mark.parametrize(
    "line,expected",
    [
        ("9 comments — 8 shipped, 1 need a human, 0 unrouted.", (9, 8, 1, 0)),
        ("1 comment - 0 shipped, 0 needs a human, 1 unrouted", (1, 0, 0, 1)),
        ("12 comments – 10 shipped, 1 need a human, 1 unrouted.", (12, 10, 1, 1)),
    ],
)
def test_tally_accepts_the_dash_and_plural_variants_the_renderer_emits(line, expected):
    t = feedback.parse_tally(line)
    assert (t["comments"], t["shipped"], t["needs_human"], t["unrouted"]) == expected


def test_malformed_yaml_is_skipped_not_fatal():
    record = FakeFile("rec-1", "broken.yaml", "text/yaml")
    drive = FakeDrive(
        {"opp-1": [FakeFile("fb-1", "feedback", FOLDER)], "fb-1": [record]},
        {"rec-1": "this: [is: not: yaml"},
    )
    assert feedback.build_feedback_payload(drive, "opp-1")["records"] == []


def test_unreadable_ledger_leaves_the_record_intact():
    class Flaky(FakeDrive):
        def get_content(self, file_id, mime_type, export_as=None):
            if file_id == "led-1":
                raise RuntimeError("drive 500")
            return super().get_content(file_id, mime_type, export_as=export_as)

    base = _drive()
    drive = Flaky(base.tree, base.bodies, markdown_bodies=base.markdown_bodies)
    (rec,) = feedback.build_feedback_payload(drive, "opp-1")["records"]
    assert rec["item_count"] == 2
    assert rec["ledger_body"] == ""


def test_records_are_newest_first():
    older = FakeFile("rec-0", "20260101-early.yaml", "text/yaml")
    base = _drive()
    base.tree["fb-1"] = [older, *base.tree["fb-1"]]
    base.bodies["rec-0"] = (
        "slug: 20260101-early\nreviewer: Early Reviewer\nreceived_at: 2026-01-01\nitems: []\n"
    )
    records = feedback.build_feedback_payload(base, "opp-1")["records"]
    assert [r["received_at"] for r in records] == ["2026-07-27", "2026-01-01"]


# --------------------------------------------------------------------------- #
# the ledger's own preamble — shapes taken from the real markdown export
# --------------------------------------------------------------------------- #
REAL_LEDGER = """\
> **Derived view — do not edit by hand.** Recomputed by ACE's `feedback-ledger` skill.

# Feedback ledger — Sophie Feintuch, 2026-07-27

Reviewed: [PDD — Household Poverty Targeting Survey](https://docs.google.com/d/x/edit) \
Against run: `20260722-1341` Responding run: `20260728-0705` (rendered 2026-07-29)

**9 comments — 8 shipped, 1 need a human, 0 unrouted.**

## \\[a\\] §3 Instrument — implement Annex A verbatim

> Fields must be required rather than optional

- **SHIPPED** · decision — decisions.yaml § required-vs-optional-fields

## \\[b\\] §5 Visit definition

- **SHIPPED** · skill fix — ace#980
"""


def test_strips_the_ledgers_own_header_so_it_does_not_stutter():
    """The panel header already carries the reviewer, artifact and tally from
    the structured record; rendering the doc's version too reads as a stutter."""
    out = feedback.strip_ledger_preamble(REAL_LEDGER)
    assert out.startswith("## \\[a\\]")
    assert "do not edit by hand" not in out
    assert "# Feedback ledger" not in out
    # The items themselves survive intact.
    assert "ace#980" in out
    assert out.count("## ") == 2


def test_keeps_the_whole_body_when_there_is_no_item_heading():
    """Half a ledger is worse than a repeated line."""
    body = "Feedback ledger — no items rendered yet."
    assert feedback.strip_ledger_preamble(body) == body
    assert feedback.strip_ledger_preamble("") == ""


def test_reads_the_run_that_responded_to_the_review():
    assert feedback.parse_responding_run(REAL_LEDGER) == "20260728-0705"


def test_responding_run_absent_rather_than_guessed():
    assert feedback.parse_responding_run("no such line") == ""
    assert feedback.parse_responding_run("") == ""


def test_tally_parses_the_real_bolded_line():
    assert feedback.parse_tally(REAL_LEDGER) == {
        "comments": 9,
        "shipped": 8,
        "needs_human": 1,
        "unrouted": 0,
    }


def test_payload_carries_the_stripped_body_and_responding_run():
    base = _drive()
    base.markdown_bodies["led-1"] = REAL_LEDGER
    (rec,) = feedback.build_feedback_payload(base, "opp-1")["records"]
    assert rec["responding_run"] == "20260728-0705"
    assert rec["ledger_body"].startswith("## \\[a\\]")
