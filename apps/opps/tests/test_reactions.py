"""Tests for partner reactions to decision rows.

Covers the three things this store has to get right: the record it
writes is one a `FeedbackRecordSchema` consumer can parse, the read-back
never leaks a privately-captured review onto a public page, and the
abuse ceilings actually hold.
"""
from __future__ import annotations

from datetime import date

import pytest
import yaml

from apps.opps.reactions import (
    MAX_COMMENT_CHARS,
    MAX_ITEMS_PER_RECORD,
    MAX_ITEMS_PER_RUN,
    ReactionRejected,
    build_anchor,
    clean_comment,
    clean_email,
    clean_reviewer,
    is_public_record_slug,
    next_item_id,
    parse_decision_id,
    read_reactions,
    reviewer_slug,
    submit_decision_reaction,
)
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient

DECISIONS_YAML = """\
schema_version: 4
opp: spark
run_id: '20260813-2126'
decisions:
  - id: solicitation-expected-period
    phase: 8-solicitation-management
    question: Which dates should the solicitation advertise?
    ai-default: Work order period of performance
    evidence_basis: conflicting
  - id: visit-window
    phase: 1-design
    question: How long is the visit window?
    ai-default: 30 days
    evidence_basis: inferred
"""


def _tree(feedback: dict | None = None) -> dict:
    opp: dict = {
        "opp.yaml": "slug: spark\n",
        "runs": {"20260813-2126": {"decisions.yaml": DECISIONS_YAML}},
    }
    if feedback is not None:
        opp["feedback"] = feedback
    return {"ACE": {"spark": opp}}


def _submit(client, **kwargs):
    defaults = dict(
        drive=client,
        opp_folder_id=client.folder_id("ACE/spark"),
        run_folder_id=client.folder_id("ACE/spark/runs/20260813-2126"),
        run_id="20260813-2126",
        decision_id="solicitation-expected-period",
        reviewer="Anne Sebert Kuhlmann",
        reviewer_email=None,
        comment="The mobilisation date reads late for a September start.",
        artifact_url="https://labs/ace/summary?tab=decisions",
        today=date(2026, 8, 14),
    )
    return submit_decision_reaction(**{**defaults, **kwargs})


# ─── Input hygiene ─────────────────────────────────────────────────


def test_reviewer_name_is_required():
    with pytest.raises(ReactionRejected):
        clean_reviewer("")
    with pytest.raises(ReactionRejected):
        clean_reviewer("  a  ")


def test_reviewer_name_collapses_whitespace():
    assert clean_reviewer("  Anne   Sebert  Kuhlmann ") == "Anne Sebert Kuhlmann"


def test_html_is_rejected_not_stripped():
    # The text also lands in a markdown-rendered gdoc, so "React escapes
    # it" is not the whole story — and silently mangling a reviewer's
    # words is worse than refusing them.
    with pytest.raises(ReactionRejected):
        clean_comment("<script>alert(1)</script> the dates look wrong")
    with pytest.raises(ReactionRejected):
        clean_reviewer("<b>Anne</b>")


def test_bare_angle_bracket_is_allowed():
    assert clean_comment("visits < 30 days should still pay").startswith("visits <")


def test_comment_length_bounds():
    with pytest.raises(ReactionRejected):
        clean_comment("no")
    with pytest.raises(ReactionRejected):
        clean_comment("x" * (MAX_COMMENT_CHARS + 1))


def test_control_characters_are_stripped():
    assert clean_comment("dates\x00 look\x07 wrong") == "dates look wrong"


def test_email_is_optional_but_validated():
    assert clean_email("") is None
    assert clean_email(" anne@example.org ") == "anne@example.org"
    with pytest.raises(ReactionRejected):
        clean_email("not-an-email")


def test_reviewer_slug_falls_back_when_unslugifiable():
    assert reviewer_slug("Anne Sebert-Kuhlmann") == "anne-sebert-kuhlmann"
    assert reviewer_slug("界 界") == "reviewer"


# ─── Anchors ───────────────────────────────────────────────────────


def test_anchor_round_trips_to_the_decision_id():
    anchor = build_anchor("visit-window", "How long is the visit window?")
    assert anchor.startswith("decision:visit-window ")
    assert parse_decision_id(anchor) == "visit-window"


def test_anchor_truncates_a_long_question():
    anchor = build_anchor("x", "q" * 400)
    assert len(anchor) < 200
    assert parse_decision_id(anchor) == "x"


def test_a_human_authored_anchor_is_not_a_decision_ref():
    assert parse_decision_id("§5 Visit definition") is None
    assert parse_decision_id(None) is None


def test_item_ids_stay_kebab_case_on_repeat():
    # FeedbackItemSchema enforces kebab-case; a second reaction to the
    # same row from the same reviewer must not break it.
    assert next_item_id(set(), "visit-window") == "visit-window"
    assert next_item_id({"visit-window"}, "visit-window") == "visit-window-2"
    assert next_item_id({"visit-window", "visit-window-2"}, "visit-window") == "visit-window-3"


# ─── The written record ────────────────────────────────────────────

#: Exactly the keys `FeedbackRecordSchema` (strict) accepts. See
#: `lib/feedback-ledger.ts` in the ACE plugin. A key outside this set
#: makes the record unparseable by the only consumer it has.
RECORD_KEYS = {
    "schema_version", "slug", "reviewer", "reviewer_email", "received_at",
    "channel", "artifact", "artifact_url", "against_run", "items",
}
ITEM_KEYS = {"id", "verbatim", "anchor"}


def test_first_reaction_creates_a_schema_shaped_record():
    client = FakeDriveClient.from_tree(_tree())
    result = _submit(client, reviewer_email="anne@example.org")

    assert result["feedback_ref"] == (
        "20260814-public-anne-sebert-kuhlmann/solicitation-expected-period"
    )
    body = client.get_content(
        client.file_id("ACE/spark/feedback/20260814-public-anne-sebert-kuhlmann.yaml"),
        "application/x-yaml",
    ).content
    record = yaml.safe_load(body)

    assert set(record) <= RECORD_KEYS
    assert record["schema_version"] == 1
    assert record["slug"] == "20260814-public-anne-sebert-kuhlmann"
    assert record["reviewer"] == "Anne Sebert Kuhlmann"
    assert record["reviewer_email"] == "anne@example.org"
    assert record["channel"] == "other"
    assert record["against_run"] == "20260813-2126"
    assert "self-reported" in record["artifact"]
    assert len(record["items"]) == 1
    item = record["items"][0]
    assert set(item) == ITEM_KEYS
    assert item["id"] == "solicitation-expected-period"
    assert item["verbatim"].startswith("The mobilisation date")
    assert parse_decision_id(item["anchor"]) == "solicitation-expected-period"


def test_second_reaction_appends_to_the_same_record():
    client = FakeDriveClient.from_tree(_tree())
    _submit(client)
    _submit(client, decision_id="visit-window", comment="30 days is too long here.")

    record = yaml.safe_load(client.get_content(
        client.file_id("ACE/spark/feedback/20260814-public-anne-sebert-kuhlmann.yaml"),
        "application/x-yaml",
    ).content)
    assert [i["id"] for i in record["items"]] == [
        "solicitation-expected-period", "visit-window",
    ]


def test_two_reactions_to_one_row_get_distinct_ids():
    client = FakeDriveClient.from_tree(_tree())
    first = _submit(client)
    second = _submit(client, comment="Actually, one more thing about this.")
    assert first["item_id"] == "solicitation-expected-period"
    assert second["item_id"] == "solicitation-expected-period-2"


def test_same_reviewer_same_day_different_run_gets_its_own_record():
    # A record carries exactly one `against_run`; overloading one would
    # misattribute the comment to the wrong run.
    tree = _tree()
    tree["ACE"]["spark"]["runs"]["20260101-0900"] = {"decisions.yaml": DECISIONS_YAML}
    client = FakeDriveClient.from_tree(tree)
    _submit(client)
    other = _submit(
        client,
        run_folder_id=client.folder_id("ACE/spark/runs/20260101-0900"),
        run_id="20260101-0900",
    )
    assert other["record_slug"] == "20260814-public-anne-sebert-kuhlmann-2"
    record = yaml.safe_load(client.get_content(
        client.file_id("ACE/spark/feedback/20260814-public-anne-sebert-kuhlmann-2.yaml"),
        "application/x-yaml",
    ).content)
    assert record["against_run"] == "20260101-0900"


def test_reaction_to_an_unknown_decision_is_refused():
    # A dangling feedback_ref renders under the ledger's "Broken stamps",
    # so an unroutable reaction is refused rather than stored.
    client = FakeDriveClient.from_tree(_tree())
    with pytest.raises(ReactionRejected) as exc:
        _submit(client, decision_id="no-such-row")
    assert exc.value.code == "not-found"
    assert "feedback" not in [f.name for f in client.list_files(client.folder_id("ACE/spark"))]


def test_feedback_folder_is_created_when_absent():
    client = FakeDriveClient.from_tree(_tree())
    _submit(client)
    names = [f.name for f in client.list_files(client.folder_id("ACE/spark"))]
    assert "feedback" in names


# ─── Abuse ceilings ────────────────────────────────────────────────


def test_per_record_ceiling_holds():
    client = FakeDriveClient.from_tree(_tree())
    for i in range(MAX_ITEMS_PER_RECORD):
        _submit(client, comment=f"comment number {i}")
    with pytest.raises(ReactionRejected) as exc:
        _submit(client, comment="one too many")
    assert exc.value.code == "too-many"


def test_per_run_ceiling_counts_across_reviewers():
    items = [
        {"id": f"visit-window-{n}", "verbatim": "x", "anchor": "decision:visit-window"}
        for n in range(2, MAX_ITEMS_PER_RUN + 2)
    ]
    record = {
        "schema_version": 1, "slug": "20260813-public-someone",
        "reviewer": "Someone", "received_at": "2026-08-13", "channel": "other",
        "against_run": "20260813-2126", "items": items,
    }
    client = FakeDriveClient.from_tree(
        _tree({"20260813-public-someone.yaml": yaml.safe_dump(record)})
    )
    with pytest.raises(ReactionRejected) as exc:
        _submit(client)
    assert exc.value.code == "too-many"


# ─── Read-back ─────────────────────────────────────────────────────


def test_read_reactions_groups_by_decision_and_hides_emails():
    client = FakeDriveClient.from_tree(_tree())
    _submit(client, reviewer_email="anne@example.org")
    _submit(client, decision_id="visit-window", comment="30 days is too long here.")

    out = read_reactions(client, client.folder_id("ACE/spark"), run_id="20260813-2126")
    assert out["total"] == 2
    assert set(out["by_decision"]) == {"solicitation-expected-period", "visit-window"}
    row = out["by_decision"]["visit-window"][0]
    assert row["reviewer"] == "Anne Sebert Kuhlmann"
    assert row["comment"] == "30 days is too long here."
    assert row["feedback_ref"].endswith("/visit-window")
    assert "anne@example.org" not in repr(out)


def test_read_reactions_is_scoped_to_the_run():
    client = FakeDriveClient.from_tree(_tree())
    _submit(client)
    out = read_reactions(client, client.folder_id("ACE/spark"), run_id="some-other-run")
    assert out == {"total": 0, "by_decision": {}}


def test_a_privately_captured_review_is_never_republished():
    # skills/feedback-ledger writes gdoc-comment / email / meeting reviews
    # into the SAME folder. Those were given to Dimagi in confidence; the
    # `public` slug marker — not a heuristic — is what keeps them off a
    # page anyone can open.
    private = {
        "schema_version": 1,
        "slug": "20260727-sophie-feintuch",
        "reviewer": "Sophie Feintuch",
        "received_at": "2026-07-27",
        "channel": "gdoc-comments",
        "against_run": "20260813-2126",
        "items": [{
            "id": "d",
            "verbatim": "internal review note that must not surface publicly",
            "anchor": "decision:visit-window · How long is the visit window?",
        }],
    }
    client = FakeDriveClient.from_tree(
        _tree({"20260727-sophie-feintuch.yaml": yaml.safe_dump(private)})
    )
    out = read_reactions(client, client.folder_id("ACE/spark"), run_id="20260813-2126")
    assert out == {"total": 0, "by_decision": {}}
    assert not is_public_record_slug("20260727-sophie-feintuch")
    assert is_public_record_slug("20260814-public-anne-sebert-kuhlmann")


def test_read_reactions_survives_a_malformed_record():
    client = FakeDriveClient.from_tree(_tree({"20260814-public-x.yaml": ":::not yaml:::"}))
    _submit(client)
    out = read_reactions(client, client.folder_id("ACE/spark"), run_id="20260813-2126")
    assert out["total"] == 1


def test_read_reactions_with_no_feedback_folder():
    client = FakeDriveClient.from_tree(_tree())
    out = read_reactions(client, client.folder_id("ACE/spark"), run_id="20260813-2126")
    assert out == {"total": 0, "by_decision": {}}
