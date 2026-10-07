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
import yaml

from apps.opps.parsers import decision_extras, normalize_decision_status
from apps.opps.summary import build_summary_payload
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.opps.tests.test_summary import (
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

_LEDGER = """\
# Open Questions — spark-facilitator

## Open

- **Rate confirmation** — never migrated. Owner: Spark. Answered in: solicitation.
"""

_STALE_OPEN_ASKS = """\
schema_version: 1
opp: spark-facilitator
run_id: 20260926-1413
generated_at: 2026-09-27T12:00:00Z
asks:
  - id: some-older-runs-ask
    review_ask: recommended-confirmation
"""


def _overrides(*rows: dict) -> str:
    return yaml.safe_dump({"schema_version": 1, "overrides": list(rows)})


def _tree(*, legacy: bool = False, overrides: str | None = None,
          decisions: str = _ASK_DECISIONS) -> dict:
    opp = {"opp.yaml": _OPP_YAML, "runs": {RUN: {
        "run_state.yaml": _state_yaml(), "decisions.yaml": decisions,
    }}}
    if legacy:
        # Both legacy files present and loud: neither may reach the payload.
        opp["open-questions.md"] = _LEDGER
        opp["open-asks.yaml"] = _STALE_OPEN_ASKS
    if overrides is not None:
        opp["inputs"] = {"decision-overrides.yaml": overrides}
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
    row = _row(_payload(), "rct-sample-overlap")
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
    payload = _payload()
    deferred = _row(payload, "rwanda-two-cbf-attribution")
    assert deferred["status"] == "deferred"
    assert deferred["revisit_when"] == "Spark plans an expansion beyond Malawi."


def test_carried_row_says_which_run_it_came_from():
    row = _row(_payload(), "sol-devices-and-system-of-record-2208")
    assert row["inherited_from_run"] == "20260926-1800"


def test_counts_name_each_kind_of_ask():
    counts = _payload()["decisions"]["counts"]
    assert counts["to_confirm"] == 1
    assert counts["to_answer"] == 1
    assert counts["deferred"] == 1
    # An overridden row still counts as changed by a human.
    assert counts["overridden"] == 1


# ─── Open asks are a FILTER of the run's decision rows ─────────────
#
# Operator decision 2026-10-07 (Jonathan Jackson): "why isn't that just a
# filter of decisions … when we created the new system we should not have
# carried forward any legacy models". ACE contract: docs/decisions-contract.md
# § Open asks — an open ask is a live row with an unanswered review_ask, or a
# status: deferred row; "answered" = overridden / human-decided, or a saved
# ruling in inputs/decision-overrides.yaml binds to it.


def test_open_asks_are_derived_from_the_runs_decision_rows():
    asks = _payload()["open_asks"]
    assert asks["confirm"] == {"total": 1, "outstanding": 1}
    assert asks["answer"]["total"] == 1
    assert asks["answer"]["outstanding"] == 1
    assert asks["answer"]["by_needed_by"] == {"award": {"total": 1, "outstanding": 1}}
    assert asks["deferred"] == 1
    assert asks["total"] == 2
    assert asks["outstanding"] == 2
    # Deferred is parked, never asked; the overridden row asks nothing.
    assert asks["outstanding_ids"] == ["working-language", "rct-sample-overlap"]


def test_a_saved_confirmation_answers_the_ask():
    asks = _payload(overrides=_overrides({
        "id": "working-language",
        "override": "English source plus Chichewa (nya) and Tumbuka (tum)",
        "ai_default": "English source plus Chichewa (nya) and Tumbuka (tum)",
        "confirmed": True,
        "decided_by_name": "Anne",
    }))["open_asks"]
    assert asks["confirm"] == {"total": 1, "outstanding": 0}
    assert asks["outstanding_ids"] == ["rct-sample-overlap"]


def test_a_saved_change_answers_a_required_before_ask():
    asks = _payload(overrides=_overrides({
        "id": "rct-sample-overlap",
        "override": "No overlap: exclude every trial community",
        "ai_default": "OPEN",
        "decided_by_name": "Anne",
    }))["open_asks"]
    assert asks["answer"]["outstanding"] == 0
    assert asks["answer"]["by_needed_by"]["award"] == {"total": 1, "outstanding": 0}


def test_a_bare_revert_is_not_an_answer():
    asks = _payload(overrides=_overrides({
        "id": "working-language",
        "override": "English source plus Chichewa (nya) and Tumbuka (tum)",
        "ai_default": "English source plus Chichewa (nya) and Tumbuka (tum)",
        "decided_by_name": "Anne",
    }))["open_asks"]
    assert asks["confirm"]["outstanding"] == 1


@pytest.mark.parametrize("status", ["human-decided", "overridden"])
def test_a_row_a_person_already_ruled_on_is_answered(status):
    decisions = _ASK_DECISIONS.replace(
        "    status: ai-default\n    evidence_basis: stated\n"
        "    plain_question: Have the Chichewa",
        f"    status: {status}\n    evidence_basis: stated\n"
        "    plain_question: Have the Chichewa",
    )
    assert decisions != _ASK_DECISIONS
    asks = _payload(decisions=decisions)["open_asks"]
    assert asks["confirm"] == {"total": 1, "outstanding": 0}


def test_a_superseded_row_never_asks():
    decisions = _ASK_DECISIONS.replace(
        "    review_ask: \"required-before: award\"\n",
        "    review_ask: \"required-before: award\"\n    superseded_by: working-language\n",
    )
    asks = _payload(decisions=decisions)["open_asks"]
    assert asks["answer"]["total"] == 0
    assert asks["answer"]["by_needed_by"] == {}


def test_a_run_without_a_decisions_log_has_no_open_asks():
    tree = _tree(legacy=True)
    del tree["ACE"]["spark-facilitator"]["runs"][RUN]["decisions.yaml"]
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    out = build_summary_payload(drive, workspace=ws, opp_slug="spark-facilitator", run_id=RUN)
    assert out["open_asks"] is None


def test_legacy_ledger_and_open_asks_yaml_are_never_read():
    """The spark workspace case: a never-migrated ledger and a stale
    open-asks.yaml sit at the opp root. Neither reaches the payload, and
    neither file is even opened."""
    drive = FakeDriveClient.from_tree(_tree(legacy=True))
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    ledger_id = drive.file_id("ACE/spark-facilitator/open-questions.md")
    asks_id = drive.file_id("ACE/spark-facilitator/open-asks.yaml")
    opened: list[str] = []
    real_get = drive.get_content

    def spy(file_id, *a, **kw):
        opened.append(file_id)
        return real_get(file_id, *a, **kw)

    drive.get_content = spy  # type: ignore[method-assign]
    out = build_summary_payload(drive, workspace=ws, opp_slug="spark-facilitator", run_id=RUN)
    assert out is not None
    assert "open_questions" not in out
    # The spy is live: the run's own decisions log WAS read through it.
    assert drive.file_id(f"ACE/spark-facilitator/runs/{RUN}/decisions.yaml") in opened
    assert ledger_id not in opened
    assert asks_id not in opened
    assert out["open_asks"]["outstanding_ids"] == ["working-language", "rct-sample-overlap"]
