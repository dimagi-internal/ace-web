"""Tests for the chat-seed builder."""
import pytest

from apps.opps.seed import build_chat_seed
from apps.opps.sync import load_opp
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)


@pytest.fixture
def snap_with_bodies():
    client = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="malaria-pilot")
    return snap, client


def test_seed_includes_idd_excerpt(snap_with_bodies):
    snap, client = snap_with_bodies
    seed = build_chat_seed(
        snap, skill="idea-to-idd", drive_client=client,
        skill_md_path="skills/idea-to-idd/SKILL.md",
    )
    assert "## IDD" in seed
    assert "Malaria Pilot IDD" in seed


def test_seed_includes_artifact_body(snap_with_bodies):
    snap, client = snap_with_bodies
    seed = build_chat_seed(
        snap, skill="idea-to-idd", drive_client=client,
        skill_md_path="skills/idea-to-idd/SKILL.md",
    )
    assert "## Artifacts" in seed
    assert "idd.md" in seed


def test_seed_includes_judge_verdict(snap_with_bodies):
    snap, client = snap_with_bodies
    seed = build_chat_seed(
        snap, skill="idea-to-idd", drive_client=client,
        skill_md_path="skills/idea-to-idd/SKILL.md",
    )
    assert "## Judge verdict" in seed
    assert "9.2" in seed
    assert "comprehensive" in seed


def test_seed_includes_gate_history_for_gate_steps(snap_with_bodies):
    snap, client = snap_with_bodies
    seed = build_chat_seed(
        snap, skill="app-deploy", drive_client=client,
        skill_md_path="skills/app-deploy/SKILL.md",
    )
    assert "## Gate history" in seed
    assert "pending" in seed


def test_seed_includes_skill_md_path(snap_with_bodies):
    snap, client = snap_with_bodies
    seed = build_chat_seed(
        snap, skill="idea-to-idd", drive_client=client,
        skill_md_path="skills/idea-to-idd/SKILL.md",
    )
    assert "skills/idea-to-idd/SKILL.md" in seed


def test_seed_includes_improvement_loop_preamble(snap_with_bodies):
    snap, client = snap_with_bodies
    seed = build_chat_seed(
        snap, skill="idea-to-idd", drive_client=client,
        skill_md_path="skills/idea-to-idd/SKILL.md",
    )
    # Preamble should explain the loop so Claude knows it can propose an edit.
    assert "improvement loop" in seed.lower() or "propose" in seed.lower()


def test_seed_unknown_skill_raises(snap_with_bodies):
    snap, client = snap_with_bodies
    with pytest.raises(ValueError, match="no step"):
        build_chat_seed(
            snap, skill="not-a-skill", drive_client=client,
            skill_md_path="skills/nope/SKILL.md",
        )
