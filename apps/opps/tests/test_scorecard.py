"""Tests for the run-level opp-eval scorecard endpoint.

Covers:
  - ``load_scorecard`` reader (latest verdict + markdown + trend from Drive)
  - ``GET /api/opps/<slug>/scorecard`` view
  - Surfacing per-skill judge verdicts from ``verdicts/*.yaml``
  - Surfacing gate decisions from ``state.yaml``'s ``gates:`` map
"""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.sync import load_opp, load_scorecard
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_tree,
    opp_with_scorecard_tree,
)


@pytest.fixture
def authed_client(db):
    user = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    c = Client()
    c.force_login(user)
    return c


# ---------------------------------------------------------------- reader


def test_load_scorecard_populates_verdict_body_and_trend():
    client = FakeDriveClient.from_tree(opp_with_scorecard_tree())
    ace_id = client.folder_id("ACE")
    sc = load_scorecard(client, ace_folder_id=ace_id, slug="cholera-smoketest")

    assert sc.latest_verdict is not None
    assert sc.latest_verdict.score == 82.0
    assert sc.latest_verdict.passed is True
    assert sc.latest_verdict_variant == "deep"
    assert "design" in sc.latest_verdict.criteria

    assert sc.latest_scorecard_path == "scorecards/2026-04-15-opp-eval-deep.md"
    assert "Overall: **82/100**" in sc.latest_scorecard_body

    assert sc.trend_path == "scorecards/trend.md"
    assert "2026-04-15" in sc.trend_body


def test_load_scorecard_is_empty_when_opp_eval_has_not_run():
    client = FakeDriveClient.from_tree(malaria_pilot_tree())
    ace_id = client.folder_id("ACE")
    sc = load_scorecard(client, ace_folder_id=ace_id, slug="malaria-pilot")

    assert sc.latest_verdict is None
    assert sc.latest_verdict_variant is None
    assert sc.latest_scorecard_path is None
    assert sc.trend_path is None


def test_load_scorecard_missing_opp_raises():
    client = FakeDriveClient.from_tree(malaria_pilot_tree())
    ace_id = client.folder_id("ACE")
    with pytest.raises(FileNotFoundError):
        load_scorecard(client, ace_folder_id=ace_id, slug="nonexistent")


# ---------------------------------------------------------------- view


def _with_fake_drive(client, fake, url):
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        return client.get(url)


def test_scorecard_view_returns_envelope(authed_client):
    fake = FakeDriveClient.from_tree(opp_with_scorecard_tree())
    response = _with_fake_drive(
        authed_client, fake, "/api/opps/cholera-smoketest/scorecard"
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["latest_verdict"]["score"] == 82.0
    assert data["latest_verdict_variant"] == "deep"
    assert "Overall: **82/100**" in data["latest_scorecard_body"]
    assert "2026-04-15" in data["trend_body"]


def test_scorecard_view_empty_payload_when_no_scorecard(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_tree())
    response = _with_fake_drive(
        authed_client, fake, "/api/opps/malaria-pilot/scorecard"
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["latest_verdict"] is None
    assert data["trend_body"] == ""


def test_scorecard_view_unknown_opp_returns_404(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_tree())
    response = _with_fake_drive(
        authed_client, fake, "/api/opps/nonexistent/scorecard"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "opp-not-found"


# --------------------------------------------- per-step verdict + gate surfacing


def test_step_verdict_surfaced_from_verdicts_yaml():
    """A per-skill ``verdicts/<skill>-eval-*.yaml`` surfaces as the
    step's ``judge`` field in the snapshot."""
    client = FakeDriveClient.from_tree(opp_with_scorecard_tree())
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="cholera-smoketest")

    ocs_eval = next(
        s for s in snap.current_run.steps if s.step.skill_name == "ocs-chatbot-eval"
    )
    assert ocs_eval.judge is not None
    assert ocs_eval.judge.score == 78.0
    assert ocs_eval.judge.passed is True


def test_gate_brief_artifact_attributed_to_producing_skill():
    """``gate-briefs/idea-to-pdd.md`` is produced_by idea-to-pdd in the
    manifest, so it surfaces as that step's artifact — which the UI uses
    to auto-open the brief when the step is gate-pending."""
    client = FakeDriveClient.from_tree(opp_with_scorecard_tree())
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="cholera-smoketest")

    idea = next(
        s for s in snap.current_run.steps if s.step.skill_name == "idea-to-pdd"
    )
    brief = next(
        (a for a in idea.artifacts if a.path == "gate-briefs/idea-to-pdd.md"), None
    )
    assert brief is not None, "gate-brief should be attributed to idea-to-pdd"
