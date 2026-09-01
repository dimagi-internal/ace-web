"""Tests for the public per-run summary payload builder.

Drives the loader through fixtures that put structured
`phases.<phase>.products.*` blocks into `run_state.yaml` — the
shape the plugin's state-consolidation sweep landed in v0.13.155 →
v0.13.172. No markdown bodies are parsed; the loader walks the
state dict.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
import yaml

from apps.opps import summary as summary_mod
from apps.opps.summary import build_summary_payload
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


@dataclass
class _FakeWorkspace:
    drive_root_folder_id: str
    slug: str = "test-team"


# ─── Fixture builders ───────────────────────────────────────────────


_OPP_YAML = """\
display_name: turmeric
slug: turmeric
connect:
  program:
    id: cc8ff997-46ac-4c79-a7dd-9563b3babbba
    url: https://connect.dimagi.com/a/ai-demo-space/program/cc8ff997-46ac-4c79-a7dd-9563b3babbba/
    labs_int_id: 7
"""


def _state_yaml(**overrides) -> str:
    """Build a run_state.yaml string carrying full products.* blocks.

    Each kwarg replaces an entire phase's `products` dict. Unset
    phases drop out so we can test partial-data scenarios.
    """
    phases = {
        "design": {
            "pdd": {
                "title": "Turmeric Market Survey",
                "description": (
                    "FLWs visit markets to photograph turmeric vendors, "
                    "capturing a yellow MTN card in each photo as a visual reference."
                ),
                "file_id": "fake-pdd",
            },
        },
        "commcare-setup": {
            "apps": {
                "learn": {
                    "name": "Turmeric Market Survey — FLW Training",
                    "nova_app_id": "mFknxMlsoLlkR28R2qpE",
                    "nova_url": "https://commcare.app/build/mFknxMlsoLlkR28R2qpE",
                    "hq_app_id": "d29dbb77012e400f9a700a731319ea55",
                    "hq_url": "https://www.commcarehq.org/a/connect-ace-prod/apps/view/d29dbb77012e400f9a700a731319ea55/",
                    "build_status": "success",
                },
                "deliver": {
                    "name": "Turmeric Market Survey — Vendor Visit",
                    "nova_app_id": "5VI1WKCEOF5ugIenbu0i",
                    "nova_url": "https://commcare.app/build/5VI1WKCEOF5ugIenbu0i",
                    "hq_app_id": "91cf053ed8f149afb06284a65150debf",
                    "hq_url": "https://www.commcarehq.org/a/connect-ace-prod/apps/view/91cf053ed8f149afb06284a65150debf/",
                    "build_status": "success",
                },
            },
        },
        "connect-setup": {
            "connect": {
                "program": {
                    "id": "cc8ff997-46ac-4c79-a7dd-9563b3babbba",
                    "name": "Turmeric Market Survey — Program",
                    "url": "https://connect.dimagi.com/a/ai-demo-space/program/cc8ff997-46ac-4c79-a7dd-9563b3babbba/",
                },
                "opportunity": {
                    "id": "8c46d744-eee4-48ff-9efb-9a8ab1520dc3",
                    "name": "Turmeric Market Survey — turmeric (2026-05-03)",
                    "url": "https://connect.dimagi.com/a/ai-demo-space/opportunity/8c46d744-eee4-48ff-9efb-9a8ab1520dc3/",
                    "start_date": "2026-06-14",
                    "end_date": "2099-08-09",
                },
            },
        },
        "ocs-setup": {
            "ocs_chatbot": {
                "experiment_id": "12027",
                "public_id": "1fcddd08-02cb-4b22-b482-181cb2f10dcb",
                "embed_key": "wDwe70vquTLm4M0carkTHGaQgrb0NYKP",
                "team_slug": "connect-ace",
                "admin_url": "https://www.openchatstudio.com/a/connect-ace/chatbots/12027/",
            },
        },
        "qa-and-training": {
            "training": {
                "deck": {
                    "file_id": "fake-deck",
                    "title": "Turmeric Market Survey — Training Deck",
                    "web_view_link": "https://docs.google.com/presentation/d/fake-deck/edit",
                },
                "docs": {
                    "llo_guide": {"file_id": "fake-llo", "title": "LLO manager guide",
                                   "web_view_link": "https://docs.google.com/document/d/fake-llo/edit"},
                    "flw_guide": {"file_id": "fake-flw", "title": "FLW training guide",
                                   "web_view_link": "https://docs.google.com/document/d/fake-flw/edit"},
                    "quick_reference": {"file_id": "fake-qr", "title": "Quick reference card",
                                         "web_view_link": "https://docs.google.com/document/d/fake-qr/edit"},
                    "faq": {"file_id": "fake-faq", "title": "FAQ",
                             "web_view_link": "https://docs.google.com/document/d/fake-faq/edit"},
                    "onboarding_email": {"file_id": "fake-onb", "title": "Onboarding email",
                                          "web_view_link": "https://docs.google.com/document/d/fake-onb/edit"},
                },
            },
        },
    }
    phases.update(overrides)
    import yaml as _yaml
    return _yaml.dump({"phases": {p: {"products": v} for p, v in phases.items()}})


# Shape ACE actually writes (verified against
# spark-facilitator/20260813-2126): one bullet per question, a bolded
# title, then "Owner:" and "Answered in:" clauses.
_OPEN_QUESTIONS_MD = """\
# Open Questions — turmeric / 20260503-0835

Seeded from the approved PDD's § Open Questions (Phase 1).

- **Rate confirmation** — the USD 2-5 per-visit band is ACE-inferred; no source \
documents current vendor compensation. Owner: responding LLO + partner. Answered \
in: solicitation response rate proposal (Phase 8).
- **Device reality** — whether every FLW carries a capable Android device is \
undocumented. Owner: responding LLO. Answered in: the LLO's solicitation response.
"""

_DECISIONS_YAML = """\
schema_version: 4
opportunity: turmeric
run_id: 20260503-0835
generated_at: 2026-05-03T08:35:00.000Z
decisions:
  - id: archetype-selection
    phase: 1-design
    skill: idea-to-pdd
    question: Which delivery archetype fits the pilot?
    ai-default: atomic-visit
    options:
      - atomic-visit
      - focus-group
    reasoning: One structured delivery per market visit.
    source: PDD § Evidence Model
    status: ai-default
    evidence_basis: inferred
  - id: solicitation-expected-period
    phase: 8-solicitation-management
    skill: solicitation-create
    question: Which dates should the solicitation advertise?
    ai-default: Work order period of performance
    options:
      - Work order period of performance
      - Phase 4 Connect opportunity dates
    reasoning: The Connect opp is an is_test artifact dated the run day.
    source: pdd-to-work-order § Period of Performance
    status: ai-default
    evidence_basis: conflicting
    conflict_signals:
      - "work order § Period of Performance: 2026-09-15 to 2027-03-31"
      - "run_state connect opportunity: start_date 2026-08-14, is_test true"
  - id: payment-rate
    phase: 4-connect
    skill: connect-opp-setup
    question: What is the per-visit rate?
    ai-default: USD 3.00
    override: USD 4.00
    options:
      - USD 3.00
      - USD 4.00
    reasoning: Midpoint of the inferred band.
    override_reasoning: Partner confirmed the going rate is 4.
    source: Research brief § 7
    status: overridden
    evidence_basis: stated
"""


def _full_tree(*, state_yaml: str | None = None) -> dict:
    if state_yaml is None:
        state_yaml = _state_yaml()
    return {
        "ACE": {
            "turmeric": {
                "opp.yaml": _OPP_YAML,
                # open-questions.md is PER-OPP and durable across runs, so it
                # lives here and not under runs/<id>/. The fixture used to put
                # it in the run folder, which matched the (wrong) reader and so
                # hid the bug that made every real opp render "Open questions —
                # Not created".
                "open-questions.md": _OPEN_QUESTIONS_MD,
                "feedback": {
                    "20260727-sophie-feintuch-ledger": "# Feedback ledger\n",
                },
                "runs": {
                    "20260503-0835": {
                        "run_state.yaml": state_yaml,
                        "decisions.yaml": _DECISIONS_YAML,
                    },
                },
            },
        },
    }


# ─── Top-level shape ───────────────────────────────────────────────


def test_complete_run_returns_full_payload():
    drive = FakeDriveClient.from_tree(_full_tree())
    # A "complete run" now includes complete ACL knowledge: since
    # ace-web#740 every Drive link's tag is measured, so a fixture that
    # declares nothing renders `unknown` — correctly. The unshared
    # open-questions doc is the one this fixture cares about.
    drive.set_link_shared(drive.file_id("ACE/turmeric/open-questions.md"), False)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))

    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p is not None

    # Hero
    assert p["opp"]["display_name"] == "Turmeric Market Survey"
    assert "FLWs visit markets" in p["opp"]["description"]
    assert p["opp"]["status"] == "active"
    assert p["opp"]["end_date"] == "2099-08-09"

    # Apps
    learn = next(a for a in p["apps"] if a["kind"] == "Learn")
    deliver = next(a for a in p["apps"] if a["kind"] == "Deliver")
    assert learn["name"] == "Turmeric Market Survey — FLW Training"
    # nova_url is intentionally not surfaced on the public payload.
    assert "nova_url" not in learn
    assert "d29dbb77" in learn["hq_url"]
    assert deliver["name"] == "Turmeric Market Survey — Vendor Visit"
    assert "91cf053e" in deliver["hq_url"]

    # Connect — only the opportunity is surfaced (program URL 404s publicly).
    assert p["connect"]["opportunity"]["name"].startswith("Turmeric Market Survey")
    assert "/opportunity/8c46d744" in p["connect"]["opportunity"]["url"]
    assert p["connect"]["opportunity"]["start_date"] == "2026-06-14"
    assert "program" not in p["connect"]

    # Training
    assert p["training"]["deck"]["title"] == "Turmeric Market Survey — Training Deck"
    titles = [d["title"] for d in p["training"]["docs"]]
    assert titles == [
        "LLO manager guide", "FLW training guide", "Quick reference card",
        "FAQ", "Onboarding email",
    ]

    # Assistant
    assert p["assistant"]["public_id"] == "1fcddd08-02cb-4b22-b482-181cb2f10dcb"
    assert p["assistant"]["embed_key"] == "wDwe70vquTLm4M0carkTHGaQgrb0NYKP"
    assert p["assistant"]["ocs_url"] == "https://www.openchatstudio.com/a/connect-ace/chatbots/12027/"

    # Open questions (still a Drive fetch — no typed handoff yet). Read from
    # the OPP folder, which is where ACE actually keeps it — and rendered as
    # CONTENT, because the doc itself is unshared.
    assert p["open_questions"]["url"].startswith("https://fake/")
    assert p["open_questions"]["access"] == "admin"
    assert [q["title"] for q in p["open_questions"]["items"]] == [
        "Rate confirmation", "Device reality",
    ]

    # Feedback ledgers — the "where did my comment go?" derived views, so a
    # returning reviewer sees the diff against their own last comments.
    assert [d["title"] for d in p["feedback"]] == ["2026-07-27 · Sophie Feintuch"]

    # Design — the PDD is what a reviewer comments on; it had no section at
    # all before. URL is synthesised from file_id when the block carries no
    # web_view_link, which is the common shape in real run_state.
    assert [d["title"] for d in p["design"]["docs"]] == ["Turmeric Market Survey"]
    assert p["design"]["docs"][0]["url"] == (
        "https://docs.google.com/document/d/fake-pdd/edit"
    )

    # Workbench — always present, always tagged. Hiding it from an
    # outsider reads exactly like the run not existing.
    assert p["workbench"] == {
        "url": "/w/test-team/opps/turmeric/runs/20260503-0835",
        "access": "admin",
    }


def test_empty_state_omits_every_section():
    """run_state.yaml with no products.* blocks yields a payload with
    every section nullable / empty — no 500s."""
    tree = _full_tree(state_yaml="phases: {}\n")
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p is not None
    assert p["apps"] == []
    # No opportunity → connect section is None (program is no longer surfaced,
    # so the opp.yaml program fallback no longer keeps the block alive).
    assert p["connect"] is None
    assert p["training"] is None
    assert p["assistant"] is None
    assert p["walkthroughs"] == []
    assert p["dashboards"] == []
    assert p["opp"]["status"] == "in_progress"  # no end_date, no cycle_grade


def test_missing_run_state_yaml_returns_none():
    """A run folder with no run_state.yaml is not a run — no payload.

    This REVERSES the earlier "200 with defaults from opp.yaml"
    behaviour (ace-web#734). A stalled fork left exactly this shape in
    Drive — artifact folders, no state file — and serving it a 200 made
    "the fork failed" and "the run has not started" indistinguishable
    from the API. The endpoint maps ``None`` to 404.

    Note this is about a specific ``run_id``, not about an opp with an
    empty ``runs/`` folder — pre-run is still a valid Workbench state
    (PR #390) and that path is untouched.
    """
    tree = {
        "ACE": {
            "turmeric": {
                "opp.yaml": _OPP_YAML,
                "runs": {"r1": {}},
            },
        },
    }
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    assert build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="r1",
    ) is None


def test_missing_opp_returns_none():
    drive = FakeDriveClient.from_tree({"ACE": {"other": {"runs": {"r1": {}}}}})
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    assert build_summary_payload(
        drive, workspace=ws, opp_slug="not-here", run_id="r1",
    ) is None


def test_missing_run_returns_none():
    drive = FakeDriveClient.from_tree({"ACE": {"opp": {"runs": {"r1": {}}}}})
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    assert build_summary_payload(
        drive, workspace=ws, opp_slug="opp", run_id="never-existed",
    ) is None


def test_no_runs_folder_returns_none():
    drive = FakeDriveClient.from_tree({"ACE": {"flat": {"opp.yaml": "x"}}})
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    assert build_summary_payload(
        drive, workspace=ws, opp_slug="flat", run_id="any",
    ) is None


# ─── Status derivation ─────────────────────────────────────────────


def test_status_closed_when_cycle_grade_letter_present():
    drive = FakeDriveClient.from_tree(_full_tree(state_yaml=_state_yaml(
        closeout={"cycle_grade": {"letter": "A-", "headline": "Hit launch on time"}},
    )))
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["opp"]["status"] == "closed"
    assert p["cycle_grade"]["letter"] == "A-"
    assert p["cycle_grade"]["headline"] == "Hit launch on time"


def test_status_in_progress_when_end_date_past():
    # Override the connect block with a past end_date.
    state = _state_yaml(**{
        "connect-setup": {
            "connect": {
                "opportunity": {
                    "id": "x",
                    "url": "https://example/opportunity/x/",
                    "end_date": "2020-01-01",
                },
            },
        },
    })
    drive = FakeDriveClient.from_tree(_full_tree(state_yaml=state))
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["opp"]["status"] == "in_progress"


# ─── Hero name fallbacks ───────────────────────────────────────────


def test_hero_name_falls_back_to_yaml_display_when_pdd_missing():
    state = _state_yaml(design={})   # no products.pdd
    tree = _full_tree(state_yaml=state)
    tree["ACE"]["turmeric"]["opp.yaml"] = "display_name: My Friendly Name\n"
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["opp"]["display_name"] == "My Friendly Name"


def test_hero_name_falls_back_to_slug_when_nothing_set():
    state = _state_yaml(design={})
    tree = _full_tree(state_yaml=state)
    tree["ACE"]["turmeric"]["opp.yaml"] = "slug: turmeric\n"   # no display_name
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["opp"]["display_name"] == "turmeric"


# ─── New post-Phase-5 sections ─────────────────────────────────────


def test_walkthroughs_render_from_synthetic_block():
    state = _state_yaml(**{
        "synthetic-data-and-workflows": {
            "synthetic": {
                "walkthroughs": [
                    {"persona": "llo-weekly-review", "slideshow_url": "https://drive.google.com/file/d/w1/view", "eval_score": 8.4},
                    {"persona": "program-admin-audit", "slideshow_url": "https://drive.google.com/file/d/w2/view"},
                    {"persona": "no-url-yet"},  # surfaced as unavailable
                ],
            },
        },
    })
    drive = FakeDriveClient.from_tree(_full_tree(state_yaml=state))
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    personas = [w["persona"] for w in p["walkthroughs"]]
    # The URL-less entry is kept and labelled, not filtered — a produced
    # walkthrough must never read as one that was never made (ace#1432).
    assert personas == ["llo-weekly-review", "program-admin-audit", "no-url-yet"]
    assert p["walkthroughs"][0]["eval_score"] == 8.4
    assert p["walkthroughs"][2]["availability"] == "unavailable"


def test_dashboards_render_from_synthetic_block():
    state = _state_yaml(**{
        "synthetic-data-and-workflows": {
            "synthetic": {
                "dashboards": [
                    {"title": "Household poverty score distribution",
                     "url": "https://labs.connect.dimagi.com/dashboards/d1"},
                    {"title": "FLW field verification",
                     "url": "https://labs.connect.dimagi.com/dashboards/d2"},
                    {"title": "No url yet"},          # filtered out
                    {"url": "https://labs.connect.dimagi.com/dashboards/d3"},  # title defaults
                    "not-a-dict",                       # filtered out
                ],
            },
        },
    })
    drive = FakeDriveClient.from_tree(_full_tree(state_yaml=state))
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["dashboards"] == [
        {"title": "Household poverty score distribution",
         "url": "https://labs.connect.dimagi.com/dashboards/d1",
         "access": "admin"},
        {"title": "FLW field verification",
         "url": "https://labs.connect.dimagi.com/dashboards/d2",
         "access": "admin"},
        {"title": "Dashboard",
         "url": "https://labs.connect.dimagi.com/dashboards/d3",
         "access": "admin"},
    ]


def test_dashboards_empty_when_absent():
    drive = FakeDriveClient.from_tree(_full_tree())
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["dashboards"] == []


def test_selected_llo_renders_from_solicitation_block():
    state = _state_yaml(**{
        "solicitation-management": {
            "selected_llo": {
                "org_slug": "acme-health",
                "org_display_name": "Acme Health Workers",
                "contact_email": "ops@acme.health",
                "awarded_at": "2026-06-01T12:00:00Z",
            },
        },
    })
    drive = FakeDriveClient.from_tree(_full_tree(state_yaml=state))
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["selected_llo"]["org_slug"] == "acme-health"
    assert p["selected_llo"]["org_display_name"] == "Acme Health Workers"
    assert p["selected_llo"]["awarded_at"] == "2026-06-01T12:00:00Z"


def test_launch_renders_from_execution_block():
    state = _state_yaml(**{
        "execution-management": {
            "launch": {
                "went_live_at": "2026-06-20T09:00:00Z",
                "llo_org_display_name": "Acme Health Workers",
            },
        },
    })
    drive = FakeDriveClient.from_tree(_full_tree(state_yaml=state))
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["launch"]["went_live_at"] == "2026-06-20T09:00:00Z"


def test_opp_eval_and_learnings_render_from_closeout_block():
    state = _state_yaml(closeout={
        "opp_eval": {
            "mode": "deep",
            "overall_score": 82,
            "verdict": "pass",
        },
        "learnings": {
            "summary_file_id": "fake-learnings",
            "summary_web_view_link": "https://docs.google.com/document/d/fake-learnings/edit",
            "iteration_warranted": True,
            "new_pdd_file_id": "fake-new-pdd",
            "new_pdd_web_view_link": "https://docs.google.com/document/d/fake-new-pdd/edit",
        },
    })
    drive = FakeDriveClient.from_tree(_full_tree(state_yaml=state))
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["opp_eval"]["overall_score"] == 82
    assert p["opp_eval"]["verdict"] == "pass"
    assert p["learnings"]["iteration_warranted"] is True
    assert p["learnings"]["summary_url"] == "https://docs.google.com/document/d/fake-learnings/edit"
    assert p["learnings"]["new_pdd_url"] == "https://docs.google.com/document/d/fake-new-pdd/edit"


def test_learnings_falls_back_to_constructed_url_when_web_view_link_absent():
    """Pre-0.13.174 runs only have file_ids — loader constructs a Drive
    blob-preview URL as a fallback so the link still works."""
    state = _state_yaml(closeout={
        "learnings": {
            "summary_file_id": "fake-learnings",
            "iteration_warranted": False,
        },
    })
    drive = FakeDriveClient.from_tree(_full_tree(state_yaml=state))
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["learnings"]["summary_url"] == "https://drive.google.com/file/d/fake-learnings/view"
    assert p["learnings"]["new_pdd_url"] is None


def test_solicitation_renders_when_url_present():
    state = _state_yaml(**{
        "solicitation-management": {
            "solicitation": {
                "url": "https://connect.dimagi.com/a/foo/solicitations/abc/",
                "deadline": "2026-06-15",
                "status": "open",
            },
        },
    })
    drive = FakeDriveClient.from_tree(_full_tree(state_yaml=state))
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["solicitation"]["url"].endswith("/solicitations/abc/")
    assert p["solicitation"]["status"] == "open"


# ─── Defensive fallbacks for legacy / drifted products shapes (ace#705) ──


def test_connect_renders_from_flat_products_shape():
    """A run that wrote the opportunity/program flat at products.* instead of
    nested under products.connect (the malaria-rdt/20260604-1604 drift) still
    renders the Connect section, and the flat products.domain still builds the
    HQ app URL."""
    flat_connect = {
        "domain": "connect-ace-prod",
        "organization_slug": "ai-demo-space",
        "program": {
            "id": "cc8ff997-46ac-4c79-a7dd-9563b3babbba",
            "name": "Turmeric Market Survey — Program",
            "url": "https://connect.dimagi.com/a/ai-demo-space/program/cc8ff997-46ac-4c79-a7dd-9563b3babbba/",
        },
        "opportunity": {
            "id": "8c46d744-eee4-48ff-9efb-9a8ab1520dc3",
            "name": "Turmeric Market Survey — turmeric (run X)",
            "url": "https://connect.dimagi.com/a/ai-demo-space/opportunity/8c46d744-eee4-48ff-9efb-9a8ab1520dc3/",
            "start_date": "2026-06-14",
            "end_date": "2099-08-09",
        },
    }
    # apps with hq_app_id but NO hq_url and NO per-app domain — must build the
    # HQ url from the flat products.domain via the _connect_domain fallback.
    apps_no_hq_url = {
        "apps": {
            "learn": {"name": "Learn app", "hq_app_id": "d29dbb77012e400f9a700a731319ea55"},
        },
    }
    drive = FakeDriveClient.from_tree(
        _full_tree(state_yaml=_state_yaml(**{"connect-setup": flat_connect, "commcare-setup": apps_no_hq_url}))
    )
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835")

    assert p["connect"]["opportunity"] is not None
    assert "/opportunity/8c46d744" in p["connect"]["opportunity"]["url"]
    assert "program" not in p["connect"]
    learn = next(a for a in p["apps"] if a["kind"] == "Learn")
    assert learn["hq_url"] == (
        "https://www.commcarehq.org/a/connect-ace-prod/apps/view/d29dbb77012e400f9a700a731319ea55/"
    )


def test_training_renders_from_training_materials_fallback():
    """A run that wrote the deck + onboarding email under
    products.training_materials instead of products.training (ace#705) still
    renders the training section."""
    materials = {
        "training_materials": {
            "deck": {"file_id": "fake-deck", "title": "Training deck",
                      "web_view_link": "https://docs.google.com/presentation/d/fake-deck/edit"},
            "onboarding_email": {"file_id": "fake-onb", "title": "Onboarding email",
                                  "web_view_link": "https://docs.google.com/document/d/fake-onb/edit"},
        },
    }
    drive = FakeDriveClient.from_tree(
        _full_tree(state_yaml=_state_yaml(**{"qa-and-training": materials}))
    )
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835")

    assert p["training"] is not None
    assert p["training"]["deck"]["url"] == "https://docs.google.com/presentation/d/fake-deck/edit"
    titles = [d["title"] for d in p["training"]["docs"]]
    assert "Onboarding email" in titles


# ─── Open questions: per-opp location (regression) ──────────────────


def test_open_questions_read_from_opp_folder_not_run_folder():
    """`open-questions.md` is per-opp and durable across runs.

    The reader used to look only in the run folder, so every real opp
    rendered "Open questions — Not created" while the doc sat one level
    up. The old fixture put the file in the run folder too, which is why
    the bug survived. Regression: opp-level only, no run-level copy.
    """
    drive = FakeDriveClient.from_tree({
        "ACE": {
            "turmeric": {
                "opp.yaml": _OPP_YAML,
                "open-questions.md": "# Open questions\n",
                "runs": {"20260503-0835": {"run_state.yaml": _state_yaml()}},
            },
        },
    })
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835"
    )
    assert p["open_questions"] is not None
    assert p["open_questions"]["url"].startswith("https://fake/")


def test_open_questions_falls_back_to_run_folder_for_legacy_runs():
    """An older run that wrote a run-local copy keeps rendering."""
    drive = FakeDriveClient.from_tree({
        "ACE": {
            "turmeric": {
                "opp.yaml": _OPP_YAML,
                "runs": {
                    "20260503-0835": {
                        "run_state.yaml": _state_yaml(),
                        "open-questions.md": "# Open questions\n",
                    },
                },
            },
        },
    })
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835"
    )
    assert p["open_questions"] is not None


def test_open_questions_absent_everywhere_is_none():
    drive = FakeDriveClient.from_tree({
        "ACE": {
            "turmeric": {
                "opp.yaml": _OPP_YAML,
                "runs": {"20260503-0835": {"run_state.yaml": _state_yaml()}},
            },
        },
    })
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835"
    )
    assert p["open_questions"] is None
    assert p["feedback"] == []


# ─── Dashboards: every shape Phase 7 actually writes ───────────────


_REAL_SYNTHETIC_BLOCK = {
    # Verbatim shape from spark-facilitator/20260813-2126 (trimmed): the
    # dashboards live under `synthetic.source.dashboards` keyed `key` +
    # `par_url`, NOT `synthetic.dashboards` keyed `title` + `url`.
    "synthetic": {
        "labs_opp_id": 10043,
        "source": {
            "dashboards": [
                {
                    "key": "llo_weekly",
                    "role": "review",
                    "workflow_id": 5117,
                    "par_url": "https://labs.connect.dimagi.com/labs/workflow/5117/run/?run_id=5123&opportunity_id=10043",
                },
                {
                    "key": "verification_integrity",
                    "role": "payment_integrity",
                    "workflow_id": 5125,
                    "par_url": "https://labs.connect.dimagi.com/labs/workflow/5125/run/?run_id=5127&opportunity_id=10043",
                },
            ],
        },
        "workflows": {
            "llo_weekly": {
                "workflow_id": 5117,
                "run_url": "https://labs.connect.dimagi.com/labs/workflow/5117/run/?run_id=5123&opportunity_id=10043",
            },
            "verification_integrity": {
                "workflow_id": 5125,
                "run_url": "https://labs.connect.dimagi.com/labs/workflow/5125/run/?run_id=5127&opportunity_id=10043",
            },
        },
        "walkthroughs": [
            {
                "eval_score": 2,
                "eval_verdict": "fail",
                "eval_rubric": "ddd-concept-eval v0.2.153",
            },
        ],
    },
}


def _payload_with_synthetic(products: dict, *, phase_meta: dict | None = None):
    """Build a payload whose synthetic phase carries `products` (and
    optionally phase-level keys like status / verdict)."""
    import yaml as _yaml

    state = _yaml.safe_load(_state_yaml())
    block = {"products": products}
    block.update(phase_meta or {})
    state["phases"]["synthetic-data-and-workflows"] = block
    drive = FakeDriveClient.from_tree(_full_tree(state_yaml=_yaml.dump(state)))
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    return build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )


def test_dashboards_read_par_url_from_source_block():
    """The page said "Dashboards — Not created" while two live labs
    dashboards existed, because the reader required `url` and Phase 7
    writes `par_url` one level down under `source`."""
    p = _payload_with_synthetic(_REAL_SYNTHETIC_BLOCK)
    assert p["dashboards"] == [
        {
            "title": "LLO weekly",
            "url": "https://labs.connect.dimagi.com/labs/workflow/5117/run/?run_id=5123&opportunity_id=10043",
            "access": "admin",
        },
        {
            "title": "Verification integrity",
            "url": "https://labs.connect.dimagi.com/labs/workflow/5125/run/?run_id=5127&opportunity_id=10043",
            "access": "admin",
        },
    ]


def test_dashboards_dedupe_across_the_three_locations():
    """`source.dashboards` and `workflows` describe the same dashboards.
    Reading both must not double them."""
    products = {
        "synthetic": {
            "dashboards": [
                {"title": "Weekly review", "url": "https://labs/one"},
            ],
            "source": {
                "dashboards": [
                    {"key": "weekly_review", "par_url": "https://labs/one"},
                    {"key": "integrity", "par_url": "https://labs/two"},
                ],
            },
            "workflows": {"integrity": {"run_url": "https://labs/two"}},
        },
    }
    p = _payload_with_synthetic(products)
    assert [d["url"] for d in p["dashboards"]] == ["https://labs/one", "https://labs/two"]
    # First-seen wins, so an explicit title beats a humanised key.
    assert p["dashboards"][0]["title"] == "Weekly review"


def test_dashboard_entry_without_any_url_is_skipped_not_fatal(caplog):
    p = _payload_with_synthetic({
        "synthetic": {"source": {"dashboards": [{"key": "no_url_yet"}]}},
    })
    assert p["dashboards"] == []
    assert "has no url" in caplog.text


# ─── Walkthroughs: absent / withheld / available ────────────────────


def test_failing_walkthrough_is_withheld_not_absent():
    """The run rendered a walkthrough whose concept eval failed. It must
    say so — "Not created" would tell a reviewer it doesn't exist."""
    p = _payload_with_synthetic(_REAL_SYNTHETIC_BLOCK, phase_meta={"verdict": "fail"})
    assert len(p["walkthroughs"]) == 1
    w = p["walkthroughs"][0]
    assert w["availability"] == "withheld"
    assert w["url"] is None
    assert w["withheld_reason"] == "Not shown — did not pass quality review"


def test_walkthrough_withheld_by_phase_verdict_when_entry_has_none():
    p = _payload_with_synthetic(
        {"synthetic": {"walkthroughs": [{"persona": "llo-weekly-review"}]}},
        phase_meta={"verdict": "fail"},
    )
    assert p["walkthroughs"][0]["availability"] == "withheld"
    assert p["walkthroughs"][0]["persona"] == "llo-weekly-review"


def test_passing_walkthrough_stays_available_and_linked():
    p = _payload_with_synthetic(
        {
            "synthetic": {
                "walkthroughs": [{
                    "persona": "llo-weekly-review",
                    "slideshow_url": "https://drive.google.com/file/d/w1/view",
                    "eval_score": 8.4,
                    "eval_verdict": "pass",
                }],
            },
        },
        phase_meta={"verdict": "pass"},
    )
    w = p["walkthroughs"][0]
    assert w["availability"] == "available"
    assert w["url"] == "https://drive.google.com/file/d/w1/view"
    assert w["eval_score"] == 8.4


def test_url_less_walkthrough_is_surfaced_not_dropped(caplog):
    """A produced walkthrough with no recognised URL must appear on the
    page as ``unavailable``. Dropping it renders identically to a run
    that never made one — the reader would be lying by omission about
    work that exists. The log line is a debugging aid, not the report:
    "loudly" has to mean visible to the reviewer (ace#1432)."""
    p = _payload_with_synthetic(
        {"synthetic": {"walkthroughs": [{"persona": "no-url-yet"}]}},
        phase_meta={"verdict": "pass"},
    )
    assert len(p["walkthroughs"]) == 1
    w = p["walkthroughs"][0]
    assert w["availability"] == "unavailable"
    assert w["url"] is None
    assert w["persona"] == "no-url-yet"
    assert w["withheld_reason"]
    # The log must name both sides so the fix is one line.
    assert "no recognised url key" in caplog.text
    assert "accepted=" in caplog.text


def test_warn_verdict_walkthrough_is_shown_not_withheld():
    """``warn`` is deliberately not a failing verdict. The concept gate
    scores the MINIMUM of 60 independently-drawn cells, so a clean pass
    is not reachable for an artifact with any soft dimension — treating
    warn as failing would withhold permanently rather than temporarily.
    Measured on spark-facilitator/20260813-2126: every accuracy defect
    fixed, all 60 cells at 3 or 4, overall still warn."""
    p = _payload_with_synthetic(
        {
            "synthetic": {
                "walkthroughs": [{
                    "persona": "verified-meetings",
                    "video_url": "https://drive.google.com/file/d/w9/view",
                    "eval_score": 3,
                    "eval_verdict": "warn",
                }],
            },
        },
        phase_meta={"verdict": "warn"},
    )
    w = p["walkthroughs"][0]
    assert w["availability"] == "available"
    assert w["url"] == "https://drive.google.com/file/d/w9/view"


@pytest.mark.parametrize("key", [
    "slideshow_url", "web_view_link", "url",
    "video_url", "video_web_view_link", "video_link",
])
def test_every_documented_url_key_links(key):
    """Phase 7 picks whichever name reads well beside its siblings, and
    an unrecognised one used to erase the entry. spark-facilitator wrote
    ``video_web_view_link``; the page served ``walkthroughs: []`` while
    the video sat published in Drive (ace#1432). Each accepted key is
    pinned so widening the list cannot silently narrow again."""
    p = _payload_with_synthetic(
        {
            "synthetic": {
                "walkthroughs": [{
                    "persona": "k",
                    key: "https://drive.google.com/file/d/kk/view",
                    "eval_verdict": "pass",
                }],
            },
        },
        phase_meta={"verdict": "pass"},
    )
    w = p["walkthroughs"][0]
    assert w["availability"] == "available", f"{key} did not link"
    assert w["url"] == "https://drive.google.com/file/d/kk/view"


def test_no_produced_walkthrough_is_ever_dropped():
    """The invariant behind all of the above: whatever Phase 7 wrote,
    the payload has one entry for it. Every entry then declares its own
    state. Nothing vanishes."""
    entries = [
        {"persona": "a", "url": "https://x/1", "eval_verdict": "pass"},
        {"persona": "b", "eval_verdict": "fail"},
        {"persona": "c"},
        {"persona": "d", "video_web_view_link": "https://x/4"},
    ]
    p = _payload_with_synthetic(
        {"synthetic": {"walkthroughs": entries}}, phase_meta={"verdict": "pass"},
    )
    assert len(p["walkthroughs"]) == len(entries)
    assert [w["persona"] for w in p["walkthroughs"]] == ["a", "b", "c", "d"]
    assert {w["availability"] for w in p["walkthroughs"]} == {
        "available", "withheld", "unavailable",
    }


# ─── Walkthroughs: what the RUN declares about its own entry ────────
#
# ace-web#726. `_read_walkthroughs` used to stamp every entry
# `access: public` / `availability: available` / `withheld_reason: null`,
# discarding whatever the run had written. Measured on
# hh-poverty-targeting/20260824-1404: the run wrote `unavailable` /
# `auth-gated` / a paragraph of reason and the anonymous payload
# returned `available` / `public` / null for all three, so a canopy-web
# DDD package behind Dimagi OAuth was advertised to outside readers as
# public. There was no data-side workaround: leaving the entry in
# tripped the ACE auditor's LINK-ACCESS-MISLABELLED, removing it tripped
# WALKTHROUGH-DROPPED.


_CANOPY_DDD_CONSOLE_URL = (
    "https://labs.connect.dimagi.com/canopy/ddd/"
    "hh-poverty-targeting-coverage-integrity/"
    "hh-poverty-targeting-coverage-integrity-2026-08-26-001"
)


def test_a_run_can_say_a_walkthrough_was_produced_but_not_shared():
    """The hh-poverty-targeting/20260824-1404 repro, end to end. The DDD
    loop ended `stopped_not_converged` and its `external_release` gate
    resolved HOLD, so "produced, deliberately not shared" is the true
    state — and the page must be able to say exactly that: named, with
    the run's own reason, and with no link an outsider cannot open."""
    reason = (
        "The DDD loop ended stopped_not_converged and its external_release "
        "gate resolved HOLD, so this package was never externally released."
    )
    p = _payload_with_synthetic(
        {
            "synthetic": {
                "walkthroughs": [{
                    "persona": "Coverage you can audit",
                    "web_view_link": _CANOPY_DDD_CONSOLE_URL,
                    "eval_score": 2,
                    "availability": "unavailable",
                    "access": "auth-gated",
                    "withheld_reason": reason,
                }],
            },
        },
        phase_meta={"verdict": "warn"},
    )
    assert len(p["walkthroughs"]) == 1
    w = p["walkthroughs"][0]
    assert w["availability"] == "unavailable"
    assert w["withheld_reason"] == reason
    assert w["url"] is None
    assert "access" not in w, "an entry with no link must claim no access"
    assert w["persona"] == "Coverage you can audit"


def test_an_author_supplied_access_tag_is_honoured_not_overwritten():
    """The narrower half of #726: the run is willing to show the link,
    it just needs the page to say the link is gated. `auth-gated` is
    normalised into the payload's two-valued vocabulary rather than
    widening it — the frozen contract and the ACE auditor both key on
    exactly `public` / `admin`."""
    p = _payload_with_synthetic(
        {
            "synthetic": {
                "walkthroughs": [{
                    "persona": "Coverage you can audit",
                    "web_view_link": _CANOPY_DDD_CONSOLE_URL,
                    "access": "auth-gated",
                    "eval_verdict": "pass",
                }],
            },
        },
        phase_meta={"verdict": "pass"},
    )
    w = p["walkthroughs"][0]
    assert w["availability"] == "available"
    assert w["url"] == _CANOPY_DDD_CONSOLE_URL
    assert w["access"] == "admin"


def test_a_run_supplied_reason_replaces_the_canned_withheld_text():
    p = _payload_with_synthetic(
        {
            "synthetic": {
                "walkthroughs": [{
                    "persona": "llo-weekly-review",
                    "slideshow_url": "https://drive.google.com/file/d/w1/view",
                    "eval_verdict": "fail",
                    "withheld_reason": "Scene 4 mislabels the payment trigger.",
                }],
            },
        },
    )
    w = p["walkthroughs"][0]
    assert w["availability"] == "withheld"
    assert w["withheld_reason"] == "Scene 4 mislabels the payment trigger."


def test_a_run_can_withhold_a_walkthrough_its_verdict_would_have_shown():
    """Declaring `withheld` needs no failing verdict behind it — a run
    may have any number of reasons not to show something it made."""
    p = _payload_with_synthetic(
        {
            "synthetic": {
                "walkthroughs": [{
                    "persona": "llo-weekly-review",
                    "slideshow_url": "https://drive.google.com/file/d/w1/view",
                    "eval_verdict": "pass",
                    "availability": "withheld",
                }],
            },
        },
        phase_meta={"verdict": "pass"},
    )
    w = p["walkthroughs"][0]
    assert w["availability"] == "withheld"
    assert w["url"] is None


def test_a_declared_availability_can_only_hide_never_reveal():
    """The one asymmetry, and it is deliberate. A failing eval verdict
    guards against putting a bad demo in front of a stakeholder;
    `availability: available` in the run state must not lift that guard.
    Author metadata may make an entry LESS visible, never more."""
    p = _payload_with_synthetic(
        {
            "synthetic": {
                "walkthroughs": [{
                    "persona": "llo-weekly-review",
                    "slideshow_url": "https://drive.google.com/file/d/w1/view",
                    "eval_verdict": "fail",
                    "availability": "available",
                }],
            },
        },
    )
    w = p["walkthroughs"][0]
    assert w["availability"] == "withheld"
    assert w["url"] is None


def test_an_unrecognised_availability_word_is_ignored_loudly(caplog):
    """Falling back to the derived state is right — but silently
    accepting a word nobody reads would hide the typo forever."""
    p = _payload_with_synthetic(
        {
            "synthetic": {
                "walkthroughs": [{
                    "persona": "llo-weekly-review",
                    "slideshow_url": "https://drive.google.com/file/d/w1/view",
                    "availability": "not-shared",
                    "eval_verdict": "pass",
                }],
            },
        },
        phase_meta={"verdict": "pass"},
    )
    assert p["walkthroughs"][0]["availability"] == "available"
    assert "not-shared" in caplog.text


def test_an_unrecognised_access_word_falls_back_to_derivation_loudly(caplog):
    p = _payload_with_synthetic(
        {
            "synthetic": {
                "walkthroughs": [{
                    "persona": "llo-weekly-review",
                    "web_view_link": _CANOPY_DDD_CONSOLE_URL,
                    "access": "sort-of-public",
                    "eval_verdict": "pass",
                }],
            },
        },
        phase_meta={"verdict": "pass"},
    )
    assert p["walkthroughs"][0]["access"] == "admin"
    assert "sort-of-public" in caplog.text


# ─── Walkthroughs: the derived access tag when the run says nothing ──


@pytest.mark.parametrize(("url", "expected"), [
    # canopy-web's auth middleware is default-deny with a short allowlist
    # of share-token-gated SPA shells (canopy-web
    # apps/common/middleware.py, pinned by its
    # tests/test_public_routes_reachable.py). The DDD OPERATOR console is
    # explicitly not on it —
    # `test_the_ddd_console_is_gated_even_though_ddd_release_is_public`.
    (_CANOPY_DDD_CONSOLE_URL, "admin"),
    ("https://labs.connect.dimagi.com/canopy/insights", "admin"),
    ("https://labs.connect.dimagi.com/canopy/w/dimagi/ddd/x", "admin"),
    ("https://labs.connect.dimagi.com/canopy/ddd-release/x/x-2026-08-26-001", "public"),
    ("https://labs.connect.dimagi.com/canopy/share/abc123", "public"),
    ("https://labs.connect.dimagi.com/canopy/walkthrough/abc123", "public"),
    ("https://labs.connect.dimagi.com/canopy/narrative/verified-monitoring", "public"),
    # Not canopy: a Drive file, a token-minted share — these circulate by
    # design, and guessing `admin` would tell a reader they cannot open
    # something they can. Same class of lie, other direction.
    ("https://drive.google.com/file/d/w1/view", "public"),
    ("https://example.org/some/deck", "public"),
])
def test_access_is_derived_from_the_link_when_the_run_does_not_tag_it(url, expected):
    p = _payload_with_synthetic(
        {
            "synthetic": {
                "walkthroughs": [{"persona": "p", "url": url, "eval_verdict": "pass"}],
            },
        },
        phase_meta={"verdict": "pass"},
    )
    assert p["walkthroughs"][0]["access"] == expected


# ─── Walkthroughs: the DDD loop's own honesty record (ace-web#740) ───
#
# The bug: the reader took `eval_score` and dropped every field that
# says whether the number means anything. On
# spark-facilitator/20260820-0817 the page rendered a score and a video
# link while the run state recorded `stopped_not_converged`, zero
# end-to-end iterations, and — the one that matters most — that the
# render measures a PRE-FIX artifact: four accuracy fixes landed during
# the iteration and appear in no captured frame, so the published video
# films a product that no longer exists.
#
# The load-bearing test is again the NEGATIVE one: a non-converged run
# must not render as a bare score.


def _walkthrough_with(**synthetic_extra):
    return _payload_with_synthetic(
        {
            "synthetic": {
                "walkthroughs": [{
                    "persona": "p",
                    "url": "https://drive.google.com/file/d/w1/view",
                    "eval_score": 2,
                    "eval_verdict": "pass",
                }],
                **synthetic_extra,
            },
        },
        phase_meta={"verdict": "pass"},
    )["walkthroughs"][0]


def test_a_score_never_travels_without_its_terminal_status():
    """THE regression test. The audited run, reproduced: a score of 2 and
    a loop that stopped without converging. The payload must carry the
    status, or the page has no way to show anything but the number."""
    w = _walkthrough_with(
        ddd_terminal_status="stopped_not_converged",
        ddd_iterations_completed_end_to_end=0,
    )
    assert w["eval_score"] == 2
    assert w["ddd"]["terminal_status"] == "stopped_not_converged"
    assert w["ddd"]["iterations_completed"] == 0


def test_a_pre_fix_render_is_flagged_as_a_hard_caveat():
    """`render_measures_pre_fix_artifact` is the field that makes the
    linked VIDEO misleading, not just the score. It must reach the page
    as its own boolean rather than being folded into prose."""
    w = _walkthrough_with(
        ddd_terminal_status="stopped_not_converged",
        ddd_render_measures_pre_fix_artifact=True,
    )
    assert w["ddd"]["measures_pre_fix_artifact"] is True


def test_the_honesty_note_reaches_the_page_verbatim():
    note = (
        "READ THIS BEFORE QUOTING THE 2.0. One iteration rendered and\n"
        "  was fully judged; NO SECOND RENDER HAPPENED."
    )
    w = _walkthrough_with(ddd_honesty_note=note)
    assert w["ddd"]["note"].startswith("READ THIS BEFORE QUOTING THE 2.0.")
    assert "NO SECOND RENDER HAPPENED" in w["ddd"]["note"]


@pytest.mark.parametrize("status", [
    "converged_clean",
    "converged_with_open_questions",
    "stopped_not_converged",
    "diverging",
])
def test_all_four_terminal_statuses_survive_distinctly(status):
    """No pass/fail collapse. "Converged, good" and "converged, still
    failing" must not render identically — the difference is the whole
    point of the field, and a boolean would erase it."""
    assert _walkthrough_with(ddd_terminal_status=status)["ddd"][
        "terminal_status"
    ] == status


def test_an_unrecognised_terminal_status_is_surfaced_not_dropped(caplog):
    """Same rule as the walkthrough URL keys (ace#1432): a value we do
    not recognise must not silently become absence."""
    w = _walkthrough_with(ddd_terminal_status="stalled_on_a_gate")
    assert w["ddd"]["terminal_status"] == "stalled_on_a_gate"
    assert "ddd_terminal_status" in caplog.text


def test_a_run_that_recorded_no_ddd_state_claims_nothing():
    """A run predating these fields renders exactly as before. Absence
    must not be dressed up as reassurance — an unrecorded caveat is not
    a cleared one, so `terminal_status` is null rather than
    "converged"."""
    w = _walkthrough_with()
    assert w["ddd"] == {
        "terminal_status": None,
        "iterations_completed": None,
        "measures_pre_fix_artifact": False,
        "note": None,
    }


def test_an_entry_level_status_overrides_the_phase_level_one():
    """The plugin writes these as siblings of `walkthroughs` today, but a
    run with two narratives needs per-entry values. Entry wins."""
    p = _payload_with_synthetic(
        {
            "synthetic": {
                "walkthroughs": [{
                    "persona": "p",
                    "url": "https://drive.google.com/file/d/w1/view",
                    "eval_verdict": "pass",
                    "ddd_terminal_status": "converged_clean",
                }],
                "ddd_terminal_status": "stopped_not_converged",
            },
        },
        phase_meta={"verdict": "pass"},
    )
    assert p["walkthroughs"][0]["ddd"]["terminal_status"] == "converged_clean"


def test_a_withheld_walkthrough_still_carries_the_loop_state():
    """A reader looking at a withheld entry still needs to know the loop
    never converged — the qualifiers are not attached to the score."""
    p = _payload_with_synthetic(
        {
            "synthetic": {
                "walkthroughs": [{"persona": "p"}],
                "ddd_terminal_status": "stopped_not_converged",
            },
        },
        phase_meta={"verdict": "fail"},
    )
    w = p["walkthroughs"][0]
    assert w["availability"] == "withheld"
    assert w["ddd"]["terminal_status"] == "stopped_not_converged"


# ─── The assistant claims only what the run recorded (ace-web#740) ───


def test_assistant_knowledge_sources_are_empty_when_the_run_recorded_none():
    """The page used to state "Trained on the design doc, training pack,
    and app guides for this opportunity" as a constant. On the audited
    run the opp collection held 16 files and NONE of the five
    training-pack documents the same page links were among them. With
    nothing recorded, the payload must claim nothing."""
    drive = FakeDriveClient.from_tree(_full_tree())
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["assistant"]["knowledge_sources"] == []


def test_assistant_knowledge_sources_carry_what_the_run_did_record():
    """ACE shipped `ocs-knowledge-refresh` (ace#1715), so later runs DO
    index the training docs. The claim has to become true for those runs
    and stay false for the earlier ones, which a constant cannot do."""
    state = _state_yaml(**{
        "ocs-setup": {
            "ocs_chatbot": {
                "public_id": "1fcddd08-02cb-4b22-b482-181cb2f10dcb",
                "embed_key": "wDwe70vquTLm4M0carkTHGaQgrb0NYKP",
                "admin_url": "https://www.openchatstudio.com/a/connect-ace/chatbots/12027/",
                "knowledge_sources": [
                    "the design doc", "the app guides", "the training pack",
                ],
            },
        },
    })
    drive = FakeDriveClient.from_tree(_full_tree(state_yaml=state))
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["assistant"]["knowledge_sources"] == [
        "the design doc", "the app guides", "the training pack",
    ]


# ─── Lifecycle stage ───────────────────────────────────────────────


def _state_with_phase_meta(meta: dict) -> str:
    import yaml as _yaml

    state = _yaml.safe_load(_state_yaml())
    for phase, block in meta.items():
        state["phases"].setdefault(phase, {}).update(block)
    return _yaml.dump(state)


def test_stage_marks_unreached_sections_as_pending_not_missing():
    """A run halted at the Phase 8→9 boundary has no LLO / launch /
    score / learnings BY DESIGN. Six of ten sections reading "Not
    created" made a healthy paused run look abandoned."""
    state = _state_with_phase_meta({
        "solicitation-management": {"status": "complete",
                                    "products": {"solicitation": {"url": "https://labs/s/1"}}},
        "execution-management": {"status": "pending", "products": {}},
        "closeout": {"status": "pending", "products": {}},
    })
    drive = FakeDriveClient.from_tree(_full_tree(state_yaml=state))
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["stage"]["label"] == "solicitation"
    assert p["stage"]["pending_sections"] == [
        "cycle_grade", "launch", "learnings", "opp_eval", "selected_llo",
    ]


def test_stage_treats_a_phase_with_products_as_started_even_without_status():
    """Older runs (and every fixture here) write products with no phase
    status. Calling those "not started" would be worse than the bug."""
    drive = FakeDriveClient.from_tree(_full_tree())
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert "training" not in p["stage"]["pending_sections"]
    assert "apps" not in p["stage"]["pending_sections"]


def test_stage_is_none_when_run_state_has_no_phases():
    tree = _full_tree(state_yaml="phases: {}\n")
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["stage"] is None


# ─── Internal links ────────────────────────────────────────────────


def test_workbench_link_is_served_to_everyone_and_declares_its_access():
    """The Workbench 404s for anyone who isn't a signed-in member, and
    ace-web rejects non-@dimagi.com sign-ins. #707 responded by HIDING
    the link from non-members; Jonathan's ruling (2026-08-14) is to show
    it with an `admin only` tag instead — "nothing is Dimagi only at
    scale for ACE, even if right now it needs to be." Membership now
    changes only ``viewer.is_member``, which is what the page keys the
    tag off.
    """
    drive = FakeDriveClient.from_tree(_full_tree())
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    kwargs = dict(workspace=ws, opp_slug="turmeric", run_id="20260503-0835")
    expected = {
        "url": "/w/test-team/opps/turmeric/runs/20260503-0835",
        "access": "admin",
    }
    member = build_summary_payload(drive, **kwargs)
    public = build_summary_payload(drive, viewer_is_member=False, **kwargs)
    assert member["workbench"] == expected
    assert public["workbench"] == expected
    assert member["viewer"] == {"is_member": True}
    assert public["viewer"] == {"is_member": False}


def test_every_gated_link_declares_admin_access():
    """The gating is a property of the PAYLOAD, not a hostname table in
    the component — the URLs change every run, the access model of the
    system behind them doesn't. These five were verified anonymously on
    spark-facilitator/20260813-2126."""
    state = _state_yaml(**{
        "synthetic-data-and-workflows": {
            "synthetic": {"dashboards": [{"title": "D", "url": "https://labs/d"}]},
        },
        "solicitation-management": {
            "solicitation": {"url": "https://labs/solicitations/1/"},
        },
    })
    drive = FakeDriveClient.from_tree(_full_tree(state_yaml=state))
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert {a["access"] for a in p["apps"]} == {"admin"}       # CommCare HQ
    assert p["connect"]["opportunity"]["access"] == "admin"    # Connect
    assert p["assistant"]["access"] == "admin"                 # OCS console
    assert p["dashboards"][0]["access"] == "admin"             # connect-labs
    assert p["solicitation"]["access"] == "admin"              # connect-labs
    assert p["workbench"]["access"] == "admin"                 # ace-web


# ─── Drive link access is MEASURED, not asserted (ace-web#740) ──────
#
# The bug these replace: `_read_design` and `_read_training` stamped
# `access: public` on every Drive deliverable unconditionally. On
# spark-facilitator/20260820-0817 an anonymous audit fetched
# `.../export?format=txt` for the two documents `design.docs` served and
# got **401** on both — while the page rendered them "Open" to a partner
# with no Google account. The page's verdict was NOT SAFE TO SHARE.
#
# The load-bearing test is the NEGATIVE one: an unreachable document must
# not be tagged public. A fixture where everything is shared proves
# nothing — the old hard-coded reader passes it.

def test_an_unreachable_document_is_not_tagged_public():
    """THE regression test for ace-web#740. Both design docs exist, both
    have working-looking URLs, and NEITHER is anyone-with-link shared —
    exactly the audited run. The page must not call them public."""
    drive = FakeDriveClient.from_tree(_full_tree())
    drive.set_link_shared("fake-pdd", False)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert {d["access"] for d in p["design"]["docs"]} == {"admin"}


def test_a_shared_document_is_tagged_public():
    """The other direction, so the reader is not just always-admin: a doc
    carrying an `anyone` permission IS public, and saying otherwise would
    tell a reader they cannot open something they can."""
    drive = FakeDriveClient.from_tree(_full_tree())
    drive.set_link_shared("fake-pdd", True)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert {d["access"] for d in p["design"]["docs"]} == {"public"}


def test_an_unreadable_acl_is_unknown_rather_than_public():
    """When the ACL read FAILS the honest answer is `unknown`. Falling back
    to `public` is the original bug with an extra step; falling back to
    `admin` invents a wall that may not exist."""
    drive = FakeDriveClient.from_tree(_full_tree())
    drive.set_link_unreadable("fake-pdd")
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert {d["access"] for d in p["design"]["docs"]} == {"unknown"}


def test_the_training_pack_is_measured_per_document():
    """Same class, different section — and the audited run is why this is
    per-document rather than per-section: the training pack WAS anonymously
    reachable on the very run whose design docs were not. One blanket tag
    could not have been right for both."""
    drive = FakeDriveClient.from_tree(_full_tree())
    for fid in ("fake-deck", "fake-llo", "fake-flw", "fake-qr", "fake-faq"):
        drive.set_link_shared(fid, True)
    drive.set_link_shared("fake-onb", False)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["training"]["deck"]["access"] == "public"
    by_title = {d["title"]: d["access"] for d in p["training"]["docs"]}
    assert by_title["Onboarding email"] == "admin"
    assert by_title["FAQ"] == "public"


def test_open_questions_access_is_measured_not_hardcoded_admin():
    """It used to be a flat `ACCESS_ADMIN` on the theory that nothing
    shares this doc. On the audited run that happens to be true — and it
    is still a habit rather than a fact about the file."""
    drive = FakeDriveClient.from_tree(_full_tree())
    oq = drive.file_id("ACE/turmeric/open-questions.md")
    drive.set_link_shared(oq, True)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["open_questions"]["access"] == "public"


def test_every_drive_link_is_measured_in_one_batch():
    """Latency guard. ace-web#738 made this endpoint batch its Drive reads;
    measuring N links with N sequential ACL round-trips would give that
    back. The state-derived links must all be resolved in one call."""
    drive = FakeDriveClient.from_tree(_full_tree())
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    first = drive.link_shared_calls[0]
    for fid in ("fake-pdd", "fake-deck", "fake-llo", "fake-onb"):
        assert fid in first, f"{fid} was not in the primed batch"

# Only DRIVE links are measured; the systems above (HQ, Connect, OCS,
# connect-labs, the Workbench) are gated by membership in those systems
# — a property of the SYSTEM, not of the object, with nothing per-object
# to read. `test_every_gated_link_declares_admin_access` above pins that
# half and is unchanged by ace-web#740.


# ─── Review surface: decisions + open questions ────────────────────


def _payload(tree=None):
    drive = FakeDriveClient.from_tree(tree or _full_tree())
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    return build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )


def test_decisions_are_surfaced_as_rows_not_a_link():
    """A 24-page PDD is a bad instrument for eliciting decisions. The
    typed rows are what a partner can react to — and the doc they live in
    is an internal working artifact nobody shares, so a link is useless."""
    d = _payload()["decisions"]
    assert d["total"] == 3
    assert d["counts"] == {
        "stated": 1, "inferred": 1, "conflicting": 1, "overridden": 1,
    }
    assert [r["id"] for r in d["rows"]] == [
        "archetype-selection", "solicitation-expected-period", "payment-rate",
    ]


def test_decision_rows_carry_the_workbench_shape():
    """Rows go through the same ``serialize_decision`` the Workbench uses,
    so one component renders both and they can't drift on field names."""
    row = _payload()["decisions"]["rows"][0]
    assert row["ai_default"] == "atomic-visit"           # from YAML `ai-default`
    assert row["options_considered"] == ["atomic-visit", "focus-group"]
    assert row["notes"] == "One structured delivery per market visit."  # `reasoning`
    assert row["evidence_basis"] == "inferred"
    assert row["source"] == "PDD § Evidence Model"
    assert row["status"] == "ai-default"


def test_decision_rows_carry_a_phase_label_and_ordinal_for_grouping():
    """Phase is the ORGANISING structure of the public review surface, so
    the label has to be the same phase name the Workbench shows — the row
    tag ``3-commcare`` humanises to "Commcare" where the plugin (and the
    Workbench reading it) says "CommCare Setup"."""
    rows = {r["id"]: r for r in _payload()["decisions"]["rows"]}
    # Tag `1-design` → the plugin's own display name for that phase.
    assert rows["archetype-selection"]["phase_label"] == "Design Review"
    assert rows["archetype-selection"]["phase_ordinal"] == 1
    assert rows["solicitation-expected-period"]["phase_label"] == "Solicitation management"
    assert rows["solicitation-expected-period"]["phase_ordinal"] == 8


def test_a_reordered_pipeline_cannot_relabel_an_old_decision():
    """`serialize_decision` projects a row's tag onto a phase name by
    ORDINAL, so a pipeline re-order silently re-points old rows: the stub
    registry's phase 4 is OCS setup, while this run recorded `4-connect`.

    Publishing that row as "OCS Setup" would be a confident, wrong claim
    about where a decision came from, on a page an outside partner reads.
    The registry may only make a label FULLER, never overrule the run.
    """
    rows = {r["id"]: r for r in _payload()["decisions"]["rows"]}
    row = rows["payment-rate"]
    assert row["phase_raw"] == "4-connect"
    assert row["phase"] == "ocs-setup"          # the ordinal projection
    assert row["phase_label"] == "Connect"      # …but the label follows the run
    assert row["phase_ordinal"] == 4


def test_phase_label_falls_back_to_the_tag_without_a_plugin_registry(monkeypatch):
    """No readable plugin (local dev, a broken checkout) is not a reason to
    lose the phase headings — degrade to the tag-derived label."""
    monkeypatch.setattr(summary_mod, "_plugin_phase_index", lambda: {})
    rows = {r["id"]: r for r in _payload()["decisions"]["rows"]}
    assert rows["archetype-selection"]["phase_label"] == "Design"
    assert rows["archetype-selection"]["phase_ordinal"] == 1


def test_conflicting_rows_keep_their_competing_signals():
    """`evidence_basis: conflicting` means ACE resolved a fork the sources
    disagreed on — the competing readings are exactly what a partner is
    best placed to correct, so they must survive to the page."""
    rows = {r["id"]: r for r in _payload()["decisions"]["rows"]}
    row = rows["solicitation-expected-period"]
    assert row["evidence_basis"] == "conflicting"
    assert len(row["conflict_signals"]) == 2
    assert "is_test true" in row["conflict_signals"][1]


def test_overridden_rows_keep_the_human_rationale():
    row = {r["id"]: r for r in _payload()["decisions"]["rows"]}["payment-rate"]
    assert row["status"] == "overridden"
    assert row["override"] == "USD 4.00"
    assert row["override_reasoning"] == "Partner confirmed the going rate is 4."


def test_decisions_absent_when_the_run_has_no_log():
    tree = _full_tree()
    del tree["ACE"]["turmeric"]["runs"]["20260503-0835"]["decisions.yaml"]
    assert _payload(tree)["decisions"] is None


def test_decisions_absent_when_the_log_is_empty_or_malformed():
    for body in ("decisions: []\n", "schema_version: 4\n", "not: a log\n"):
        tree = _full_tree()
        tree["ACE"]["turmeric"]["runs"]["20260503-0835"]["decisions.yaml"] = body
        assert _payload(tree)["decisions"] is None


def test_decision_rows_without_id_or_question_are_dropped_loudly():
    """A row we can't render is skipped with a log line — a silent drop is
    what made dashboards read "Not created" while two live ones existed."""
    tree = _full_tree()
    tree["ACE"]["turmeric"]["runs"]["20260503-0835"]["decisions.yaml"] = (
        "decisions:\n"
        "  - id: fine\n"
        "    phase: 1-design\n"
        "    question: A real question?\n"
        "    ai-default: yes\n"
        "  - phase: 1-design\n"
        "    question: No id\n"
        "  - id: no-question\n"
        "    phase: 1-design\n"
        "  - just-a-string\n"
    )
    d = _payload(tree)["decisions"]
    assert [r["id"] for r in d["rows"]] == ["fine"]


def test_open_questions_parse_owner_and_where_it_gets_answered():
    """An unresolved question with no owner is an unassigned one. The
    convention ACE writes carries both; parsing keeps them separable."""
    items = _payload()["open_questions"]["items"]
    assert items[0] == {
        "title": "Rate confirmation",
        "detail": (
            "the USD 2-5 per-visit band is ACE-inferred; no source documents "
            "current vendor compensation"
        ),
        "owner": "responding LLO + partner",
        "answered_in": "solicitation response rate proposal (Phase 8)",
        # The legacy `Title — detail` convention carries no `blocking:`
        # field. Null, not absent: the key is on every item so the page
        # never has to check whether a row has the shape it expects.
        "blocking": None,
    }


def test_open_questions_unparseable_bullet_still_renders():
    """A question we can't parse is still a question the reviewer should
    see — degrade to prose, never drop."""
    tree = _full_tree()
    tree["ACE"]["turmeric"]["open-questions.md"] = (
        "# Open Questions\n\n- Just a bare sentence with no structure at all\n"
    )
    items = _payload(tree)["open_questions"]["items"]
    assert items == [{
        "title": "",
        "detail": "Just a bare sentence with no structure at all",
        "owner": None,
        "answered_in": None,
        "blocking": None,
    }]


def test_open_questions_survive_an_unreadable_body():
    """Losing the body must not lose the link — the section degrades to
    what #705 shipped rather than vanishing."""
    tree = _full_tree()
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))

    real_get_content = drive.get_content
    oq_id = drive.file_id("ACE/turmeric/open-questions.md")

    def boom(file_id, mime_type):
        if file_id == oq_id:
            raise RuntimeError("drive is down")
        return real_get_content(file_id, mime_type)

    drive.get_content = boom  # type: ignore[method-assign]
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["open_questions"]["items"] == []
    assert p["open_questions"]["url"].startswith("https://fake/")


# ─── Reactions on the payload ──────────────────────────────────────


def test_payload_carries_the_reactions_collected_on_this_run():
    """Reactions ride the same payload as the rows they attach to.

    A separate fetch would mean the page renders 42 decisions and their
    replies at different moments — and the empty state (before the second
    request lands) says "nobody has said anything", which is a lie.
    """
    import yaml as _yaml

    tree = _full_tree()
    tree["ACE"]["turmeric"]["feedback"]["20260814-public-anne-kuhlmann.yaml"] = (
        _yaml.safe_dump({
            "schema_version": 1,
            "slug": "20260814-public-anne-kuhlmann",
            "reviewer": "Anne Kuhlmann",
            "reviewer_email": "anne@example.org",
            "received_at": "2026-08-14",
            "channel": "other",
            "against_run": "20260503-0835",
            "items": [{
                "id": "photo-required",
                "verbatim": "A photo per visit is too much in the rainy season.",
                "anchor": "decision:photo-required · Should each visit require a photo?",
            }],
        })
    )
    p = _payload(tree)
    assert p["reactions"]["total"] == 1
    row = p["reactions"]["by_decision"]["photo-required"][0]
    assert row["reviewer"] == "Anne Kuhlmann"
    assert row["feedback_ref"] == "20260814-public-anne-kuhlmann/photo-required"
    # Emails are collected so we can reply, never published.
    assert "anne@example.org" not in repr(p)


def test_payload_reactions_default_to_empty():
    assert _payload(_full_tree())["reactions"] == {"total": 0, "by_decision": {}}


# ─── workbench_url carries the deployment mount (dimagi-internal/ace#1329) ───
#
# The run-summary footer link — "See the full build process" — 404'd for
# ANYONE who clicked it, on every run. The payload emitted it root-relative:
#
#     "workbench": {"url": "/w/dimagi-team/opps/spark-facilitator/runs/20260813-2126", ...}
#
# The page is served under the `/ace` mount, so a root-relative href resolves
# against the ORIGIN, not the mount:
#
#     https://labs.connect.dimagi.com/w/…      -> 404
#     https://labs.connect.dimagi.com/ace/w/…  -> 200
#
# It went unnoticed because `scripts/check-summary-links.py` collected URLs
# with `if v.startswith("http")`, so every relative value in the payload was
# invisible to it. ace#1328 fixed the checker; this is the serializer half.
#
# Blast radius is one link — but it is the link that says "here is how we
# built this", on the page we hand to external partners, so it is the one a
# partner is most likely to click after reading the summary.


def test_workbench_url_carries_the_force_script_name_mount(settings):
    settings.FORCE_SCRIPT_NAME = "/ace"
    drive = FakeDriveClient.from_tree(_full_tree())
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))

    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["workbench"]["url"] == "/ace/w/test-team/opps/turmeric/runs/20260503-0835"


def test_workbench_url_has_no_prefix_when_served_at_root(settings):
    settings.FORCE_SCRIPT_NAME = None
    drive = FakeDriveClient.from_tree(_full_tree())
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))

    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["workbench"]["url"] == "/w/test-team/opps/turmeric/runs/20260503-0835"


def test_workbench_url_never_doubles_the_slash(settings):
    # FORCE_SCRIPT_NAME is coerced to None when empty precisely because Django
    # generates "//api/health" otherwise; the same trap applies here, and a
    # trailing slash must not survive either.
    for mount in ("/ace/", "/ace"):
        settings.FORCE_SCRIPT_NAME = mount
        drive = FakeDriveClient.from_tree(_full_tree())
        ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
        p = build_summary_payload(
            drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
        )
        assert "//" not in p["workbench"]["url"], mount
        assert p["workbench"]["url"].startswith("/ace/w/"), mount


def test_workbench_url_is_none_without_a_workspace_slug(settings):
    settings.FORCE_SCRIPT_NAME = "/ace"
    drive = FakeDriveClient.from_tree(_full_tree())
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"), slug="")

    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["workbench"] is None


# ─── Confidentiality: a private review's ledger is not a public link ──


def _tree_with_ledgers():
    """Two ledgers side by side: one private review, one public reaction."""
    tree = _full_tree()
    fb = tree["ACE"]["turmeric"]["feedback"]
    fb["20260727-sophie-feintuch.yaml"] = yaml.safe_dump({
        "schema_version": 1,
        "slug": "20260727-sophie-feintuch",
        "reviewer": "Sophie Feintuch",
        "received_at": "2026-07-27",
        "channel": "gdoc-comments",
        "items": [{"id": "d", "verbatim": "This is a private review."}],
    })
    fb["20260814-public-anne-kuhlmann.yaml"] = yaml.safe_dump({
        "schema_version": 1,
        "slug": "20260814-public-anne-kuhlmann",
        "reviewer": "Anne Kuhlmann",
        "received_at": "2026-08-14",
        "channel": "other",
        "items": [{"id": "photo-required", "verbatim": "Left on the public page."}],
    })
    fb["20260814-public-anne-kuhlmann-ledger"] = "# Feedback ledger\n"
    return tree


def test_private_feedback_ledger_is_not_served_to_a_non_member():
    """`read_reactions` refuses to republish a privately-captured review —
    and linking the ledger RENDERED FROM that review would walk straight
    around it. The title alone discloses that a named person reviewed the
    run; the doc behind it is one anyone-with-link grant from disclosing
    everything they said."""
    drive = FakeDriveClient.from_tree(_tree_with_ledgers())
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
        viewer_is_member=False,
    )
    titles = [d["title"] for d in p["feedback"]]
    assert titles == ["2026-08-14 · Public Anne Kuhlmann"]
    assert "Sophie" not in str(p["feedback"])


def test_member_sees_every_ledger_including_the_private_ones():
    """The confidentiality GATE (may a non-member see this ledger at all?)
    is `is_public`, derived from the feedback record's channel. It is not
    the same question as the ledger doc's Drive ACL, and since ace-web#740
    the `access` tag answers only the second one — measured, per file. A
    member sees both ledgers here; the private one is still gated out for
    a non-member, which `test_private_feedback_ledger_is_not_served_to_a_
    non_member` covers."""
    drive = FakeDriveClient.from_tree(_tree_with_ledgers())
    for name in ("20260727-sophie-feintuch-ledger",
                 "20260814-public-anne-kuhlmann-ledger"):
        drive.set_link_shared(drive.file_id(f"ACE/turmeric/feedback/{name}"), False)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
        viewer_is_member=True,
    )
    by_title = {d["title"]: d["access"] for d in p["feedback"]}
    assert set(by_title) == {
        "2026-07-27 · Sophie Feintuch", "2026-08-14 · Public Anne Kuhlmann",
    }
    # Neither doc is anyone-with-link shared, so neither is tagged public —
    # including the one whose REVIEW is public. Before ace-web#740 the
    # public-review ledger was stamped `access: public` on the strength of
    # its channel, which is a claim about the review, not about the door.
    assert set(by_title.values()) == {"admin"}


def test_a_public_review_whose_doc_is_shared_is_tagged_public():
    """The other half of the split: the tag follows the FILE."""
    drive = FakeDriveClient.from_tree(_tree_with_ledgers())
    drive.set_link_shared(
        drive.file_id("ACE/turmeric/feedback/20260814-public-anne-kuhlmann-ledger"),
        True,
    )
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
        viewer_is_member=True,
    )
    by_title = {d["title"]: d["access"] for d in p["feedback"]}
    assert by_title["2026-08-14 · Public Anne Kuhlmann"] == "public"
    # Nothing declared the private ledger's ACL, so it is honestly unknown
    # rather than guessed either way.
    assert by_title["2026-07-27 · Sophie Feintuch"] == "unknown"


def test_a_ledger_with_no_record_at_all_is_private():
    """Default-deny. An orphaned ledger — record deleted, renamed, or never
    written — must not be assumed public because nothing said otherwise."""
    drive = FakeDriveClient.from_tree(_full_tree())  # ledger, no record yaml
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
        viewer_is_member=False,
    )
    assert p["feedback"] == []


def test_public_summary_channel_marks_a_record_public_without_the_slug():
    """The boundary is a FIELD now (dimagi-internal/ace#1362). A record that
    declares `channel: public-summary` is public even if its slug carries no
    `-public-` segment, so the filename convention stops being load-bearing."""
    tree = _full_tree()
    fb = tree["ACE"]["turmeric"]["feedback"]
    fb["20260815-anne-kuhlmann.yaml"] = yaml.safe_dump({
        "schema_version": 1,
        "slug": "20260815-anne-kuhlmann",
        "reviewer": "Anne Kuhlmann",
        "received_at": "2026-08-15",
        "channel": "public-summary",
        "items": [{"id": "a", "verbatim": "Left on the public page."}],
    })
    fb["20260815-anne-kuhlmann-ledger"] = "# Feedback ledger\n"
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
        viewer_is_member=False,
    )
    assert [d["title"] for d in p["feedback"]] == ["2026-08-15 · Anne Kuhlmann"]


def test_read_connect_falls_back_to_opportunity_deep_link():
    """connect-opp-setup writes the live URL as products.connect.opportunity.deep_link
    (not .url). _read_connect must surface it as opportunity.url. Regression: the
    fallback previously read connect.deep_link (wrong nesting level) and the opp
    link rendered blank on the summary page."""
    from apps.opps.summary import _read_connect

    state = {
        "phases": {
            "connect-setup": {
                "products": {
                    "connect": {
                        "opportunity": {
                            "id": "bce9150c",
                            "name": "LEEP Paint Surveillance - India",
                            "deep_link": "https://connect.dimagi.com/a/ai-demo-space/opportunity/bce9150c/",
                        },
                    },
                },
            },
        },
    }
    out = _read_connect(state)
    assert out is not None
    assert out["opportunity"]["url"] == (
        "https://connect.dimagi.com/a/ai-demo-space/opportunity/bce9150c/"
    )


# ─── Open questions: the ## Open / ## Archive split (ace#1867) ──────


#: A structural mirror of a real durable ledger — the two-section shape
#: `skills/idea-to-pdd` writes, with the field-labelled row schema. Row
#: text is trimmed; the SHAPE is what these tests are about.
_TWO_SECTION_LEDGER = """\
# Open Questions — turmeric

Opportunity-level, durable across runs.

## Open

- **id:** rate-confirmation **question:** What does the partner pay vendors \
today? **raised_by:** 20260503-0835 **owner:** partner \
**answered_where:** solicitation responses **blocking:** Before Phase 8 \
**latest:** The single largest unknown. No source addresses it; \
`vendor_rate` is unset and M&E has not weighed in.

- **id:** device-reality **question:** Does every FLW carry a capable \
Android device? **raised_by:** 20260503-0835 **owner:** responding LLO \
**answered_where:** — **blocking:** Go/no-go **latest:** Still unanswered.

## Archive

Questions this opportunity has already ANSWERED. Do not re-ask.

- **id:** payment-anchor-record **question:** Which record anchors a \
payment? **raised_by:** pre-ledger **owner:** partner \
**resolved_at:** 2026-07-24T00:00:00Z **resolved_by:** the partner's M&E \
lead **resolution_note:** The Village Monitoring Form.
"""


def _open_questions(body: str) -> list[dict]:
    from apps.opps.summary import _open_section, _parse_open_questions

    return _parse_open_questions(_open_section(body))


def test_archived_questions_are_not_counted_as_open():
    """The headline number IS `items.length`, so an archived row rendered
    in the open list makes the page's own sentence false.

    `spark-facilitator/20260828-0703`: 21 rows under `## Open`, 7 under
    `## Archive`, headline "28 open questions the run couldn't settle" —
    7 of which carried `resolved_at` and a `resolution_note`.
    """
    items = _open_questions(_TWO_SECTION_LEDGER)

    assert len(items) == 2
    assert [q["title"] for q in items] == [
        "What does the partner pay vendors today?",
        "Does every FLW carry a capable Android device?",
    ]
    blob = " ".join(f"{q['title']} {q['detail']}" for q in items)
    assert "resolved_at" not in blob
    assert "resolution_note" not in blob
    assert "payment-anchor-record" not in blob


def test_the_archive_instruction_never_reaches_the_reader():
    """`## Archive`'s lead line is an instruction addressed to ACE.

    It is not a bullet, so the wrapped-line branch glued it onto the LAST
    open question and an external partner was shown ACE's own directive
    as part of a question's text.
    """
    items = _open_questions(_TWO_SECTION_LEDGER)

    assert all("Do not re-ask" not in q["detail"] for q in items)
    assert all("already ANSWERED" not in q["detail"] for q in items)


def test_field_labelled_rows_get_a_real_title_and_no_scaffolding():
    """27 of 28 rows rendered `title: ""` and a run-on `id: … question: …`
    blob, because the parser stripped `**` before it could tell a label
    from prose (ace-web#743)."""
    first, second = _open_questions(_TWO_SECTION_LEDGER)

    assert first["title"] == "What does the partner pay vendors today?"
    assert first["owner"] == "partner"
    assert first["answered_in"] == "solicitation responses"
    assert first["blocking"] == "Before Phase 8"
    assert first["detail"].startswith("The single largest unknown.")

    # None of the schema key names survive into rendered text.
    for q in (first, second):
        for field in ("title", "detail"):
            for key in ("id:", "question:", "raised_by:", "answered_where:"):
                assert key not in q[field], (field, key, q[field])

    # `answered_where: —` means "no venue yet", not "the venue is —".
    assert second["answered_in"] is None
    assert second["blocking"] == "Go/no-go"


def test_code_spans_and_drive_escapes_do_not_reach_the_page():
    """15 of 28 rows leaked literal backticks and 9 leaked `M\\&E`-style
    markdown escapes to the public page."""
    from apps.opps.drive_export import unescape_markdown

    items = _open_questions(unescape_markdown(_TWO_SECTION_LEDGER.replace(
        "M&E", "M\\&E",
    )))

    rendered = " ".join(f"{q['title']} {q['detail']}" for q in items)
    assert "`" not in rendered
    assert "\\" not in rendered
    assert "vendor_rate is unset and M&E has not weighed in." in rendered


def test_a_ledger_with_no_open_heading_still_renders_every_row():
    """Pre-two-section ledgers have no `## Open`. Every bullet in one is
    open, so the whole body is kept — older runs must not go blank."""
    items = _open_questions(_OPEN_QUESTIONS_MD)

    assert [q["title"] for q in items] == ["Rate confirmation", "Device reality"]
    assert items[0]["owner"] == "responding LLO + partner"


# ─── Build status: a partial phase must not read as a clean one ────


def _build(phase: dict, *, state_extra: dict | None = None):
    from apps.opps.summary import _read_build

    state = {"phases": {"commcare-setup": phase}}
    state.update(state_extra or {})
    return _read_build(state, "commcare-setup")


def test_a_partial_phase_surfaces_its_status_and_failing_gate():
    """`spark-facilitator/20260828-0703` shipped both apps with
    `status: partial` and a FAILED `entity_state_fidelity` gate — the
    payment-key gate — and the COMMCARE APPS section showed no status at
    all, rendering it identically to a clean run (ace-web#744)."""
    out = _build({
        "status": "partial",
        "verdict": "partial-deliver-eval-blocked-on-phase1-gap",
        "status_note": "The phase does not claim pass because the deliver\neval returns fail.",
        "steps": {
            "pdd-to-learn-app": {"status": "done", "verdict": "pass"},
            "pdd-to-deliver-app-eval": {
                "status": "done",
                "verdict": "fail",
                "blocker_open_detail": "entity_state_fidelity - PDD declares no taxonomy row.",
            },
        },
    })

    assert out is not None
    assert out["status"] == "partial"
    assert out["verdict"] == "partial-deliver-eval-blocked-on-phase1-gap"
    # The run's own prose, whitespace-collapsed — never re-worded here.
    assert out["note"] == (
        "The phase does not claim pass because the deliver eval returns fail."
    )
    assert out["failing_checks"] == [{
        "name": "pdd-to-deliver-app-eval",
        "verdict": "fail",
        "detail": "entity_state_fidelity - PDD declares no taxonomy row.",
    }]


def test_a_clean_phase_adds_nothing_to_the_page():
    """A run that finished clean must render exactly as it did before —
    no invented reassurance, no empty caveat block."""
    assert _build({
        "status": "done",
        "verdict": "pass",
        "steps": {"pdd-to-learn-app": {"status": "done", "verdict": "pass"}},
    }) is None
    assert _build({}) is None


def test_a_carried_blocker_is_surfaced_even_when_the_phase_says_done():
    """A blocker the operator explicitly waved through is exactly the case
    where the page most needs to speak up (ace-web#744)."""
    out = _build(
        {"status": "done", "verdict": "pass", "steps": {}},
        state_extra={"blocker_dispositions": {
            "phase3_entity_state_fidelity": {
                "phase": "commcare-setup",
                "gate": "entity_state_fidelity",
                "disposition": "CARRIED FORWARD - run proceeded to Phase 4",
                "residual_accepted": "Learn-taught vocabulary was\nNOT machine-verified.",
            },
            "phase6_other": {"phase": "qa-and-training", "gate": "x"},
        }},
    )

    assert out is not None
    assert [b["gate"] for b in out["carried_blockers"]] == ["entity_state_fidelity"]
    assert out["carried_blockers"][0]["residual_accepted"] == (
        "Learn-taught vocabulary was NOT machine-verified."
    )


# ─── Synthetic provenance: the dashboards are generated data ───────


def _synthetic(products: dict):
    from apps.opps.summary import _read_synthetic

    return _read_synthetic({
        "phases": {"synthetic-data-and-workflows": {"products": products}},
    })


def test_generated_data_is_labelled_from_the_runs_own_counts():
    """The DASHBOARDS section carried no qualifier while the run recorded
    223 generated visit records against 12 invented facilitators
    (`spark-facilitator/20260828-0703`). Every number here is read from
    the run — none of it is hardcoded."""
    out = _synthetic({"synthetic": {"source": {
        "provider": "ace-run",
        "labs_synthetic_opp_id": 10054,
        "record_counts": {"user_visits": 223, "user_data": 12, "completed_works": 0},
        "data_shape": {
            "rows": 12,
            "rows_population": (
                "user_data — the facilitator cohort, the population both "
                "dashboards enumerate one line per"
            ),
        },
    }}})

    assert out == {
        "is_synthetic": True,
        "provider": "ace-run",
        "labs_opp_id": 10054,
        "visits": 223,
        "completed_works": 0,
        "cohort_size": 12,
        # The schema key is machinery; the clause after the dash is English.
        "cohort_population": (
            "the facilitator cohort, the population both dashboards "
            "enumerate one line per"
        ),
    }


def test_a_run_that_generated_nothing_is_not_labelled():
    """No synthetic block means no generated data — labelling it anyway
    would be the same lie pointed the other way."""
    assert _synthetic({}) is None
    assert _synthetic({"synthetic": {}}) is None


def test_the_label_survives_a_run_that_recorded_no_counts():
    """A run with a synthetic block but no counts still says the data is
    generated; it just says it without figures rather than inventing any."""
    out = _synthetic({"synthetic": {"source": {"provider": "ace-run"}}})

    assert out is not None
    assert out["is_synthetic"] is True
    assert out["visits"] is None
    assert out["cohort_size"] is None
    assert out["cohort_population"] is None


# ─── Deep QA (/ace:qa-deep) ─────────────────────────────────────────
#
# The only section on this page whose EXISTENCE is a Drive fact rather
# than a run_state fact — `/ace:qa-deep` deliberately writes no pointer,
# so the verdict files are the signal. Contract-level shape is frozen in
# test_public_surface_contract.py; these are the behaviours.


def _deep_tree(*, ocs: str | None = None, apps: str | None = None) -> dict:
    run: dict = {"run_state.yaml": "phases: {}\n"}
    if ocs is not None:
        run["5-ocs"] = {"ocs-chatbot-eval_verdict-deep.yaml": ocs}
    if apps is not None:
        run["6-qa-and-training"] = {"app-ux-eval_verdict-deep.yaml": apps}
    return {"run": run}


def _read_deep(tree: dict, state: dict | None = None):
    from apps.opps.summary import _read_deep_qa
    drive = FakeDriveClient.from_tree(tree)
    return _read_deep_qa(drive, drive.folder_id("run"), state or {})


_OCS_MIN = """\
skill: ocs-chatbot-eval
ran_at: 2026-09-01T15:05:00Z
published_version: 3
overall_score: 8.03
verdict: warn
dimensions:
  correctness: {score: 7.23, weight: 0.3}
per_item:
  - {ref: opp-1, score: 8.7, verdict: pass, note: Fine.}
  - {ref: opp-50, score: 3.0, verdict: fail, note: Invented a cash pathway.}
gate: {threshold: 7.0, disposition: iterate}
"""


def test_deep_qa_is_absent_when_neither_verdict_exists():
    """No files, no section. There is nothing else to key on."""
    assert _read_deep(_deep_tree()) is None


def test_a_deep_verdict_leads_with_the_gate_not_the_score():
    """8.03 over a 7.0 bar, and the gate is still `iterate`.

    The number and the gate are carried as separate facts because they
    disagree, and the one that decides whether this opportunity may
    launch is the gate.
    """
    stage = _read_deep(_deep_tree(ocs=_OCS_MIN))["stages"][0]
    assert stage["stage"] == "assistant" and stage["ran"] is True
    assert (stage["score"], stage["threshold"]) == (8.03, 7.0)
    assert stage["gate"] == "iterate"
    assert stage["verdict"] == "warn"
    assert stage["counts"] == {"total": 2, "pass": 1, "warn": 0, "fail": 1}


def test_an_unquoted_ran_at_survives_as_a_string():
    """`ran_at: 2026-09-01T15:05:00Z` is a native YAML timestamp, so
    `safe_load` hands back a `datetime`. The real OCS verdict writes it
    bare and the real app verdict quotes its own — treating this as a
    string drops the timestamp on one stage and only one stage, silently.
    When the timestamp is the only staleness signal a reader gets, that
    is the whole bug."""
    stage = _read_deep(_deep_tree(ocs=_OCS_MIN))["stages"][0]
    assert stage["ran_at"] and stage["ran_at"].startswith("2026-09-01T15:05:00")


def test_only_the_non_passing_items_are_carried_and_failures_come_first():
    """A deep OCS suite is ~68 prompts. The rows an external reader needs
    are the ones that did not pass; `counts` is what stops that short
    list reading as the whole suite."""
    verdict = _OCS_MIN.replace(
        "gate: {",
        "  - {ref: opp-29, score: 6.0, verdict: warn, note: Wrong address.}\n"
        "gate: {",
    )
    stage = _read_deep(_deep_tree(ocs=verdict))["stages"][0]
    assert [i["ref"] for i in stage["items"]] == ["opp-50", "opp-29"]
    assert stage["counts"]["pass"] == 1
    assert all(i["verdict"] != "pass" for i in stage["items"])


def test_the_other_stage_says_it_did_not_run_rather_than_disappearing():
    """`/ace:qa-deep --ocs-only` is a supported invocation, so half a
    deep gate is a real state the page has to be able to describe."""
    stages = _read_deep(_deep_tree(ocs=_OCS_MIN))["stages"]
    assert [s["ran"] for s in stages] == [True, False]
    assert set(stages[0]) == set(stages[1])
    assert stages[1]["gate"] is None and stages[1]["items"] == []


def test_a_verdict_measured_against_the_current_chatbot_is_not_stale():
    state = {"phases": {"ocs-setup": {"products": {
        "ocs_chatbot": {"published_version": 3},
    }}}}
    stage = _read_deep(_deep_tree(ocs=_OCS_MIN), state)["stages"][0]
    assert stage["is_stale"] is False
    assert stage["freshness"] == [{
        "basis": "published chatbot version",
        "verdict_value": "3",
        "current_value": "3",
        "is_current": True,
    }]


def test_a_verdict_measured_against_a_superseded_version_is_stale():
    """Phase 9 `llo-launch` refuses activation on a stale deep verdict.
    A verdict about version 3 says nothing about version 4."""
    state = {"phases": {"ocs-setup": {"products": {
        "ocs_chatbot": {"published_version": 4},
    }}}}
    stage = _read_deep(_deep_tree(ocs=_OCS_MIN), state)["stages"][0]
    assert stage["is_stale"] is True
    assert stage["freshness"][0]["current_value"] == "4"


def test_staleness_is_unknown_rather_than_guessed_when_either_side_is_absent():
    """The rule that keeps this honest. A verdict with no identifier, or
    a run_state with no released build, produces NO comparison and
    `is_stale: None` — the page then shows the timestamp and leaves the
    judgement to the reader. A staleness check that can be wrong is worse
    than none, because `fresh` is the claim a reader would act on."""
    # Verdict carries no identifier.
    no_ref = _OCS_MIN.replace("published_version: 3\n", "")
    stage = _read_deep(_deep_tree(ocs=no_ref), {"phases": {"ocs-setup": {
        "products": {"ocs_chatbot": {"published_version": 3}},
    }}})["stages"][0]
    assert stage["freshness"] == [] and stage["is_stale"] is None
    # run_state carries no current value.
    stage = _read_deep(_deep_tree(ocs=_OCS_MIN), {})["stages"][0]
    assert stage["freshness"] == [] and stage["is_stale"] is None


def test_the_apps_stage_compares_the_released_build_it_was_measured_against():
    apps_verdict = """\
skill: app-ux-eval
ran_at: "2026-09-01T16:40:00-04:00"
artifact_refs: {deliver_build_id: b085, learn_build_id: 5b40}
overall_score: 5.7
verdict: fail
dimensions:
  clarity: {score: 8.6, weight: 0.15}
per_item:
  - {ref: journey-deliver-followup-preload, score: 2.8, verdict: fail, note: Case stale.}
gate: {threshold: 7.0, disposition: reject}
"""
    state = {"phases": {"commcare-setup": {"products": {"apps": {
        "deliver": {"released_build_id": "b085"},
        "learn": {"released_build_id": "OLD"},
    }}}}}
    stage = _read_deep(_deep_tree(apps=apps_verdict), state)["stages"][1]
    assert stage["gate"] == "reject"
    assert [(f["basis"], f["is_current"]) for f in stage["freshness"]] == [
        ("deliver build", True), ("learn build", False),
    ]
    # One stale half is enough. `is_stale` is not an average.
    assert stage["is_stale"] is True


def test_an_unrecognised_gate_disposition_is_surfaced_verbatim(caplog):
    """Same rule `_ddd_honesty` applies to a DDD terminal status: a
    disposition this reader has not heard of must show up as itself, not
    vanish into silence."""
    verdict = _OCS_MIN.replace("disposition: iterate", "disposition: quarantine")
    stage = _read_deep(_deep_tree(ocs=verdict))["stages"][0]
    assert stage["gate"] == "quarantine"
    assert "quarantine" in caplog.text
