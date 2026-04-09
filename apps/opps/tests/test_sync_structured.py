"""Tests for the structured-layout sync layer."""
import pytest

from apps.opps.sync import OppSnapshot, load_opp
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)


@pytest.fixture
def client() -> FakeDriveClient:
    return FakeDriveClient.from_tree(malaria_pilot_structured_tree())


def test_load_opp_returns_full_snapshot(client):
    ace_id = client.folder_id("ACE")
    snap: OppSnapshot = load_opp(client, ace_folder_id=ace_id, slug="malaria-pilot")
    assert snap.opp.slug == "malaria-pilot"
    assert snap.opp.current_run_id == "2026-04-06-002"
    assert [r.run_id for r in snap.all_runs] == [
        "2026-04-06-002",
        "2026-04-01-001",
    ]  # newest first
    # Current run expanded
    assert snap.current_run.run_id == "2026-04-06-002"
    assert snap.current_run.mode == "review"
    assert snap.current_run.status == "running"


def test_load_opp_includes_all_steps_for_current_run(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="malaria-pilot")
    skill_names = [s.step.skill_name for s in snap.current_run.steps]
    assert skill_names == [
        "idea-to-idd",
        "idd-to-learn-app",
        "idd-to-deliver-app",
        "app-deploy",
    ]


def test_load_opp_populates_judge_results(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="malaria-pilot")
    step = next(s for s in snap.current_run.steps if s.step.skill_name == "idea-to-idd")
    assert step.judge is not None
    assert step.judge.score == 9.2
    step_lla = next(s for s in snap.current_run.steps if s.step.skill_name == "idd-to-learn-app")
    assert step_lla.judge.score == 8.5


def test_load_opp_populates_gates(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="malaria-pilot")
    step = next(s for s in snap.current_run.steps if s.step.skill_name == "app-deploy")
    assert len(step.gates) == 1
    assert step.gates[0].decision == "pending"


def test_load_opp_with_explicit_run_id(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(
        client, ace_folder_id=ace_id, slug="malaria-pilot", run_id="2026-04-01-001"
    )
    assert snap.current_run.run_id == "2026-04-01-001"
    # The older run has only 2 steps in the fixture
    assert len(snap.current_run.steps) == 2


def test_load_opp_attaches_idd_body(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="malaria-pilot")
    assert "Malaria Pilot IDD" in snap.idd_body


def test_load_opp_unknown_slug_raises(client):
    ace_id = client.folder_id("ACE")
    with pytest.raises(FileNotFoundError, match="malaria-banana"):
        load_opp(client, ace_folder_id=ace_id, slug="malaria-banana")
