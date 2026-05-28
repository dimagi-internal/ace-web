"""Tests for the public per-run summary payload builder.

Drives the loader through fixtures that put structured
`phases.<phase>.products.*` blocks into `run_state.yaml` — the
shape the plugin's state-consolidation sweep landed in v0.13.155 →
v0.13.172. No markdown bodies are parsed; the loader walks the
state dict.
"""
from __future__ import annotations

from dataclasses import dataclass

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


def _full_tree(*, state_yaml: str | None = None) -> dict:
    if state_yaml is None:
        state_yaml = _state_yaml()
    return {
        "ACE": {
            "turmeric": {
                "opp.yaml": _OPP_YAML,
                "runs": {
                    "20260503-0835": {
                        "run_state.yaml": state_yaml,
                        "open-questions.md": "# Open questions\n",
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
    assert learn["nova_url"] == "https://commcare.app/build/mFknxMlsoLlkR28R2qpE"
    assert "d29dbb77" in learn["hq_url"]
    assert deliver["name"] == "Turmeric Market Survey — Vendor Visit"
    assert "91cf053e" in deliver["hq_url"]

    # Connect
    assert p["connect"]["opportunity"]["name"].startswith("Turmeric Market Survey")
    assert "/opportunity/8c46d744" in p["connect"]["opportunity"]["url"]
    assert p["connect"]["opportunity"]["start_date"] == "2026-06-14"
    assert p["connect"]["program"]["url"].endswith("cc8ff997-46ac-4c79-a7dd-9563b3babbba/")

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

    # Open questions (still a Drive fetch — no typed handoff yet)
    assert p["open_questions"]["url"].startswith("https://fake/")

    # Workbench
    assert p["workbench_url"] == "/w/test-team/opps/turmeric/runs/20260503-0835"


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
    # Connect program still resolves from opp.yaml fallback.
    assert p["connect"]["program"]["url"].endswith("cc8ff997-46ac-4c79-a7dd-9563b3babbba/")
    assert p["connect"]["opportunity"] is None
    assert p["training"] is None
    assert p["assistant"] is None
    assert p["walkthroughs"] == []
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
                    {"persona": "no-url-yet"},  # filtered out
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
    assert personas == ["llo-weekly-review", "program-admin-audit"]
    assert p["walkthroughs"][0]["eval_score"] == 8.4


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
    out = _read_connect(state, {})
    assert out is not None
    assert out["opportunity"]["url"] == (
        "https://connect.dimagi.com/a/ai-demo-space/opportunity/bce9150c/"
    )
