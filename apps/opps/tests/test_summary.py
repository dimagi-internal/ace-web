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
                # open-questions.md is PER-OPP and durable across runs, so it
                # lives here and not under runs/<id>/. The fixture used to put
                # it in the run folder, which matched the (wrong) reader and so
                # hid the bug that made every real opp render "Open questions —
                # Not created".
                "open-questions.md": "# Open questions\n",
                "feedback": {
                    "20260727-sophie-feintuch-ledger": "# Feedback ledger\n",
                },
                "runs": {
                    "20260503-0835": {
                        "run_state.yaml": state_yaml,
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
    # the OPP folder, which is where ACE actually keeps it.
    assert p["open_questions"]["url"].startswith("https://fake/")

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
         "url": "https://labs.connect.dimagi.com/dashboards/d1"},
        {"title": "FLW field verification",
         "url": "https://labs.connect.dimagi.com/dashboards/d2"},
        {"title": "Dashboard",
         "url": "https://labs.connect.dimagi.com/dashboards/d3"},
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
        },
        {
            "title": "Verification integrity",
            "url": "https://labs.connect.dimagi.com/labs/workflow/5125/run/?run_id=5127&opportunity_id=10043",
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


def test_url_less_walkthrough_with_a_passing_phase_is_dropped_loudly(caplog):
    p = _payload_with_synthetic(
        {"synthetic": {"walkthroughs": [{"persona": "no-url-yet"}]}},
        phase_meta={"verdict": "pass"},
    )
    assert p["walkthroughs"] == []
    assert "has no url" in caplog.text


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


def test_workbench_url_dropped_when_internal_links_excluded():
    """The Workbench 404s for anyone who isn't a signed-in member, and
    ace-web rejects non-@dimagi.com sign-ins, so on a public payload the
    only "go deeper" link on the page was a dead end."""
    drive = FakeDriveClient.from_tree(_full_tree())
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    kwargs = dict(workspace=ws, opp_slug="turmeric", run_id="20260503-0835")
    assert build_summary_payload(drive, **kwargs)["workbench_url"] == (
        "/w/test-team/opps/turmeric/runs/20260503-0835"
    )
    assert build_summary_payload(
        drive, include_internal_links=False, **kwargs,
    )["workbench_url"] is None
