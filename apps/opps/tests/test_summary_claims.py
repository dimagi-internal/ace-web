"""The claim set on the public run summary — "what changed because you asked".

A CLAIM is a falsifiable statement about what a run's OUTPUT must look
like, written because a named counterpart decided something between runs.
ACE's design
(``docs/superpowers/specs/2026-09-15-pre-run-claims-post-run-validation-design.md``
§ Rendering) specifies ONE reviewer-facing view in two places — the run's
ace-web page and the reply — and the page half did not exist: an anonymous
render of ``poverty-graduation/20260915-1518`` carried 23,497 characters of
text and ZERO occurrences of "claim" (ace#2420).

The fixture below is that run's real claim set, cut to four claims and with
its ~190-word audit ``evidence`` strings kept in shape, because two of the
things worth testing only exist on real data: ``evidence`` that must not
reach an anonymous reader, and a claim the counterpart authored herself.

What these tests protect is not "claims render". It is the three
properties the design leans on:

* the claim set is the DENOMINATOR, so an UNMET or NOT REACHED claim shows
  up as an accusation rather than as an absence;
* a claim the counterpart authored is marked as hers — ACE writes its own
  exam, and reviewer visibility is the only mitigation the design accepts;
* a ``judged`` verdict is qualified, so it cannot borrow a probe's
  authority.
"""
from __future__ import annotations

import pytest

from apps.opps.summary import build_summary_payload
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.opps.tests.test_summary import _FakeWorkspace, _full_tree

OPP = "turmeric"
RUN = "20260503-0835"
RUN_PATH = f"ACE/{OPP}/runs/{RUN}"

#: Four claims from `poverty-graduation/20260915-1518`, one per verdict.
#: `cs-deliver-unpaid` keeps its real `evidence` — atom signature, internal
#: field names and all — because that is the string the anonymous payload
#: must not carry.
CLAIMS_YAML = """\
schema_version: 1
kind: run-claims
opp: poverty-graduation
frozen_at: '2026-09-15T15:18:14Z'
source_run_id: '20260915-1518'
claims:
  - id: cs-deliver-unpaid
    claim: >-
      The Deliver app's consumption-support distribution visit carries no
      payment marker.
    artifact: deliver-app
    checkable_at: commcare-setup
    origin:
      kind: counterpart-decision
      person: Sophie Feintuch
      quote: >-
        Please make the Deliver app, the Connect opportunity and the support
        assistant agree on that.
    authored_by: ace
    check:
      kind: probe
      how: Parse the released Deliver CCZ.
    verdict: MET
    evidence_kind: probed
    evidence: >-
      commcare_download_ccz(domain=connect-ace-prod,
      app_id=e4594937038c42d2be4d01f45df44209) returns
      connect_markers.deliver=2 and projected_connect_state.deliver_units =
      [targeting_survey, asset_delivery] with collision_count 0.
    says: >-
      The Deliver app has no payment marker on consumption support — two
      payable activities, and no consumption form in it at all.
    checked_at: '2026-09-16T16:05:00Z'
    checked_in_phase: commcare-setup
  - id: comments-land
    claim: Sophie's nine Targeting PDD comments land in this run's design.
    artifact: composed-pdd
    checkable_at: idea-to-design
    origin:
      kind: counterpart-decision
      person: Sophie Feintuch
      quote: whether my comments land
    authored_by: counterpart
    check:
      kind: judged
      how: Read the comment threads and account for every one.
    verdict: UNMET
    evidence_kind: judged
    evidence: drive_list_comments on 1u-QzTn1G82n returns 8 threads; two unanswered.
    says: Two of your nine comments were not accounted for in this run's design.
    checked_at: '2026-09-15T16:30:00Z'
    checked_in_phase: idea-to-design
  - id: cs-assistant-unpaid
    claim: The support assistant tells workers consumption support is unpaid.
    artifact: ocs-chatbot
    checkable_at: ocs-setup
    origin:
      kind: counterpart-decision
      person: Sophie Feintuch
    authored_by: ace
    check:
      kind: judged
      how: Ask the chatbot and read the answer.
    verdict: NOT REACHED
    evidence_kind: judged
    evidence: the `ocs-setup` checkpoint never ran in this run
    says: >-
      The run never reached the point where this could be checked, so nobody
      answered it.
  - id: payment-rate-per-component
    claim: The solicitation prices each payable activity separately.
    artifact: solicitation
    checkable_at: solicitation-management
    origin:
      kind: counterpart-decision
      person: Anne Kuhlmann
    authored_by: ace
    check:
      kind: judged
      how: Read the published solicitation.
    verdict: INDETERMINATE
    evidence_kind: judged
    evidence: get_solicitation(20793) returned a draft, not the published record.
    would_settle_it: the published listing, once labs finishes indexing it
"""


def _payload(
    claims_yaml: str | None = CLAIMS_YAML, *, viewer_is_member: bool = True,
) -> dict:
    drive = FakeDriveClient.from_tree(_full_tree())
    if claims_yaml is not None:
        drive.upload_file(
            drive.folder_id(RUN_PATH), "claims.yaml", claims_yaml, "text/yaml",
        )
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    payload = build_summary_payload(
        drive, workspace=ws, opp_slug=OPP, run_id=RUN,
        viewer_is_member=viewer_is_member,
    )
    assert payload is not None
    return payload


def _all_claims(section: dict) -> list[dict]:
    return [c for group in section["people"] for c in group["claims"]]


# ─── Absence ────────────────────────────────────────────────────────


def test_a_run_with_no_claims_file_renders_no_section():
    """Most opportunities have none. A "no claims" heading on every other
    run teaches reviewers to skip the section."""
    assert _payload(None)["claims"] is None


def test_a_claims_file_with_an_empty_list_renders_no_section():
    assert _payload("schema_version: 1\nkind: run-claims\nclaims: []\n")["claims"] is None


# ─── Unreadability is LOUD ──────────────────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("claims:\n  - id: a\n   claim: bad indent\n", id="not-yaml"),
        pytest.param("- just\n- a\n- list\n", id="not-a-mapping"),
        pytest.param("schema_version: 1\nclaims: not a list\n", id="claims-not-a-list"),
    ],
)
def test_an_unreadable_claims_file_surfaces_as_a_visible_problem(body):
    """``classifyRunClaims`` reports ``ok: false`` rather than throwing, and
    the page has to match it. Silence here would put the reviewer back in
    front of a page that renders an omission as an absence — which is the
    failure the whole mechanism exists to kill."""
    section = _payload(body)["claims"]
    assert section is not None
    assert section["error"]
    assert section["people"] == []


def test_a_file_whose_rows_are_malformed_still_renders_the_readable_ones_and_says_so():
    """Dropping the unreadable rows quietly would corrupt the DENOMINATOR,
    which is the one thing this section has to get right."""
    body = CLAIMS_YAML + "  - not-a-mapping\n  - {id: '', claim: ''}\n"
    section = _payload(body)["claims"]
    assert section["total"] == 4
    assert "2 further claim" in section["error"]


# ─── Completeness — the denominator property ────────────────────────


def test_every_claim_is_carried_whichever_way_it_went():
    section = _payload()["claims"]
    assert section["total"] == 4
    verdicts = {c["id"]: c["verdict"] for c in _all_claims(section)}
    assert verdicts == {
        "cs-deliver-unpaid": "MET",
        "comments-land": "UNMET",
        "cs-assistant-unpaid": "NOT REACHED",
        "payment-rate-per-component": "INDETERMINATE",
    }


def test_the_tally_names_each_way_a_claim_went():
    section = _payload()["claims"]
    assert section["counts"] == {
        "met": 1, "unmet": 1, "not_reached": 1,
        "indeterminate": 1, "unanswered": 0,
    }
    assert section["summary"] == (
        "1/4 met, 1 not met, 1 never reached, 1 indeterminate"
    )


def test_REGRESSION_CONTROL_a_never_reached_claim_is_not_a_met_run():
    """Every ANSWERED claim passing is not "all met" when a checkpoint
    never ran. Reporting otherwise recreates the silence being removed."""
    body = CLAIMS_YAML.replace("verdict: UNMET", "verdict: MET").replace(
        "verdict: INDETERMINATE", "verdict: MET",
    )
    section = _payload(body)["claims"]
    assert section["counts"]["met"] == 3
    assert section["counts"]["not_reached"] == 1
    assert section["all_met"] is False


def test_a_claim_with_no_verdict_is_carried_as_unanswered_never_as_met():
    body = CLAIMS_YAML.replace("    verdict: MET\n", "")
    section = _payload(body)["claims"]
    assert section["counts"]["unanswered"] == 1
    assert section["counts"]["met"] == 0
    row = next(c for c in _all_claims(section) if c["id"] == "cs-deliver-unpaid")
    assert row["verdict"] is None


def test_an_unrecognised_verdict_is_carried_as_unanswered_not_coerced():
    body = CLAIMS_YAML.replace("    verdict: MET\n", "    verdict: PROBABLY\n")
    row = next(
        c for c in _all_claims(_payload(body)["claims"])
        if c["id"] == "cs-deliver-unpaid"
    )
    assert row["verdict"] is None


# ─── The two markings that make §1 safe ─────────────────────────────


def test_a_claim_the_counterpart_authored_is_marked_as_theirs():
    """The design's ONLY mitigation for ACE writing its own exam: she can
    see which bar was hers, and say so when ACE's is too low."""
    rows = {c["id"]: c["authored_by"] for c in _all_claims(_payload()["claims"])}
    assert rows["comments-land"] == "counterpart"
    assert rows["cs-deliver-unpaid"] == "ace"


def test_a_judged_verdict_is_carried_as_judged():
    rows = {c["id"]: c["evidence_kind"] for c in _all_claims(_payload()["claims"])}
    assert rows["cs-deliver-unpaid"] == "probed"
    assert rows["comments-land"] == "judged"


# ─── `says` vs `evidence` ───────────────────────────────────────────


def test_the_counterpart_facing_sentence_is_served_to_everyone():
    for member in (True, False):
        row = next(
            c for c in _all_claims(_payload(viewer_is_member=member)["claims"])
            if c["id"] == "cs-deliver-unpaid"
        )
        assert row["says"].startswith("The Deliver app has no payment marker")


def test_the_audit_evidence_never_reaches_a_non_member():
    """`evidence` is Drive file ids, MCP atom signatures and read-path
    caveats — the class `skills/agent-turn-review` § F bans from anything
    a counterpart reads (ace#2386)."""
    anon = _payload(viewer_is_member=False)
    assert all(c["evidence"] is None for c in _all_claims(anon["claims"]))
    # And not smuggled in anywhere else in the payload either.
    import json

    assert "commcare_download_ccz" not in json.dumps(anon)


def test_a_member_still_gets_the_audit_record():
    row = next(
        c for c in _all_claims(_payload()["claims"])
        if c["id"] == "cs-deliver-unpaid"
    )
    assert "commcare_download_ccz" in row["evidence"]


def test_an_indeterminate_claim_carries_what_would_settle_it():
    row = next(
        c for c in _all_claims(_payload()["claims"])
        if c["id"] == "payment-rate-per-component"
    )
    assert row["would_settle_it"] == "the published listing, once labs finishes indexing it"


# ─── Grouping ───────────────────────────────────────────────────────


def test_claims_are_grouped_by_the_person_who_asked():
    people = [g["person"] for g in _payload()["claims"]["people"]]
    assert set(people) == {"Sophie Feintuch", "Anne Kuhlmann"}
    counts = {g["person"]: len(g["claims"]) for g in _payload()["claims"]["people"]}
    assert counts == {"Sophie Feintuch": 3, "Anne Kuhlmann": 1}


def test_a_claim_with_no_recorded_person_is_still_carried():
    """Unattributed is a bad record, not a reason to drop a claim from the
    denominator."""
    body = CLAIMS_YAML.replace("      person: Anne Kuhlmann\n", "")
    section = _payload(body)["claims"]
    assert section["total"] == 4
    assert "Unattributed" in [g["person"] for g in section["people"]]
