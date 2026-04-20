"""Tests for the flat-layout fallback reader."""
import pytest

from apps.opps.sync import load_opp
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    nutrition_legacy_flat_tree,
)


@pytest.fixture
def client() -> FakeDriveClient:
    return FakeDriveClient.from_tree(nutrition_legacy_flat_tree())


def test_flat_layout_synthesizes_implicit_run(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="nutrition-legacy")
    assert snap.opp.slug == "nutrition-legacy"
    assert snap.opp.current_run_id == "r1"
    assert snap.current_run.run_id == "r1"


def test_flat_layout_populates_pdd_body(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="nutrition-legacy")
    assert "Nutrition IDD" in snap.pdd_body


def test_flat_layout_synthesizes_step_rows_for_full_registry(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="nutrition-legacy")
    skill_names = [s.step.skill_name for s in snap.current_run.steps]
    # The count comes from plugin agent frontmatter; we expect at least
    # the core 19 and at most a handful more as the plugin evolves.
    assert len(skill_names) >= 19
    assert skill_names[0] == "idea-to-pdd"
    assert skill_names[-1] == "cycle-grade"


def test_flat_layout_marks_known_subfolder_steps_complete(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="nutrition-legacy")
    # app-summaries/ subfolder is treated as evidence that
    # pdd-to-learn-app and pdd-to-deliver-app produced output.
    learn = next(s for s in snap.current_run.steps if s.step.skill_name == "pdd-to-learn-app")
    assert learn.step.status == "complete"
    assert any("learn-app-summary" in a.name for a in learn.artifacts)
    # test-results/ subfolder → app-test
    test_step = next(s for s in snap.current_run.steps if s.step.skill_name == "app-test")
    assert test_step.step.status == "complete"


def test_flat_layout_later_steps_pending(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="nutrition-legacy")
    cycle_grade = next(s for s in snap.current_run.steps if s.step.skill_name == "cycle-grade")
    assert cycle_grade.step.status == "pending"
    assert cycle_grade.artifacts == []
