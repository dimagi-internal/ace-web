"""Tests for the chat-seed builder."""
import pytest

from apps.opps.seed import build_chat_seed
from apps.opps.sync import load_opp
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_tree,
)


@pytest.fixture
def snap_with_bodies():
    client = FakeDriveClient.from_tree(malaria_pilot_tree())
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="malaria-pilot")
    return snap, client


def test_seed_includes_idd_excerpt(snap_with_bodies):
    snap, client = snap_with_bodies
    seed = build_chat_seed(
        snap, skill="idea-to-pdd", drive_client=client,
        skill_md_path="skills/idea-to-pdd/SKILL.md",
    )
    assert "## IDD" in seed
    assert "Malaria Pilot IDD" in seed


def test_seed_includes_artifact_body(snap_with_bodies):
    snap, client = snap_with_bodies
    seed = build_chat_seed(
        snap, skill="idea-to-pdd", drive_client=client,
        skill_md_path="skills/idea-to-pdd/SKILL.md",
    )
    assert "## Artifacts" in seed
    assert "pdd.md" in seed


def test_seed_includes_skill_md_path(snap_with_bodies):
    snap, client = snap_with_bodies
    seed = build_chat_seed(
        snap, skill="idea-to-pdd", drive_client=client,
        skill_md_path="skills/idea-to-pdd/SKILL.md",
    )
    assert "skills/idea-to-pdd/SKILL.md" in seed


def test_seed_includes_improvement_loop_preamble(snap_with_bodies):
    snap, client = snap_with_bodies
    seed = build_chat_seed(
        snap, skill="idea-to-pdd", drive_client=client,
        skill_md_path="skills/idea-to-pdd/SKILL.md",
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
