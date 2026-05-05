"""Tests for the public per-run summary payload builder.

See ``docs/specs/2026-05-04-opp-summary-page-design.md``.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.opps.summary import build_summary_payload
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


@dataclass
class _FakeWorkspace:
    drive_root_folder_id: str
    slug: str = "test-team"


def _completed_run_tree() -> dict:
    """A run with every section populated — apps, connect, training,
    OCS assistant, open questions doc, and a future end-date so status
    resolves to 'active'."""
    return {
        "ACE": {
            "open-questions.md": "# Open questions\n\nSee Drive for the full table.",
            "turmeric-pilot": {
                "opp.yaml": "display_name: Turmeric Supplementation\nslug: turmeric-pilot\n",
                "open-questions.md": "# Open questions for turmeric-pilot",
                "runs": {
                    "20260415-1430": {
                        "pdd.md": (
                            "---\n"
                            "archetype: atomic-visit\n"
                            "---\n\n"
                            "# Turmeric Supplementation Pilot\n\n"
                            "A maternal-health pilot in two districts of Bihar.\n\n"
                            "Three months of FLW-led visits.\n"
                        ),
                        "run_state.yaml": (
                            "current_phase: ocs\n"
                            "training_deck:\n"
                            "  presentation_id: deck-abc\n"
                            "  web_view_link: https://docs.google.com/presentation/d/deck-abc/\n"
                            "  title: FLW Training · Turmeric Supplementation\n"
                        ),
                        "deployment-summary.md": (
                            "# Deployment summary\n\n"
                            "## Learn app\n"
                            "Build at https://www.commcarehq.org/a/turmeric/apps/view/learn123/\n\n"
                            "## Deliver app\n"
                            "Build at https://www.commcarehq.org/a/turmeric/apps/view/deliver456/\n"
                        ),
                        "app-summaries": {
                            "learn-app-summary.md": (
                                "---\n"
                                "nova_app_id: learn-nova-001\n"
                                "nova_app_url: https://commcare.app/apps/learn-nova-001\n"
                                "archetype: atomic-visit\n"
                                "display_name: Turmeric Onboarding\n"
                                "---\n\n"
                                "# Turmeric Onboarding\n"
                            ),
                            "deliver-app-summary.md": (
                                "---\n"
                                "nova_app_id: deliver-nova-002\n"
                                "nova_app_url: https://commcare.app/apps/deliver-nova-002\n"
                                "archetype: atomic-visit\n"
                                "display_name: Turmeric Visit\n"
                                "---\n\n"
                                "# Turmeric Visit\n"
                            ),
                        },
                        "connect-setup": {
                            "opportunity.md": (
                                "---\n"
                                "opportunity_id: 4f9c0001-aaaa-bbbb-cccc-000000000001\n"
                                "name: Turmeric Supplementation · Bihar 2026\n"
                                "start_date: '2026-04-15'\n"
                                "end_date: '2099-06-15'\n"
                                "---\n\n"
                                "# Connect opportunity\n"
                            ),
                            "program.md": (
                                "---\n"
                                "program_id: prog-0001\n"
                                "name: Maternal Supplementation 2026\n"
                                "---\n\n"
                                "# Program\n"
                            ),
                        },
                        "training-materials": {
                            "llo-manager-guide.md":   "# LLO manager guide\n",
                            "flw-training-guide.md":  "# FLW training guide\n",
                            "quick-reference.md":     "# Quick reference card\n",
                            "faq.md":                 "# FAQ\n",
                        },
                        "ocs-agent-config.md": (
                            "---\n"
                            "experiment_id: 11792\n"
                            "public_id: ocs-public-uuid-0001\n"
                            "embed_key: ocs-embed-key-secret\n"
                            "collection_id: 718\n"
                            "---\n\n"
                            "# OCS agent config\n"
                        ),
                        "ocs-setup": {
                            "widget-handoff.md": (
                                "---\n"
                                "widget_url: https://chatbots.dimagi.com/c/ocs-public-uuid-0001/\n"
                                "---\n\n"
                                "# Widget handoff\n"
                            ),
                        },
                    },
                },
            },
        }
    }


def _phase2_only_tree() -> dict:
    """A partial run that only has apps deployed — no Connect, OCS,
    training, or open questions yet. Status resolves to in_progress."""
    return {
        "ACE": {
            "early-pilot": {
                "opp.yaml": "display_name: Early Pilot\nslug: early-pilot\n",
                "runs": {
                    "20260420-0900": {
                        "pdd.md": "# Early Pilot\n\nJust getting started.\n",
                        "deployment-summary.md": (
                            "# Deployment summary\n"
                            "## Learn app\n"
                            "https://www.commcarehq.org/a/early/apps/view/abc/\n"
                        ),
                        "app-summaries": {
                            "learn-app-summary.md": (
                                "---\n"
                                "nova_app_id: x\n"
                                "nova_app_url: https://commcare.app/apps/x\n"
                                "display_name: Early Learn\n"
                                "---\n\n# Early Learn\n"
                            ),
                        },
                    },
                },
            },
        }
    }


# ─── Top-level shape ───────────────────────────────────────────────


def test_complete_run_returns_full_payload():
    drive = FakeDriveClient.from_tree(_completed_run_tree())
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))

    payload = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric-pilot", run_id="20260415-1430",
    )

    assert payload is not None
    assert payload["opp"]["display_name"] == "Turmeric Supplementation"
    assert payload["opp"]["status"] == "active"
    assert "Bihar" in payload["opp"]["description"]
    assert payload["opp"]["end_date"] == "2099-06-15"
    assert payload["opp"]["slug"] == "turmeric-pilot"
    assert payload["opp"]["run_id"] == "20260415-1430"

    assert len(payload["apps"]) == 2
    learn = next(a for a in payload["apps"] if a["kind"] == "Learn")
    deliver = next(a for a in payload["apps"] if a["kind"] == "Deliver")
    assert learn["name"] == "Turmeric Onboarding"
    assert learn["nova_url"] == "https://commcare.app/apps/learn-nova-001"
    assert "learn123" in learn["hq_url"]
    assert deliver["nova_url"] == "https://commcare.app/apps/deliver-nova-002"
    assert "deliver456" in deliver["hq_url"]

    assert payload["connect"]["opportunity"]["name"].startswith("Turmeric")
    assert "/o/opportunities/" in payload["connect"]["opportunity"]["url"]
    assert payload["connect"]["program"]["name"] == "Maternal Supplementation 2026"
    assert "/o/programs/prog-0001/" in payload["connect"]["program"]["url"]

    assert payload["training"]["deck"]["url"].endswith("/deck-abc/")
    titles = [d["title"] for d in payload["training"]["docs"]]
    assert titles == [
        "LLO manager guide", "FLW training guide", "Quick reference card", "FAQ",
    ]

    assert payload["assistant"]["public_id"] == "ocs-public-uuid-0001"
    assert payload["assistant"]["embed_key"] == "ocs-embed-key-secret"
    assert payload["assistant"]["ocs_url"] == "https://chatbots.dimagi.com/c/ocs-public-uuid-0001/"

    assert payload["open_questions"] is not None
    assert "fake/" in payload["open_questions"]["url"]

    assert payload["workbench_url"] == "/w/test-team/opps/turmeric-pilot/runs/20260415-1430"


def test_phase_2_only_run_omits_missing_sections():
    drive = FakeDriveClient.from_tree(_phase2_only_tree())
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))

    payload = build_summary_payload(
        drive, workspace=ws, opp_slug="early-pilot", run_id="20260420-0900",
    )

    assert payload is not None
    assert payload["opp"]["status"] == "in_progress"
    assert payload["opp"]["end_date"] is None
    assert len(payload["apps"]) == 1
    assert payload["connect"] is None
    assert payload["assistant"] is None
    assert payload["open_questions"] is None
    # training section may be present-but-empty if neither deck nor docs;
    # spec says "render only if data exists" — assert None.
    assert payload["training"] is None


def test_missing_opp_returns_none():
    drive = FakeDriveClient.from_tree({"ACE": {"other-opp": {"runs": {"r1": {}}}}})
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))

    payload = build_summary_payload(
        drive, workspace=ws, opp_slug="does-not-exist", run_id="r1",
    )
    assert payload is None


def test_missing_run_returns_none():
    drive = FakeDriveClient.from_tree({
        "ACE": {"the-opp": {"runs": {"20260101-1000": {}}}},
    })
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))

    payload = build_summary_payload(
        drive, workspace=ws, opp_slug="the-opp", run_id="20260202-2222",
    )
    assert payload is None


def test_no_runs_folder_returns_none():
    drive = FakeDriveClient.from_tree({
        "ACE": {"flat-opp": {"opp.yaml": "display_name: Flat\nslug: flat-opp\n"}},
    })
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))

    payload = build_summary_payload(
        drive, workspace=ws, opp_slug="flat-opp", run_id="any",
    )
    assert payload is None


# ─── Status derivation ─────────────────────────────────────────────


def test_status_closed_when_cycle_grade_present():
    tree = _completed_run_tree()
    tree["ACE"]["turmeric-pilot"]["runs"]["20260415-1430"]["closeout"] = {
        "cycle-grade.md": "# Cycle grade\n\nOverall: A-\n",
    }
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))

    payload = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric-pilot", run_id="20260415-1430",
    )
    assert payload["opp"]["status"] == "closed"


def test_status_in_progress_when_end_date_past():
    tree = _completed_run_tree()
    tree["ACE"]["turmeric-pilot"]["runs"]["20260415-1430"]["connect-setup"]["opportunity.md"] = (
        "---\n"
        "opportunity_id: aaaa\n"
        "name: Turmeric · Closed\n"
        "end_date: '2020-01-01'\n"
        "---\n"
    )
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))

    payload = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric-pilot", run_id="20260415-1430",
    )
    assert payload["opp"]["status"] == "in_progress"


# ─── Frontmatter / parsing edge cases ──────────────────────────────


def test_missing_frontmatter_falls_back_to_h1_for_app_name():
    tree = _phase2_only_tree()
    tree["ACE"]["early-pilot"]["runs"]["20260420-0900"]["app-summaries"][
        "learn-app-summary.md"
    ] = "# A Different Title\n\nNo frontmatter here.\n"
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))

    payload = build_summary_payload(
        drive, workspace=ws, opp_slug="early-pilot", run_id="20260420-0900",
    )
    assert payload["apps"][0]["name"] == "A Different Title"
    assert payload["apps"][0]["nova_url"] is None


def test_malformed_frontmatter_does_not_500():
    tree = _phase2_only_tree()
    tree["ACE"]["early-pilot"]["runs"]["20260420-0900"]["app-summaries"][
        "learn-app-summary.md"
    ] = "---\nthis is: not: valid: yaml: at: all:\nbecause::: too: many: colons:\n---\n# Fine\n"
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))

    payload = build_summary_payload(
        drive, workspace=ws, opp_slug="early-pilot", run_id="20260420-0900",
    )
    # Falls back to H1; nova_url is None rather than crashing.
    assert payload is not None
    assert payload["apps"][0]["name"] in ("Fine", "Early Learn")  # tolerant


def test_widget_handoff_url_preferred_over_constructed():
    tree = _completed_run_tree()
    tree["ACE"]["turmeric-pilot"]["runs"]["20260415-1430"]["ocs-setup"]["widget-handoff.md"] = (
        "---\n"
        "widget_url: https://staging.example.com/c/some-other-id/\n"
        "---\n# Handoff\n"
    )
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))

    payload = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric-pilot", run_id="20260415-1430",
    )
    assert payload["assistant"]["ocs_url"] == "https://staging.example.com/c/some-other-id/"


def test_no_workspace_root_returns_none():
    drive = FakeDriveClient.from_tree({"ACE": {}})
    ws = _FakeWorkspace(drive_root_folder_id="")  # empty
    payload = build_summary_payload(
        drive, workspace=ws, opp_slug="x", run_id="y",
    )
    assert payload is None
