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


def test_missing_run_state_yaml_returns_payload_with_defaults():
    """A run folder with no run_state.yaml still produces a payload
    (sections come from opp.yaml + defaults)."""
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
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="r1",
    )
    assert p is not None
    assert p["opp"]["display_name"] == "turmeric"   # falls back to opp.yaml
    assert p["apps"] == []
    assert p["training"] is None


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


def test_drive_deliverables_are_not_tagged_admin():
    """Drive ACLs are per-file and `/ace:share-run-access` shares exactly
    these with reviewers — claiming "admin only" here would be a guess in
    the wrong direction."""
    drive = FakeDriveClient.from_tree(_full_tree())
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert {d["access"] for d in p["design"]["docs"]} == {"public"}
    assert p["training"]["deck"]["access"] == "public"
    assert {d["access"] for d in p["training"]["docs"]} == {"public"}
    # NOT the feedback ledgers: a ledger is only "public" when the review it
    # renders was itself left on a public page. The fixture's is a privately
    # captured gdoc review, so it is member-only — see
    # test_private_feedback_ledger_is_not_served_to_a_non_member.
    assert {f["access"] for f in p["feedback"]} == {"admin"}


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


def test_member_sees_every_ledger_with_the_private_ones_tagged():
    drive = FakeDriveClient.from_tree(_tree_with_ledgers())
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
        viewer_is_member=True,
    )
    by_title = {d["title"]: d["access"] for d in p["feedback"]}
    assert by_title["2026-07-27 · Sophie Feintuch"] == "admin"
    assert by_title["2026-08-14 · Public Anne Kuhlmann"] == "public"


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
