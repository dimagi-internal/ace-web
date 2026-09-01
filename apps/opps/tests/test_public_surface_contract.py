"""FROZEN CONTRACT for the public run-summary payload.

    https://labs.connect.dimagi.com/ace/opps/<ws>/<opp>/runs/<run>/summary

This module is deliberately brittle. It is not a behaviour test — every
other file in this directory tests behaviour. This one freezes the WIRE
NAMES of ``apps.opps.summary.build_summary_payload``'s output, because
that payload is an external contract with two consumers that cannot see
each other:

1. ``frontend/src/pages/OppSummaryPage.tsx`` — the page an external
   partner reads. It is the only page we hand to people with no Dimagi
   account.
2. ``scripts/audit-run-surface.py`` in the sibling ``ace`` plugin repo —
   an anonymous auditor that probes this surface and keys on the EXACT
   key names asserted below.

**If a test in this file fails, the correct first move is NOT to update
the expected value.** A failure here means one of:

  * a key was renamed  → the page and the auditor both go silently blind
    to that section, and BOTH of them render the absence as "Not
    created" rather than as an error;
  * a section was dropped → same, silently;
  * a new secret-shaped value reached an anonymous payload → decide
    explicitly, in review, whether it may be published.

Only change an expected literal here in the same commit that changes
every consumer, and say so in the PR.

Why this file exists at all
---------------------------
On 2026-08-14 the first external partner (``spark-facilitator /
20260813-2126``) was sent this page. It was badly wrong in five separate
ways and every automated check reported green. A human found all five by
eye, in a day. The individual bugs are fixed; these are the structural
invariants that stop them recurring:

* **A key-name mismatch is invisible at runtime — it renders as
  absence.** The page said walkthroughs and dashboards were "Not
  created" while both existed, because the reader looked for
  ``url``/``title`` where the run had written ``par_url``/``key`` nested
  under ``synthetic.source``. Nothing threw. Nothing logged an error a
  reviewer would see. The page simply said the work did not exist.
* **The same trap on the reading side.** An auditor that counted a
  payload key named ``questions`` when the field is ``items`` reported 0
  open questions forever, and nearly sent someone to "fix" a feature
  that worked.
* **An untagged link reads to an outsider as broken, not deliberate.**
  Every link-bearing object must declare ``access``.
* **A relative URL is invisible to a link checker that filters on
  ``startswith("http")``.** The footer's "See the full build process"
  link 404'd anonymously on every run for exactly that reason.
* **A privately captured review must not leak through a derived view.**

See ``docs/learnings/public-summary-link-access.md``,
``public-summary-embed-key.md``, and ``public-summary-editing.md``.
"""
from __future__ import annotations

import re
from typing import Any

import pytest
import yaml

from apps.opps.summary import (
    ACCESS_ADMIN,
    ACCESS_PUBLIC,
    ACCESS_UNKNOWN,
    build_summary_payload,
)
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient

# Reused, never re-invented: one fake Drive and one fixture vocabulary for
# the whole summary suite. A second fake would drift from the first, and
# a contract test asserted against a divergent fixture is worse than no
# contract test.
from apps.opps.tests.test_summary import (
    _DECISIONS_YAML,
    _OPEN_QUESTIONS_MD,
    _OPP_YAML,
    _FakeWorkspace,
    _state_yaml,
)

OPP_SLUG = "turmeric"
RUN_ID = "20260503-0835"

#: The DDD loop's own qualifiers on a walkthrough (ace-web#740). Frozen
#: as a set because dropping ANY of them puts a bare score back on the
#: page: on ``spark-facilitator/20260820-0817`` the run state recorded
#: ``ddd_terminal_status: stopped_not_converged``,
#: ``ddd_iterations_completed_end_to_end: 0``,
#: ``ddd_render_measures_pre_fix_artifact: true`` and a
#: ``ddd_honesty_note`` beginning "READ THIS BEFORE QUOTING THE 2.0" —
#: and the payload carried none of them, so the page showed a score and
#: linked a video that films a product four fixes out of date.
_DDD_KEYS = frozenset({
    "terminal_status", "iterations_completed", "measures_pre_fix_artifact", "note",
})


# ─── The maximal fixture ────────────────────────────────────────────
#
# Every section populated, so an omission shows up as a missing key
# rather than as a legitimately-null section. Partial-data behaviour is
# already covered in test_summary.py; this fixture exists to make the
# payload's full shape observable in one place.


def _maximal_state_yaml() -> str:
    """Every section populated — including the two that are ``None`` on a
    healthy run (``build``, ``synthetic``), because
    ``test_the_maximal_fixture_really_populates_every_section`` is the
    guard that stops a frozen key set from passing vacuously.
    """
    import yaml as _yaml

    state = _yaml.safe_load(_maximal_products_yaml())
    # Phase-LEVEL keys (not products): the Phase Write-Back Contract's
    # {status, verdict, steps}. `_state_yaml` only writes `products`.
    state["phases"]["commcare-setup"].update({
        "status": "partial",
        "verdict": "partial-deliver-eval-blocked-on-phase1-gap",
        "status_note": (
            "Both apps shipped. The phase does not claim pass because "
            "pdd-to-deliver-app-eval fails a hard gate owned by Phase 1."
        ),
        "steps": {
            "pdd-to-learn-app": {"status": "done", "verdict": "pass"},
            "pdd-to-deliver-app-eval": {
                "status": "done",
                "verdict": "fail",
                "blocker_open_detail": (
                    "entity_state_fidelity - PDD declares no "
                    "entity_state_taxonomy row."
                ),
            },
        },
    })
    # The other half of every `deep_qa.stages[].freshness` comparison.
    # `_read_deep_qa` compares the verdict's own identifier against these
    # EXACT fields and emits nothing when either side is missing, so a
    # fixture that omitted them would leave the freshness list empty and
    # the frozen key set below passing vacuously.
    apps = state["phases"]["commcare-setup"]["products"]["apps"]
    apps["learn"]["released_build_id"] = "5b403ead83ed410b85b9083fe3835d5c"
    apps["deliver"]["released_build_id"] = "b08533bdf26a48a295a362ff204fb88d"
    state["phases"]["ocs-setup"]["products"]["ocs_chatbot"]["published_version"] = 3
    state["blocker_dispositions"] = {
        "phase3_entity_state_fidelity": {
            "phase": "commcare-setup",
            "gate": "entity_state_fidelity",
            "disposition": "CARRIED FORWARD - run proceeded to Phase 4",
            "residual_accepted": (
                "Learn-taught vocabulary vs Deliver-shipped vocabulary "
                "was NOT machine-verified this run."
            ),
        },
    }
    return _yaml.dump(state)


#: Stage A of ``/ace:qa-deep``. Shape and values follow
#: ``spark-facilitator/20260828-0703``, which is the run this section was
#: built for: **8.03 against a 7.0 threshold, and the gate is still
#: ``iterate``**, because ``--deep`` requires zero Fail entries and two
#: prompts fabricated safety-adjacent operational procedure. A fixture
#: that scored badly would not test the thing worth testing — the whole
#: point is that a good-looking number and a failing gate coexist.
_OCS_DEEP_VERDICT = """\
skill: ocs-chatbot-eval
target: 13033
mode: deep
ran_at: 2026-09-01T15:05:00Z
capture_path: 5-ocs/ocs-chatbot-qa_transcript-deep.md
published_version: 3
overall_score: 8.03
overall_score_pre_cap: 8.03
verdict: warn
dimensions:
  correctness: {score: 7.23, weight: 0.30}
  refusal_correctness: {score: 7.78, weight: 0.20}
per_item:
  - ref: opp-1
    prompt: What is this opportunity about?
    score: 8.7
    verdict: pass
    note: Accurate and rule-compliant.
  - ref: opp-29
    score: 6.0
    verdict: warn
    note: Gives the escalation contact as ace@dimagi.com; the address is wrong.
  - ref: opp-50
    score: 3.0
    verdict: fail
    note: Improvised a cash-handover pathway the design does not contain.
  - ref: opp-56
    score: 3.0
    verdict: fail
    note: Invented a PersonalID recovery chain the PDD does not specify.
auto_surfaced:
  - severity: BLOCKER
    message: >-
      [FABRICATED-OPERATIONAL-SPECIFIC] opp-50 declined the cash request
      correctly and then improvised the handover procedure. Clamped to 3.0.
  - severity: WARN
    message: >-
      [INFLATION-GUARD] The same factual error appears in two entries.
gate:
  threshold: 7.0
  disposition: iterate
  rationale: >-
    8.03 clears the 7.0 threshold, but --deep is "overall >= 7 AND every Fail
    resolved" and this suite carries two Fails.
"""

#: Stage B. Deliberately points at a build id that is NOT the one
#: ``products.apps.deliver.released_build_id`` names, so the maximal
#: fixture exercises BOTH directions of the freshness comparison at once
#: — Stage A current, Stage B stale. Phase 9 ``llo-launch`` refuses
#: activation on a stale verdict, so "which build was this measured
#: against" is the load-bearing fact, not a detail.
_APP_DEEP_VERDICT = """\
skill: app-ux-eval
target: turmeric
mode: deep
ran_at: "2026-09-01T16:40:00-04:00"
capture_path: 6-qa-and-training/app-screenshot-capture_manifest.yaml
artifact_refs:
  deliver_build_id: 0000000000000000000000000000dead
overall_score: 5.7
overall_score_pre_cap: 5.9
verdict: fail
dimensions:
  clarity: {score: 8.6, weight: 0.15}
  capture_robustness: {score: 2.9, weight: 0.30}
per_item:
  - ref: journey-deliver-registration
    journey: journey-deliver-registration
    is_smoke: false
    score: 7.8
    verdict: pass
    note: The strongest journey in the set.
  - ref: journey-deliver-followup-preload
    journey: journey-deliver-followup-preload
    is_smoke: false
    score: 2.8
    verdict: fail
    note: The community case did not advance after a submitted and synced visit.
auto_surfaced:
  - severity: BLOCKER
    message: >-
      Case state stale after submit-and-sync; the recipe criterion asserted the
      row exists, never that the date moved.
gate:
  threshold: 7.0
  disposition: reject
  rationale: >-
    5.7 is below the 7.0 threshold and five of seven journeys fail.
"""


def _maximal_products_yaml() -> str:
    return _state_yaml(
        design={
            "pdd": {
                "title": "Turmeric Market Survey",
                "description": "FLWs visit markets to photograph turmeric vendors.",
                "file_id": "fake-pdd",
            },
            "work_order": {
                "title": "Work Order",
                "web_view_link": "https://docs.google.com/document/d/fake-wo/edit",
            },
        },
        closeout={
            "cycle_grade": {
                "letter": "A-",
                "headline": "Hit launch on time",
                "overall_score": 88,
            },
            "opp_eval": {"mode": "deep", "overall_score": 82, "verdict": "pass"},
            "learnings": {
                "summary_file_id": "fake-learnings",
                "summary_web_view_link": "https://docs.google.com/document/d/fake-l/edit",
                "new_pdd_file_id": "fake-new-pdd",
                "new_pdd_web_view_link": "https://docs.google.com/document/d/fake-n/edit",
                "iteration_warranted": True,
            },
        },
        **{
            "synthetic-data-and-workflows": {
                "synthetic": {
                    "walkthroughs": [
                        # available
                        {
                            "persona": "llo-weekly-review",
                            "slideshow_url": "https://drive.google.com/file/d/w1/view",
                            "eval_score": 8.4,
                        },
                        # withheld — produced, failed its concept eval. This
                        # entry is the reason (c) excludes walkthroughs: it
                        # carries `availability`, not `access`, and its `url`
                        # is null on purpose.
                        {
                            "persona": "program-admin-audit",
                            "slideshow_url": "https://drive.google.com/file/d/w2/view",
                            "eval_verdict": "fail",
                        },
                        # unavailable — produced, NOT withheld, but carrying
                        # no URL under any key this reader knows. It stays on
                        # the page; dropping it is what shipped as
                        # `walkthroughs: []` on a real run (ace#1432).
                        {
                            "persona": "field-supervisor-daily",
                            "eval_verdict": "pass",
                        },
                        # available, but behind Dimagi OAuth — and the RUN
                        # says so. Before ace-web#726 the reader stamped
                        # every entry `access: public`, so a canopy-web DDD
                        # package was advertised to anonymous readers as
                        # openable. `auth-gated` normalises to `admin`; the
                        # payload vocabulary stays two-valued.
                        {
                            "persona": "coverage-you-can-audit",
                            "web_view_link": (
                                "https://labs.connect.dimagi.com/canopy/ddd/"
                                "coverage-integrity/coverage-integrity-2026-08-26-001"
                            ),
                            "eval_score": 6.1,
                            "access": "auth-gated",
                        },
                    ],
                    "dashboards": [
                        {
                            "title": "FLW field verification",
                            "url": "https://labs.connect.dimagi.com/dashboards/d1",
                        },
                    ],
                    # The provenance of every number the two sections
                    # above show. Shape verified against
                    # spark-facilitator/20260828-0703.
                    "source": {
                        "provider": "ace-run",
                        "labs_synthetic_opp_id": 10054,
                        "record_counts": {
                            "user_visits": 223,
                            "user_data": 12,
                            "completed_works": 0,
                        },
                        "data_shape": {
                            "rows": 12,
                            "rows_population": (
                                "user_data \u2014 the facilitator cohort"
                            ),
                        },
                    },
                },
            },
            "solicitation-management": {
                "solicitation": {
                    "url": "https://labs.connect.dimagi.com/solicitations/abc/",
                    "deadline": "2026-06-15",
                    "status": "open",
                },
                "selected_llo": {
                    "org_slug": "acme-health",
                    "org_display_name": "Acme Health Workers",
                    "contact_email": "ops@acme.health",
                    "awarded_at": "2026-06-01T12:00:00Z",
                },
            },
            "execution-management": {
                "launch": {
                    "went_live_at": "2026-06-20T09:00:00Z",
                    "llo_org_display_name": "Acme Health Workers",
                },
            },
        },
    )


_PUBLIC_REACTION_RECORD = yaml.safe_dump({
    "schema_version": 1,
    "slug": "20260814-public-anne-kuhlmann",
    "reviewer": "Anne Kuhlmann",
    "reviewer_email": "anne@example.org",
    "received_at": "2026-08-14",
    "channel": "public-summary",
    "against_run": RUN_ID,
    "items": [{
        "id": "payment-rate",
        "verbatim": "USD 4 matches what we pay today.",
        "anchor": "decision:payment-rate · What is the per-visit rate?",
    }],
})

_PRIVATE_REVIEW_RECORD = yaml.safe_dump({
    "schema_version": 1,
    "slug": "20260727-sophie-feintuch",
    "reviewer": "Sophie Feintuch",
    "received_at": "2026-07-27",
    "channel": "gdoc-comments",
    "items": [{"id": "d", "verbatim": "This was said in confidence."}],
})

_SAVED_OVERRIDES = yaml.safe_dump({
    "schema_version": 1,
    "overrides": [{
        "id": "archetype-selection",
        "override": "focus-group",
        "override_reasoning": "The pilot runs as group sessions.",
        "decided_by": "anne@example.org",
        "decided_by_name": "Anne Kuhlmann",
        "decided_by_verified": False,
        "decided_at": "2026-08-14T10:00:00+00:00",
        "source_run_id": RUN_ID,
        "history": [],
    }],
})


def _maximal_tree() -> dict:
    """One opp, one run, every payload section reachable.

    Two feedback ledgers side by side — one rendered from a PRIVATE
    review, one from a reaction left on this very page — because the
    confidentiality invariant in (e) is only meaningful when there is
    something for it to hide AND something for it to keep.
    """
    return {
        "ACE": {
            OPP_SLUG: {
                "opp.yaml": _OPP_YAML,
                "open-questions.md": _OPEN_QUESTIONS_MD,
                "inputs": {"decision-overrides.yaml": _SAVED_OVERRIDES},
                "feedback": {
                    "20260727-sophie-feintuch.yaml": _PRIVATE_REVIEW_RECORD,
                    "20260727-sophie-feintuch-ledger": "# Feedback ledger\n",
                    "20260814-public-anne-kuhlmann.yaml": _PUBLIC_REACTION_RECORD,
                    "20260814-public-anne-kuhlmann-ledger": "# Feedback ledger\n",
                },
                "runs": {
                    RUN_ID: {
                        "run_state.yaml": _maximal_state_yaml(),
                        "decisions.yaml": _DECISIONS_YAML,
                        # `/ace:qa-deep`'s two outputs, at the paths it
                        # documents. Nothing in `run_state.yaml` points
                        # at them — their PRESENCE is the signal the
                        # deep gate ran, and their absence is what makes
                        # the section vanish on every other run.
                        "5-ocs": {
                            "ocs-chatbot-eval_verdict-deep.yaml": _OCS_DEEP_VERDICT,
                        },
                        "6-qa-and-training": {
                            "app-ux-eval_verdict-deep.yaml": _APP_DEEP_VERDICT,
                        },
                    },
                },
            },
        },
    }


#: The maximal fixture's Drive ACLs, mirroring what an anonymous probe
#: actually found on ``spark-facilitator/20260820-0817`` (ace-web#740):
#: the design docs answer 401 to a reader with no account, the training
#: pack is anyone-with-link readable, and the internal working artifacts
#: are not. Encoded here rather than defaulted in the fake so that
#: "maximal" means "every fact declared", not "every fact assumed".
_MAXIMAL_LINK_SHARING = {
    "fake-pdd": False,
    "fake-wo": False,
    "fake-learnings": False,
    "fake-deck": True,
    "fake-llo": True,
    "fake-flw": True,
    "fake-qr": True,
    "fake-faq": True,
    "fake-onb": True,
}

#: Drive files the fixture creates as tree nodes, so their ids are only
#: knowable after the tree is built. Path -> anyone-with-link?
_MAXIMAL_LINK_SHARING_BY_PATH = {
    f"ACE/{OPP_SLUG}/open-questions.md": False,
    f"ACE/{OPP_SLUG}/feedback/20260727-sophie-feintuch-ledger": False,
    f"ACE/{OPP_SLUG}/feedback/20260814-public-anne-kuhlmann-ledger": True,
}


def _build(*, viewer_is_member: bool = True) -> dict:
    drive = FakeDriveClient.from_tree(_maximal_tree())
    for file_id, shared in _MAXIMAL_LINK_SHARING.items():
        drive.set_link_shared(file_id, shared)
    for path, shared in _MAXIMAL_LINK_SHARING_BY_PATH.items():
        drive.set_link_shared(drive.file_id(path), shared)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    payload = build_summary_payload(
        drive, workspace=ws, opp_slug=OPP_SLUG, run_id=RUN_ID,
        viewer_is_member=viewer_is_member,
    )
    assert payload is not None, "the maximal fixture must always build a payload"
    return payload


@pytest.fixture
def payload() -> dict:
    """The member view of the maximal run."""
    return _build(viewer_is_member=True)


@pytest.fixture
def anon_payload() -> dict:
    """The view an external partner with the link actually gets."""
    return _build(viewer_is_member=False)


# ─── Generic payload walker ─────────────────────────────────────────


def _walk(node: Any, path: str = ""):
    """Yield ``(dotted_path, node)`` for every node in the payload.

    List membership collapses to a ``[]`` segment rather than an index,
    so paths are stable regardless of how many entries a run produced —
    ``feedback[].url``, not ``feedback[0].url``. That is what lets the
    expected sets below be literals a human can read.
    """
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, f"{path}[]")


def _dicts(payload: dict):
    for path, node in _walk(payload):
        if isinstance(node, dict):
            yield path, node


# ─── (a) The frozen top-level key set ───────────────────────────────
#
# The ACE auditor (`scripts/audit-run-surface.py` in the `ace` repo)
# reads exactly these names off an anonymous fetch of this payload. A
# key added here without telling it is a section the auditor will never
# check; a key REMOVED is a section it will report as missing forever.

PUBLIC_PAYLOAD_KEYS = frozenset({
    "opp",
    "design",
    "apps",
    # The producing phase's verdict on `apps`. Added with ace#1867 /
    # ace-web#744: a `partial` Phase 3 rendered identically to a clean
    # one, so the page's only status vocabulary was "done" vs "not
    # started". `null` on a clean run — the auditor must read absence as
    # "nothing to flag", not as a missing section.
    "build",
    # The `/ace:qa-deep` gate's own verdicts. `null` on every run that
    # never took the deep gate — the auditor must read absence as "the
    # gate was not run", NOT as a missing section, because the two
    # verdict files ARE the only record that it was.
    "deep_qa",
    "connect",
    "training",
    "assistant",
    "walkthroughs",
    "dashboards",
    # What `dashboards` and `walkthroughs` are showing numbers OF. Phase
    # 7 GENERATES its dataset and the page never said so; a reader took
    # 223 invented visit records for observations (ace#1867).
    "synthetic",
    "selected_llo",
    "solicitation",
    "launch",
    "cycle_grade",
    "opp_eval",
    "learnings",
    "open_questions",
    "stage",
    "feedback",
    "decisions",
    "reactions",
    "decision_edits",
    "workbench",
    "viewer",
})


def test_the_top_level_key_set_is_frozen(payload):
    """Extra or missing top-level keys fail, both directions.

    Adding a section is a contract change: the auditor and the page both
    need to learn about it. Removing one is a contract break. Neither
    should be able to happen as a side effect of an unrelated edit.
    """
    assert set(payload) == PUBLIC_PAYLOAD_KEYS


def test_the_maximal_fixture_really_populates_every_section(payload):
    """The guard on (b): a frozen key set proves nothing if the fixture
    left the section null, because ``None`` has no keys to check."""
    empty = [
        key for key in PUBLIC_PAYLOAD_KEYS
        if payload[key] is None or payload[key] == [] or payload[key] == {}
    ]
    assert empty == [], f"maximal fixture left these sections empty: {empty}"


# ─── (b) Frozen per-section link/label key names ────────────────────
#
# One entry per shape an external consumer reads. The VALUES are
# behaviour (tested in test_summary.py); these are the NAMES, and a
# rename is exactly the failure that renders as "Not created" with no
# error anywhere.
#
# `synthetic.source.par_url` is why: Phase 7 wrote its dashboards under a
# key the reader had never heard of, so two live dashboards rendered as
# absent. And `items` is why on the reading side: an auditor that looked
# for `questions` counted zero open questions forever.

SECTION_KEYS: dict[str, frozenset[str]] = {
    "opp": frozenset({
        "workspace_slug", "slug", "run_id", "display_name",
        "description", "status", "end_date",
    }),
    "design": frozenset({"docs"}),
    "design.docs[]": frozenset({"title", "url", "access"}),
    "apps[]": frozenset({"kind", "name", "hq_url", "access"}),
    # A `partial` phase must be able to SAY it is partial. `note` is the
    # run's own prose and is preferred over anything the page phrases.
    "build": frozenset({
        "status", "verdict", "note", "failing_checks", "carried_blockers",
    }),
    "build.failing_checks[]": frozenset({"name", "verdict", "detail"}),
    "build.carried_blockers[]": frozenset({
        "id", "gate", "disposition", "residual_accepted",
    }),
    # Both stages are always present when the section is; a stage that
    # did not run keeps every key and nulls the values, so "Stage B has
    # not been run" is something the payload SAYS rather than something a
    # reader infers from a shorter list.
    "deep_qa": frozenset({"stages"}),
    "deep_qa.stages[]": frozenset({
        # `gate` and `counts.fail` are the load-bearing pair, and `score`
        # is context. Dropping either would put a bare number back on the
        # page: on spark-facilitator/20260828-0703 Stage A scores 8.03
        # against a 7.0 bar and its gate is `iterate` anyway, because
        # --deep requires zero Fails and two prompts fabricated
        # safety-adjacent procedure. "8.03" beside a tick reads as
        # ready-to-launch. It is not.
        "stage", "label", "ran", "ran_at", "gate", "verdict", "score",
        "threshold", "counts", "dimensions", "findings", "items",
        # Phase 9 `llo-launch` refuses activation on a MISSING **or
        # STALE** deep verdict, so what the verdict was measured against
        # is part of the verdict.
        "freshness", "is_stale",
    }),
    "deep_qa.stages[].counts": frozenset({"total", "pass", "warn", "fail"}),
    "deep_qa.stages[].dimensions[]": frozenset({"name", "score", "weight"}),
    "deep_qa.stages[].findings[]": frozenset({"severity", "message"}),
    "deep_qa.stages[].items[]": frozenset({"ref", "verdict", "score", "note"}),
    "deep_qa.stages[].freshness[]": frozenset({
        "basis", "verdict_value", "current_value", "is_current",
    }),
    "connect": frozenset({"opportunity"}),
    "connect.opportunity": frozenset({
        "name", "url", "start_date", "end_date", "access",
    }),
    "training": frozenset({"deck", "docs"}),
    "training.deck": frozenset({"title", "url", "access"}),
    "training.docs[]": frozenset({"title", "url", "access"}),
    # `knowledge_sources` (ace-web#740) is what the run recorded the
    # assistant as actually indexing. It is a LIST, empty when the run
    # recorded nothing, and the page's claim about what the bot knows is
    # conditional on it — the sentence used to be a constant string that
    # named a training pack the collection did not contain.
    "assistant": frozenset({
        "ocs_url", "access", "public_id", "embed_key", "knowledge_sources",
    }),
    # `walkthroughs[]` is deliberately absent: it has THREE legal shapes
    # (available / withheld / unavailable), so a single frozen key set
    # would be a lie. All three are frozen below, one test each.
    "dashboards[]": frozenset({"title", "url", "access"}),
    # Read from the run's own `products.synthetic.source`; nothing here
    # is hardcoded, so a rename here silently un-labels generated data.
    "synthetic": frozenset({
        "is_synthetic", "provider", "labs_opp_id", "visits",
        "completed_works", "cohort_size", "cohort_population",
    }),
    "selected_llo": frozenset({
        "org_slug", "org_display_name", "contact_email", "awarded_at",
    }),
    "solicitation": frozenset({"url", "deadline", "status", "access"}),
    "launch": frozenset({"went_live_at", "llo_org_display_name"}),
    "cycle_grade": frozenset({"letter", "headline", "overall_score"}),
    "opp_eval": frozenset({"overall_score", "verdict", "mode"}),
    "learnings": frozenset({
        "summary_url", "new_pdd_url", "iteration_warranted", "access",
    }),
    # The list key is `items`. NOT `questions`.
    "open_questions": frozenset({"url", "access", "items"}),
    # `blocking` — when the question has to be answered by. The ledger
    # always carried it; the reader discarded it, so a question gating
    # Phase 8 looked the same as a post-pilot one (ace#1867).
    "open_questions.items[]": frozenset({
        "title", "detail", "owner", "answered_in", "blocking",
    }),
    "stage": frozenset({"label", "pending_sections"}),
    "feedback[]": frozenset({"title", "url", "access"}),
    "decisions": frozenset({"total", "counts", "rows"}),
    "decisions.counts": frozenset({
        "stated", "inferred", "conflicting", "overridden",
    }),
    # Projected through the SAME `serialize_decision` the Workbench uses,
    # plus the two grouping fields this surface adds. One shape, two
    # surfaces, no drift.
    "decisions.rows[]": frozenset({
        "id", "phase", "phase_raw", "phase_label", "phase_ordinal", "skill",
        "question", "ai_default", "override", "options_considered", "source",
        "status", "notes", "override_reasoning", "evidence_basis",
        "conflict_signals",
    }),
    "reactions": frozenset({"total", "by_decision"}),
    "workbench": frozenset({"url", "access"}),
    "viewer": frozenset({"is_member"}),
}


@pytest.mark.parametrize("path", sorted(SECTION_KEYS))
def test_section_key_names_are_frozen(payload, path):
    """One assertion per shape. Parametrised so a rename names itself in
    the failure line instead of hiding inside a bulk diff.

    EVERY occurrence at a path is checked, not just the first — a list
    whose entries disagree on their keys is exactly the drift that made
    two live dashboards render as "Not created".
    """
    observed = [node for p, node in _dicts(payload) if p == path]
    assert observed, f"the maximal fixture produced nothing at {path!r}"
    for node in observed:
        assert set(node) == SECTION_KEYS[path], path


def test_an_available_walkthrough_declares_its_link_and_access(payload):
    """The linkable shape. `availability` rides alongside `access` rather
    than replacing it, so the page can tell "openable" from "produced but
    withheld" without inspecting the URL."""
    available = [w for w in payload["walkthroughs"] if w["availability"] == "available"]
    assert available, "the maximal fixture must include an available walkthrough"
    for entry in available:
        assert set(entry) == {
            "persona", "url", "eval_score", "availability", "withheld_reason",
            "access", "ddd",
        }
        assert entry["url"]
        assert entry["access"] in (ACCESS_PUBLIC, ACCESS_ADMIN)
        assert set(entry["ddd"]) == _DDD_KEYS


def test_a_withheld_walkthrough_still_declares_why(payload):
    """The one shape (b) can't pin with a single key set: a withheld
    entry drops `access` (there is nothing to open) and MUST carry a
    reason. Telling a reviewer something does not exist, when it does and
    we chose not to show it, is the failure this replaced."""
    withheld = [w for w in payload["walkthroughs"] if w["availability"] == "withheld"]
    assert withheld, "the maximal fixture must include a withheld walkthrough"
    for entry in withheld:
        assert set(entry) == {
            "persona", "url", "eval_score", "availability", "withheld_reason",
            "ddd",
        }
        assert entry["url"] is None
        assert entry["withheld_reason"]
        assert set(entry["ddd"]) == _DDD_KEYS


def test_an_unavailable_walkthrough_is_present_rather_than_dropped(payload):
    """The third shape, and the one that cost a real run. A walkthrough
    that passed but whose URL came through under a key the reader did not
    recognise used to be dropped, so the page served `walkthroughs: []`
    while the video sat published in Drive. Silence there is worse than
    withholding: withholding says "we have it and are not showing you",
    an empty list says "there is nothing". Same keys as withheld — no
    `access`, because there is nothing to open — and a reason is
    mandatory."""
    entries = [w for w in payload["walkthroughs"] if w["availability"] == "unavailable"]
    assert entries, "the maximal fixture must include an unavailable walkthrough"
    for entry in entries:
        assert set(entry) == {
            "persona", "url", "eval_score", "availability", "withheld_reason",
            "ddd",
        }
        assert entry["url"] is None
        assert entry["withheld_reason"]
        assert set(entry["ddd"]) == _DDD_KEYS


def test_a_run_declared_access_tag_survives_into_the_payload(payload):
    """ace-web#726. The reader used to stamp `access: public` on every
    walkthrough regardless of what the run wrote, so a canopy-web page
    behind Dimagi OAuth was advertised to anonymous readers as openable
    — worse than a dead link, because it reads as an invitation, and it
    is exactly what the ACE auditor calls LINK-ACCESS-MISLABELLED.

    The run's own tag wins. It is normalised into this module's
    two-valued vocabulary rather than widening it: the auditor and the
    page both key on `public` / `admin`, so a third word would go
    unread by both."""
    by_persona = {w["persona"]: w for w in payload["walkthroughs"]}
    entry = by_persona["coverage-you-can-audit"]
    assert entry["availability"] == "available"
    assert entry["access"] == ACCESS_ADMIN, (
        "the fixture declared access `auth-gated` on this entry; a payload "
        "that reports `public` is telling an outside reader something untrue"
    )


def test_every_produced_walkthrough_reaches_the_page(payload):
    """The invariant the three shapes exist to serve. Whatever Phase 7
    wrote, the page carries one entry for it — the entry then declares
    its own state. Nothing is filtered on the way out."""
    assert len(payload["walkthroughs"]) == 4
    assert {w["availability"] for w in payload["walkthroughs"]} == {
        "available", "withheld", "unavailable",
    }


def test_the_deep_qa_gate_is_carried_and_is_not_the_score(payload):
    """The one thing this section must never do.

    ``spark-facilitator/20260828-0703`` Stage A scores **8.03** against a
    **7.0** threshold and its gate is **``iterate``**, because ``--deep``
    is "overall >= 7 AND every Fail resolved" and two prompts fabricated
    safety-adjacent operational procedure — an invented cash-handover
    pathway and an invented PersonalID recovery chain. A page that
    printed 8.03 beside a green tick would tell a partner this
    opportunity is ready to launch.

    So the gate and the Fail count are carried as their own fields and
    are NEVER derivable from the score. This asserts the combination
    directly: a score above threshold, a non-approve gate, and a non-zero
    Fail count, all present at once. If a future edit made the page
    compute a verdict from the number, this fixture is the counterexample
    it would have to survive.
    """
    by_stage = {s["stage"]: s for s in payload["deep_qa"]["stages"]}
    ocs = by_stage["assistant"]
    assert ocs["score"] > ocs["threshold"], "the fixture must score ABOVE the bar"
    assert ocs["gate"] == "iterate", "and must still not be approved"
    assert ocs["counts"]["fail"] == 2, "because of the Fails, which must be counted"
    assert [i["ref"] for i in ocs["items"] if i["verdict"] == "fail"] == [
        "opp-50", "opp-56",
    ], "and named, not just counted"


def test_a_deep_qa_stage_that_did_not_run_keeps_the_same_shape():
    """Half a deep gate is a real state, and it must SAY so.

    ``/ace:qa-deep`` takes ``--ocs-only`` / ``--apps-only``, so a run can
    carry one verdict and not the other. The stage that did not run keeps
    every key and nulls the values rather than being dropped — a reader
    must be told "the app journeys have not been deep-QA'd", not left to
    notice that a list is one entry shorter than they expected.
    """
    tree = _maximal_tree()
    del tree["ACE"][OPP_SLUG]["runs"][RUN_ID]["6-qa-and-training"]
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    payload = build_summary_payload(
        drive, workspace=ws, opp_slug=OPP_SLUG, run_id=RUN_ID,
    )
    stages = payload["deep_qa"]["stages"]
    assert [s["stage"] for s in stages] == ["assistant", "apps"]
    assert [s["ran"] for s in stages] == [True, False]
    # Identical key sets, so the frozen contract above holds for both.
    assert set(stages[0]) == set(stages[1])
    assert stages[1]["gate"] is None and stages[1]["score"] is None
    assert stages[1]["counts"] == {"total": 0, "pass": 0, "warn": 0, "fail": 0}


def test_the_whole_deep_qa_section_is_absent_when_the_gate_never_ran():
    """The visibility rule, at the contract level.

    There is no flag and nothing to keep in sync: ``/ace:qa-deep`` writes
    no pointer into ``run_state.yaml``, so the two verdict FILES are the
    only record that it ran. No files, no section — not an empty shell
    that a reader would have to interpret.
    """
    tree = _maximal_tree()
    run = tree["ACE"][OPP_SLUG]["runs"][RUN_ID]
    del run["5-ocs"]
    del run["6-qa-and-training"]
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    payload = build_summary_payload(
        drive, workspace=ws, opp_slug=OPP_SLUG, run_id=RUN_ID,
    )
    assert payload["deep_qa"] is None
    # …and the rest of the page is unaffected.
    assert payload["apps"] and payload["decisions"]


def test_reaction_and_edit_rows_keep_their_wire_names(payload):
    """`reactions.by_decision` and `decision_edits` are keyed by decision
    id, so their VALUE shape is the contract, not their key names."""
    for rows in payload["reactions"]["by_decision"].values():
        for row in rows:
            assert set(row) == {
                "reviewer", "comment", "received_at", "feedback_ref",
            }
    for edit in payload["decision_edits"].values():
        assert set(edit) == {
            "override", "reasoning", "decided_by_name", "decided_by_verified",
            "decided_at", "source_run_id", "is_revert", "history",
        }


# ─── (c) Every link-bearing object declares `access` ────────────────


def test_every_link_bearing_object_declares_its_access(anon_payload):
    """Walk the payload generically: any dict carrying ``url`` or a
    ``*_url`` key must also carry an ``access`` tag drawn from this
    module's ``ACCESS_*`` constants.

    Access is a property of the PAYLOAD, not a hostname table in the
    component — the URLs change every run, the access model of the system
    behind them does not. An untagged link reads to an outsider as
    broken rather than deliberate, which is indistinguishable from the
    run not existing (``docs/learnings/public-summary-link-access.md``).

    ``walkthroughs[]`` is the one exemption, and it is not a loophole:
    it uses ``availability`` because it has a third state (produced but
    withheld) that a two-valued access tag cannot express. See
    ``test_a_withheld_walkthrough_still_declares_why``.

    **The vocabulary gained ``unknown`` in ace-web#740**, and this is the
    same commit that changed both consumers. A Drive link's tag is now
    MEASURED from the file's ACL rather than asserted, and when the ACL
    cannot be read the honest answer is neither ``public`` (the bug being
    fixed: the audited run served two anonymously-401 documents tagged
    ``public``) nor ``admin`` (a wall that may not exist). The ACE
    auditor is unaffected by the widening: its ``LINK-ACCESS-MISLABELLED``
    rule fires on "the page says ``public``, an outsider gets a gate", so
    a tag that is not ``public`` cannot trip it.
    """
    checked = 0
    for path, node in _dicts(anon_payload):
        if path == "walkthroughs[]":
            continue
        if not any(key == "url" or key.endswith("_url") for key in node):
            continue
        checked += 1
        assert "access" in node, f"{path} carries a link but declares no access"
        assert node["access"] in (ACCESS_PUBLIC, ACCESS_ADMIN, ACCESS_UNKNOWN), (
            f"{path} declares access={node['access']!r}, "
            f"which is none of ACCESS_PUBLIC / ACCESS_ADMIN / ACCESS_UNKNOWN"
        )
    # Belt and braces: a walker that silently matched nothing would make
    # this test pass on an empty payload.
    assert checked >= 8, f"only {checked} link-bearing objects found — walker broken?"


# ─── (d) No undeclared secret-shaped value on an anonymous payload ──

#: Key names that look like a credential. A NEW one on this payload must
#: fail CI and force an explicit decision, not slip out with a deploy.
_SECRET_SHAPED = re.compile(r"key|token|secret|password|credential|api_key", re.I)

#: Maps whose KEYS are data (decision ids), not schema. Their key names
#: are not part of the contract, so they are not scanned — their values
#: still are.
_DATA_KEYED_MAPS = frozenset({"decision_edits", "reactions.by_decision"})

#: Secret-shaped values we have decided, in review, to publish anyway.
ACCEPTED_PUBLIC_SECRETS = frozenset({
    # `assistant.embed_key` — the OCS widget is a BROWSER component: it
    # authenticates the anonymous visitor's chat session with
    # `chatbot-id` + `embed-key` read from the page itself, so any key
    # that reaches the widget is by construction readable by anyone who
    # can load the page. There is no server-side variant to proxy it
    # behind, and dropping it deletes the "Need help?" assistant — the
    # one interactive thing an external reviewer can use.
    #
    # It is a per-chatbot PUBLIC IDENTIFIER, not an OCS account
    # credential: it cannot read other chatbots, other teams, or existing
    # transcripts. The exposure is bounded to "someone can talk to this
    # bot", under whatever rate limiting OCS applies.
    #
    # Reviewed 2026-08-14 (ace-web#706) and left in place as an accepted,
    # documented exposure rather than silently removed. The real fix is
    # upstream and OCS-side: a session-scoped token minted server-side,
    # or an ace-web proxy that starts the session and hands the widget a
    # short-lived token. Full rationale lives in `_read_assistant`'s
    # docstring and `docs/learnings/public-summary-embed-key.md`.
    "assistant.embed_key",
})


def test_no_undeclared_secret_shaped_value_reaches_an_anonymous_reader(anon_payload):
    """Equality, not containment, in BOTH directions.

    A new secret-shaped key fails, which is the point. But so does a
    STALE entry in ``ACCEPTED_PUBLIC_SECRETS``: an accepted exposure that
    has since been removed should stop being carried as accepted, or the
    list rots into a rubber stamp nobody re-reads.
    """
    found = set()
    for path, node in _dicts(anon_payload):
        if path in _DATA_KEYED_MAPS:
            continue
        for key in node:
            if _SECRET_SHAPED.search(key):
                found.add(f"{path}.{key}" if path else key)

    assert found == set(ACCEPTED_PUBLIC_SECRETS), (
        "the set of secret-shaped values on the ANONYMOUS public payload "
        "changed. Do not widen ACCEPTED_PUBLIC_SECRETS to make this pass: "
        "decide, in review, whether the new value may be published to "
        "anyone with the link, and record the reasoning inline above.\n"
        f"  found:    {sorted(found)}\n"
        f"  accepted: {sorted(ACCEPTED_PUBLIC_SECRETS)}"
    )


# ─── (e) Confidentiality vs usability are DIFFERENT rules ───────────


def test_a_non_member_payload_never_carries_an_admin_feedback_ledger(anon_payload):
    """Two rules that look alike and are not. Both must hold at once.

    **Usability** — every gated link is SHOWN to everyone and tagged
    ``admin``, never hidden. Hiding a link an external reviewer can't use
    is the same failure as letting it 404, just quieter: an outsider
    shown nothing cannot tell a gated link from a run that does not
    exist. So admin-tagged links elsewhere on a non-member payload are
    EXPECTED, and their absence would itself be a regression.

    **Confidentiality** — a privately captured review's ledger is
    REMOVED, not tagged. ``read_reactions`` in this same payload already
    refuses to republish a private review; linking the ledger RENDERED
    FROM it walks straight around that. The title alone
    ("2026-07-27 · Sophie Feintuch") discloses that a named person
    reviewed this run, and the doc behind it is one anyone-with-link
    grant from disclosing everything they said.

    So the invariant is generic and one-sided: NOTHING under ``feedback``
    is admin-tagged for a non-member, while admin tags elsewhere are
    required. The specific behaviour — which ledger survives, and why —
    is covered by
    ``test_summary.py::test_private_feedback_ledger_is_not_served_to_a_non_member``
    and is not repeated here.
    """
    admin_paths = {
        path for path, node in _dicts(anon_payload)
        if node.get("access") == ACCESS_ADMIN
    }

    # Confidentiality: nothing under `feedback`, at any depth.
    assert not [p for p in admin_paths if p.split("[")[0].split(".")[0] == "feedback"]
    assert anon_payload["feedback"], (
        "the fixture must serve at least one ledger to a non-member, or "
        "this test passes vacuously"
    )
    # Since ace-web#740 the `access` tag no longer restates the
    # confidentiality gate — the gate is `is_public` (derived from the
    # review's channel) and still decides what a non-member SEES; the
    # tag answers only "can this door be opened", measured per file. The
    # surviving ledger's doc IS anyone-with-link shared in the fixture,
    # so it reads `public`; a fixture that shared nothing would read
    # `unknown`, which is equally not a leak.
    assert {f["access"] for f in anon_payload["feedback"]} <= {
        ACCESS_PUBLIC, ACCESS_UNKNOWN,
    }

    # Usability: gated links elsewhere are served, and tagged.
    assert admin_paths >= {
        "apps[]",
        "connect.opportunity",
        "assistant",
        "dashboards[]",
        "solicitation",
        "open_questions",
        "workbench",
    }


# ─── (f) `workbench.url` is RELATIVE, so it must carry the mount ────


def test_workbench_url_is_relative_and_therefore_must_carry_the_mount(settings):
    """The footer's "See the full build process" link is emitted as a
    plain relative ``href``, so it resolves against the ORIGIN unless it
    carries the deployment mount. On labs the app is served under
    ``/ace``: ``/w/<ws>/...`` 404s and ``/ace/w/<ws>/...`` is 200. Every
    reader who clicked it got a 404, on every run.

    It went unnoticed because the link checker collected URLs with
    ``if v.startswith("http")`` — so every RELATIVE value in the payload
    was invisible to it. That is the invariant worth freezing, and it is
    the half the mount tests in ``test_summary.py`` do not state: this
    URL is relative BY DESIGN (it must inherit the origin), which is
    exactly why the prefix is not optional.

    Variant behaviour (no mount, trailing slash, no workspace slug) is
    covered by ``test_summary.py::test_workbench_url_*``; only the
    relative-therefore-prefixed implication is asserted here.
    """
    settings.FORCE_SCRIPT_NAME = "/ace"
    url = _build()["workbench"]["url"]
    assert not url.startswith("http"), (
        "workbench.url is relative by design — a link checker that filters "
        "on startswith('http') must not be able to skip it silently"
    )
    assert url.startswith(settings.FORCE_SCRIPT_NAME), (
        f"{url!r} is relative and does not carry the deployment mount, so it "
        "resolves against the origin and 404s for every anonymous reader"
    )
