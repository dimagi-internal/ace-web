"""The review asks fold into decision rows (ACE spec 2026-10-04,
``docs/superpowers/specs/2026-10-04-open-questions-into-decisions-design.md``).

Rows are verbatim from ``spark/spark-facilitator/20261001-2208``'s
``decisions.yaml`` (the spec's evidence run), with the four new ask fields
added the way the spec's migration writes them: ``working-language`` keeps its
real ``recommended-confirmation``; ``rct-sample-overlap`` is the spec's one
category-E row (``required-before: award``); ``rwanda-two-cbf-attribution`` is a
category-C ``deferred`` row.
"""
from __future__ import annotations

import pytest

from apps.opps.parsers import decision_extras, normalize_decision_status
from apps.opps.summary import build_summary_payload
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.opps.tests.test_summary import (
    _OPEN_QUESTIONS_MD,
    _OPP_YAML,
    _FakeWorkspace,
    _state_yaml,
)

RUN = "20261001-2208"

_ASK_DECISIONS = """\
schema_version: 6
opportunity: spark-facilitator
run_id: 20261001-2208
decisions:
  - id: working-language
    phase: 1-design
    skill: idea-to-pdd
    question: Working language(s) and who reviews translations?
    ai-default: English source plus Chichewa (nya) and Tumbuka (tum)
    options:
      - English source plus Chichewa (nya) and Tumbuka (tum)
      - English only
    reasoning: Matches Spark's own app.
    source: FCAP extract (app languages en/nya/tum)
    status: ai-default
    evidence_basis: stated
    plain_question: Have the Chichewa and Tumbuka translations been checked by a native speaker?
    review_ask: recommended-confirmation
    confirm_reason: The Chichewa and Tumbuka text was produced by AI and has not been reviewed.
    plain: The apps are written in English, with Chichewa and Tumbuka translations made by AI.
    owner: partner
    answer_channel: review
  - id: rct-sample-overlap
    phase: 8-solicitation-management
    skill: solicitation-create
    question: Are any candidate pilot communities in the sample of Spark's FCAP trial?
    ai-default: OPEN
    options: [OPEN]
    reasoning: No default anywhere; gates the award.
    source: PDD §12
    status: ai-default
    evidence_basis: inferred
    plain_question: Can pilot communities overlap with Spark's trial communities?
    plain: Not yet decided.
    review_ask: "required-before: award"
    confirm_reason: Phase 8 could pick trial communities.
    owner: partner
    answer_channel: solicitation:q-rct-overlap
  - id: rwanda-two-cbf-attribution
    phase: 1-design
    skill: idea-to-pdd
    question: How is payment attributed where two CBFs share one community (Rwanda)?
    ai-default: Not needed for the Malawi pilot
    options: [Not needed for the Malawi pilot]
    reasoning: Expansion only.
    source: research brief
    status: deferred
    revisit_when: Spark plans an expansion beyond Malawi.
    owner: Spark
    evidence_basis: stated
    plain: Not needed for this pilot.
  - id: sol-devices-and-system-of-record-2208
    phase: 8-solicitation-management
    skill: solicitation-create
    question: Does the listing ask about CBF smartphones/connectivity?
    ai-default: Not asked; rate all-in with CBF vs organisation split
    override: Ask about devices; devices costed separately
    options:
      - Not asked; rate all-in with CBF vs organisation split
      - Ask about devices; devices costed separately
    reasoning: Standing operator directives.
    override_reasoning: Operator decision 2026-10-04 (Jonathan Jackson).
    source: PDD §10
    status: overridden
    evidence_basis: conflicting
    conflict_signals: [a, b]
    inherited_from_run: "20260926-1800"
"""

_OPEN_ASKS = """\
schema_version: 1
opp: spark-facilitator
run_id: 20261001-2208
generated_at: 2026-10-04T12:00:00Z
asks:
  - id: working-language
    review_ask: recommended-confirmation
  - id: rct-sample-overlap
    review_ask: required-before
    needed_by: award
"""


def _tree(*, open_asks: str | None, ledger: bool = True) -> dict:
    opp = {"opp.yaml": _OPP_YAML, "runs": {RUN: {
        "run_state.yaml": _state_yaml(), "decisions.yaml": _ASK_DECISIONS,
    }}}
    if ledger:
        opp["open-questions.md"] = _OPEN_QUESTIONS_MD
    if open_asks is not None:
        opp["open-asks.yaml"] = open_asks
    return {"ACE": {"spark-facilitator": opp}}


def _payload(**kw) -> dict:
    drive = FakeDriveClient.from_tree(_tree(**kw))
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    out = build_summary_payload(drive, workspace=ws, opp_slug="spark-facilitator", run_id=RUN)
    assert out is not None
    return out


def _row(payload: dict, row_id: str) -> dict:
    return next(r for r in payload["decisions"]["rows"] if r["id"] == row_id)


# ─── Row fields ─────────────────────────────────────────────────────


def test_inline_required_before_folds_into_review_ask_plus_needed_by():
    row = _row(_payload(open_asks=None), "rct-sample-overlap")
    assert row["review_ask"] == "required-before"
    assert row["needed_by"] == "award"
    assert row["answer_channel"] == "solicitation:q-rct-overlap"
    assert row["owner"] == "partner"


@pytest.mark.parametrize("raw,expected", [
    ({"review_ask": "required-before", "needed_by": "go-live"}, ("required-before", "go-live")),
    ({"review_ask": "required-before:closeout"}, ("required-before", "closeout")),
    # An explicit needed_by wins over the inline one.
    ({"review_ask": "required-before: award", "needed_by": "go-live"},
     ("required-before", "go-live")),
    ({"review_ask": "recommended-confirmation"}, ("recommended-confirmation", "")),
])
def test_required_before_normalisation(raw, expected):
    out = decision_extras(raw)
    assert (out["review_ask"], out["needed_by"]) == expected


def test_human_decided_and_deferred_statuses_survive():
    assert normalize_decision_status("human-decided") == "human-decided"
    assert normalize_decision_status("deferred") == "deferred"
    assert normalize_decision_status("open") == "ai-default"
    payload = _payload(open_asks=None)
    deferred = _row(payload, "rwanda-two-cbf-attribution")
    assert deferred["status"] == "deferred"
    assert deferred["revisit_when"] == "Spark plans an expansion beyond Malawi."


def test_carried_row_says_which_run_it_came_from():
    row = _row(_payload(open_asks=None), "sol-devices-and-system-of-record-2208")
    assert row["inherited_from_run"] == "20260926-1800"


def test_counts_name_each_kind_of_ask():
    counts = _payload(open_asks=None)["decisions"]["counts"]
    assert counts["to_confirm"] == 1
    assert counts["to_answer"] == 1
    assert counts["deferred"] == 1
    # An overridden row still counts as changed by a human.
    assert counts["overridden"] == 1


# ─── open-asks.yaml vs the legacy ledger ────────────────────────────


def test_without_open_asks_the_legacy_ledger_is_still_read():
    oq = _payload(open_asks=None)["open_questions"]
    assert oq["source"] == "ledger"
    assert oq["asks_run_id"] is None
    assert [q["title"] for q in oq["items"]] == ["Rate confirmation", "Device reality"]


def test_open_asks_wins_and_the_ledger_is_not_repeated():
    """The asks are decision rows now; the page must not ask twice."""
    oq = _payload(open_asks=_OPEN_ASKS)["open_questions"]
    assert oq["source"] == "decisions"
    assert oq["items"] == []
    assert oq["asks_run_id"] == RUN


def test_open_asks_without_a_ledger_still_names_its_source():
    oq = _payload(open_asks=_OPEN_ASKS, ledger=False)["open_questions"]
    assert oq["source"] == "decisions"


def test_an_unreadable_open_asks_falls_back_to_the_ledger():
    oq = _payload(open_asks="::: not yaml :::\n- [")["open_questions"]
    assert oq["source"] == "ledger"
