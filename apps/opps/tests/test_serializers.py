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
    assert set(data.keys()) == {"opp", "pdd_body", "runs", "current_run", "phases"}
    # phases is a list (possibly empty if ACE_PLUGIN_PATH isn't a real plugin dir).
    assert isinstance(data["phases"], list)


def test_serialize_opp_card_fields(snap):
    card = serialize_opp_card(snap.opp, snap.current_run)
    assert card["slug"] == "malaria-pilot"
    assert card["display_name"] == "Malaria Pilot — Northern Mozambique"
    assert card["current_run_id"] == "2026-04-06-002"
    assert card["current_step"] == "app-deploy"
    assert "labels" in card


def test_serialize_opp_snapshot_runs_list(snap):
    data = serialize_opp_snapshot(snap)
    assert len(data["runs"]) == 2
    run_ids = [r["run_id"] for r in data["runs"]]
    assert run_ids == ["2026-04-06-002", "2026-04-01-001"]


def test_serialize_opp_snapshot_current_run_has_all_steps(snap):
    data = serialize_opp_snapshot(snap)
    steps = data["current_run"]["steps"]
    skills = [s["skill_name"] for s in steps]
    assert "idea-to-pdd" in skills
    assert "app-deploy" in skills


def test_serialize_step_snapshot_judge_shape(snap):
    step_snap = next(
        s for s in snap.current_run.steps if s.step.skill_name == "idea-to-pdd"
    )
    data = serialize_step_snapshot(step_snap)
    assert data["skill_name"] == "idea-to-pdd"
    assert data["judge"]["score"] == 9.2
    assert data["judge"]["passed"] is True
    assert "rationale" in data["judge"]


def test_serialize_step_snapshot_no_judge(snap):
    step_snap = next(
        s for s in snap.current_run.steps if s.step.skill_name == "app-deploy"
    )
    data = serialize_step_snapshot(step_snap)
    assert data["judge"] is None
    assert len(data["gates"]) == 1
    assert data["gates"][0]["decision"] == "pending"


def test_serialize_step_snapshot_artifacts(snap):
    step_snap = next(
        s for s in snap.current_run.steps if s.step.skill_name == "idea-to-pdd"
    )
    data = serialize_step_snapshot(step_snap)
    assert len(data["artifacts"]) == 1
    assert data["artifacts"][0]["name"] == "pdd.md"
    assert "drive_web_link" in data["artifacts"][0]
