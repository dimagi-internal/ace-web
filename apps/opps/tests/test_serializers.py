"""Tests that the serializers produce the exact JSON shape the frontend expects."""
import pytest

from apps.opps.serializers import (
    serialize_opp_card,
    serialize_opp_snapshot,
    serialize_step_snapshot,
)
from apps.opps.sync import load_opp
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)


@pytest.fixture
def snap():
    client = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    ace_id = client.folder_id("ACE")
    return load_opp(client, ace_folder_id=ace_id, slug="malaria-pilot")


def test_serialize_opp_snapshot_top_level_keys(snap):
    data = serialize_opp_snapshot(snap)
    assert set(data.keys()) == {"opp", "pdd_body", "current_run", "phases"}
    # phases is a list (possibly empty if ACE_PLUGIN_PATH isn't a real plugin dir).
    assert isinstance(data["phases"], list)


def test_serialize_opp_card_fields(snap):
    card = serialize_opp_card(snap.opp, snap.current_run)
    assert card["slug"] == "malaria-pilot"
    assert card["display_name"] == "Malaria Pilot — Northern Mozambique"
    # Flat layout synthesizes a single run with id "r1".
    assert card["current_run_id"] == "r1"
    assert card["current_step"] == "app-test"
    assert "labels" in card


def test_serialize_opp_snapshot_current_run_has_all_steps(snap):
    data = serialize_opp_snapshot(snap)
    steps = data["current_run"]["steps"]
    skills = [s["skill_name"] for s in steps]
    # All canonical skills are emitted as rows (with status pending if no
    # artifacts are present on Drive). Count comes from plugin agent
    # frontmatter — at least 19 today.
    assert "idea-to-pdd" in skills
    assert "app-deploy" in skills
    assert len(skills) >= 19


def test_serialize_step_snapshot_no_judge_no_gates(snap):
    """When no verdicts/ files and no state.yaml gates: are present, the
    step payload contains null judge and empty gates for frontend compat."""
    step_snap = next(
        s for s in snap.current_run.steps if s.step.skill_name == "idea-to-pdd"
    )
    data = serialize_step_snapshot(step_snap)
    assert data["judge"] is None
    assert data["gates"] == []


def test_serialize_step_snapshot_artifacts(snap):
    """idea-to-pdd's artifact is the opp-root pdd.md."""
    step_snap = next(
        s for s in snap.current_run.steps if s.step.skill_name == "idea-to-pdd"
    )
    data = serialize_step_snapshot(step_snap)
    assert len(data["artifacts"]) == 1
    assert data["artifacts"][0]["name"] == "pdd.md"
    assert "drive_web_link" in data["artifacts"][0]
