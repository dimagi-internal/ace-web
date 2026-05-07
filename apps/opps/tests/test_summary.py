"""Tests for the public per-run summary payload builder.

The fixtures mirror the actual ACE Drive layout (May 2026) — see the
module docstring in ``apps/opps/summary.py`` for the canonical map.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.opps.summary import build_summary_payload
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


@dataclass
class _FakeWorkspace:
    drive_root_folder_id: str
    slug: str = "test-team"


# ── Fixture builders ───────────────────────────────────────────────


_PDD_BODY = """\
Intervention Design Document: Turmeric Market Survey

Overview
FLWs visit markets to photograph turmeric vendors[a][b], capturing a yellow MTN card in each photo as a visual reference. Each visit also records the GPS location of the vendor.

Background
Long technical context that should NOT be the description.
"""


_LEARN_SUMMARY = """\
---
nova_app_id: mFknxMlsoLlkR28R2qpE
nova_app_url: https://commcare.app/apps/mFknxMlsoLlkR28R2qpE
archetype: atomic-visit
title: "Turmeric Market Survey — FLW Training"
connect_type: learn
validated: true
---

# Learn App Summary
"""


_DELIVER_SUMMARY = """\
---
nova_app_id: 5VI1WKCEOF5ugIenbu0i
nova_app_url: https://commcare.app/apps/5VI1WKCEOF5ugIenbu0i
archetype: atomic-visit
title: "Turmeric Market Survey — Vendor Visit"
connect_type: deliver
validated: true
---

# Deliver App Summary
"""


_DEPLOY_SUMMARY = """\
---
hq_base_url: https://www.commcarehq.org
hq_domain: connect-ace-prod
learn_app_id: d29dbb77012e400f9a700a731319ea55
learn_app_url: https://www.commcarehq.org/a/connect-ace-prod/apps/view/d29dbb77012e400f9a700a731319ea55/
learn_build_status: success
deliver_app_id: 91cf053ed8f149afb06284a65150debf
deliver_app_url: https://www.commcarehq.org/a/connect-ace-prod/apps/view/91cf053ed8f149afb06284a65150debf/
deliver_build_status: success
---

# Deployment Summary
"""


_OPP_BODY = """\
# Connect Opportunity — turmeric

## Identity
- **Opportunity ID (UUID):** `8c46d744-eee4-48ff-9efb-9a8ab1520dc3`
- **Name:** Turmeric Market Survey — turmeric (2026-05-03)
- **URL:** https://connect.dimagi.com/a/ai-demo-space/opportunity/8c46d744-eee4-48ff-9efb-9a8ab1520dc3/
- **Program:** `cc8ff997-46ac-4c79-a7dd-9563b3babbba`

## Core configuration

| Field | Value |
|---|---|
| `short_description` | Turmeric vendor photo+GPS+19-field survey |
| `currency` | USD |
| `start_date` | 2026-06-14 (placeholder — LLO sets concrete date in Phase 6) |
| `end_date` | 2099-08-09 (placeholder) |
"""


_PROGRAM_BODY = """\
# Connect Program

## Identity
- **Program ID (UUID):** `cc8ff997-46ac-4c79-a7dd-9563b3babbba`
- **Name:** Turmeric Market Survey — turmeric (2026-05-03)
- **URL:** https://connect.dimagi.com/a/ai-demo-space/program/cc8ff997-46ac-4c79-a7dd-9563b3babbba/
"""


_WIDGET_HANDOFF = """\
---
opp: turmeric
status: pending-operator-paste-in
---

# OCS Widget Handoff

## Credentials to paste

| Connect field | Value |
|---|---|
| `chatbot_url` | `https://www.openchatstudio.com/chatbots/embed/1fcddd08-02cb-4b22-b482-181cb2f10dcb/` |
| `chatbot_public_id` | `1fcddd08-02cb-4b22-b482-181cb2f10dcb` |
| `chatbot_embed_key` | `wDwe70vquTLm4M0carkTHGaQgrb0NYKP` |
"""


def _full_tree() -> dict:
    return {
        "ACE": {
            "turmeric": {
                "opp.yaml": "display_name: turmeric\nslug: turmeric\n",
                "inputs": {"pdd.md": _PDD_BODY},
                "connect-setup": {
                    "opportunity.md": _OPP_BODY,
                    "program.md": _PROGRAM_BODY,
                },
                "ocs-setup": {"widget-handoff.md": _WIDGET_HANDOFF},
                "ocs-agent-config.md": (
                    "---\n"
                    "opp: turmeric\n"
                    "status: done\n"
                    "experiment_id: 12027\n"
                    "---\n"
                ),
                "training-materials": {
                    "Turmeric Market Survey — Training Deck": "deck-stub",
                    "llo-manager-guide.md": "# LLO guide\n",
                    "flw-training-guide.md": "# FLW guide\n",
                    "quick-reference.md": "# Quick ref\n",
                    "faq.md": "# FAQ\n",
                    "onboarding-email-body.md": "# Onboarding email\n",
                },
                "runs": {
                    "20260503-0835": {
                        "run_state.yaml": "current_phase: ocs\n",
                        "open-questions.md": "# Open questions\n",
                        "2-commcare": {
                            "pdd-to-learn-app_summary.md": _LEARN_SUMMARY,
                            "pdd-to-deliver-app_summary.md": _DELIVER_SUMMARY,
                            "app-deploy_summary.md": _DEPLOY_SUMMARY,
                        },
                    },
                },
            },
        }
    }


def _phase2_only_tree() -> dict:
    return {
        "ACE": {
            "early-pilot": {
                "opp.yaml": "display_name: early-pilot\n",
                "runs": {
                    "20260420-0900": {
                        "2-commcare": {
                            "pdd-to-learn-app_summary.md": _LEARN_SUMMARY.replace(
                                "Turmeric", "Early"
                            ),
                            "app-deploy_summary.md": _DEPLOY_SUMMARY.replace(
                                "deliver_app_url:",
                                "# (no deliver yet)\nplaceholder:",
                            ),
                        },
                    },
                },
            },
        }
    }


def _set_drive_link(client: FakeDriveClient, path: str) -> str:
    """Return what FakeDriveClient gives for web_view_link of a node at path."""
    return f"https://fake/{client.file_id(path)}"


# ─── Top-level shape ───────────────────────────────────────────────


def _set_mime(drive: FakeDriveClient, path: str, mime: str) -> None:
    """Test helper — Google Slides files have no extension and their
    mime can't be guessed by the fake client. Set it manually."""
    node = drive._nodes_by_id[drive.file_id(path)]
    node.mime_type = mime


def test_complete_run_returns_full_payload():
    drive = FakeDriveClient.from_tree(_full_tree())
    _set_mime(
        drive,
        "ACE/turmeric/training-materials/Turmeric Market Survey — Training Deck",
        "application/vnd.google-apps.presentation",
    )
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))

    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p is not None

    # Hero
    assert p["opp"]["display_name"] == "Turmeric Market Survey"
    assert "FLWs visit markets" in p["opp"]["description"]
    assert "[a]" not in p["opp"]["description"]   # docs comment markers stripped
    assert "**" not in p["opp"]["description"]    # bold markdown stripped
    assert p["opp"]["status"] == "active"
    assert p["opp"]["end_date"] == "2099-08-09"

    # Apps
    assert len(p["apps"]) == 2
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
    assert p["connect"]["opportunity"]["end_date"] == "2099-08-09"
    assert p["connect"]["program"]["name"].startswith("Turmeric Market Survey")
    assert "/program/cc8ff997" in p["connect"]["program"]["url"]

    # Training
    assert p["training"]["deck"]["title"].startswith("Turmeric Market Survey")
    titles = [d["title"] for d in p["training"]["docs"]]
    assert titles == [
        "LLO manager guide", "FLW training guide", "Quick reference card",
        "FAQ", "Onboarding email",
    ]

    # Assistant — admin URL `/a/<team>/chatbots/<experiment_id>/` so an
    # operator can view/edit the bot in OCS. The widget-handoff
    # `chatbot_url` (an embed-page URL) is NOT what we link to; that
    # URL is a 404 on OCS.
    assert p["assistant"]["public_id"] == "1fcddd08-02cb-4b22-b482-181cb2f10dcb"
    assert p["assistant"]["embed_key"] == "wDwe70vquTLm4M0carkTHGaQgrb0NYKP"
    assert p["assistant"]["ocs_url"] == "https://www.openchatstudio.com/a/connect-ace/chatbots/12027/"

    # Open questions
    assert p["open_questions"]["url"].startswith("https://fake/")

    # Workbench escape
    assert p["workbench_url"] == "/w/test-team/opps/turmeric/runs/20260503-0835"


def test_phase2_only_omits_missing_sections():
    drive = FakeDriveClient.from_tree(_phase2_only_tree())
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="early-pilot", run_id="20260420-0900",
    )
    assert p is not None
    assert p["connect"] is None
    assert p["training"] is None
    assert p["assistant"] is None
    assert p["open_questions"] is None
    assert p["opp"]["status"] == "in_progress"
    assert p["opp"]["end_date"] is None
    # Apps still present (Learn only — deploy summary lacks deliver_app_url
    # so it's still rendered as Learn).
    assert any(a["kind"] == "Learn" for a in p["apps"])


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


def test_status_closed_when_cycle_grade_in_phase_folder():
    tree = _full_tree()
    tree["ACE"]["turmeric"]["runs"]["20260503-0835"]["7-closeout"] = {
        "cycle-grade.md": "# Cycle grade\n\nOverall: A-\n",
    }
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["opp"]["status"] == "closed"


def test_status_in_progress_when_end_date_past():
    tree = _full_tree()
    tree["ACE"]["turmeric"]["connect-setup"]["opportunity.md"] = (
        _OPP_BODY.replace("2099-08-09", "2020-01-01")
    )
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["opp"]["status"] == "in_progress"


# ─── Hero parsing edge cases ───────────────────────────────────────


def test_hero_name_falls_back_to_yaml_display_when_pdd_missing():
    tree = _phase2_only_tree()
    tree["ACE"]["early-pilot"]["opp.yaml"] = "display_name: My Friendly Name\n"
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="early-pilot", run_id="20260420-0900",
    )
    assert p["opp"]["display_name"] == "My Friendly Name"


def test_hero_name_falls_back_to_slug_when_yaml_matches_slug():
    tree = _phase2_only_tree()
    tree["ACE"]["early-pilot"]["opp.yaml"] = "display_name: early-pilot\n"
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="early-pilot", run_id="20260420-0900",
    )
    assert p["opp"]["display_name"] == "early-pilot"


def test_hero_description_uses_overview_section():
    tree = _full_tree()
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    desc = p["opp"]["description"]
    assert desc.startswith("FLWs visit markets")
    # Background paragraph should not be included.
    assert "Long technical context" not in desc


# ─── Markdown body extraction ──────────────────────────────────────


def test_widget_handoff_table_parsing():
    """Confirm the chatbot_public_id / chatbot_embed_key are extracted
    from the markdown table even when surrounded by backticks and pipes."""
    tree = _full_tree()
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    a = p["assistant"]
    assert a["public_id"] == "1fcddd08-02cb-4b22-b482-181cb2f10dcb"
    assert a["embed_key"] == "wDwe70vquTLm4M0carkTHGaQgrb0NYKP"


def test_experiment_id_falls_back_to_resume_from():
    """When ocs-agent-config.md doesn't carry experiment_id as a
    frontmatter field but does have ``resume_from: existing-bot-experiment-N``,
    the OCS admin URL should still resolve."""
    tree = _full_tree()
    tree["ACE"]["turmeric"]["ocs-agent-config.md"] = (
        "---\n"
        "opp: turmeric\n"
        "status: done\n"
        "resume_from: existing-bot-experiment-99999\n"
        "---\n"
    )
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["assistant"]["ocs_url"].endswith("/chatbots/99999/")


def test_experiment_id_falls_back_to_handoff_body():
    """As a last resort, scrape ``experiment N`` from widget-handoff.md
    body prose."""
    tree = _full_tree()
    tree["ACE"]["turmeric"]["ocs-agent-config.md"] = (
        "---\nopp: turmeric\nstatus: done\n---\n"
    )
    tree["ACE"]["turmeric"]["ocs-setup"]["widget-handoff.md"] = (
        _WIDGET_HANDOFF
        + "\n\nThese credentials belong to experiment 55555 (default version).\n"
    )
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["assistant"]["ocs_url"].endswith("/chatbots/55555/")


def test_no_experiment_id_yields_null_ocs_url():
    """If experiment_id can't be found anywhere, ``ocs_url`` is None
    (the widget still mounts; just no admin link)."""
    tree = _full_tree()
    tree["ACE"]["turmeric"]["ocs-agent-config.md"] = (
        "---\nopp: turmeric\nstatus: done\n---\n"
    )
    # Strip the "experiment 12027" mention from the handoff body.
    drive = FakeDriveClient.from_tree(tree)
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    # The base _WIDGET_HANDOFF doesn't have "experiment N" prose either.
    p = build_summary_payload(
        drive, workspace=ws, opp_slug="turmeric", run_id="20260503-0835",
    )
    assert p["assistant"]["ocs_url"] is None
    # Public id and embed key still present so the corner widget mounts.
    assert p["assistant"]["public_id"]
    assert p["assistant"]["embed_key"]
