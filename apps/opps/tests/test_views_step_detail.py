"""Tests for GET /api/opps/<slug>/runs/<run_id>/steps/<skill>.

Flat layout synthesizes a single implicit run with id "r1"; the URL
pattern still carries `run_id` for back-compat but the value is
ignored by the handler. See docs/plans/2026-04-20-drop-multi-run-simplify.md.
"""
import logging
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_tree,
    nutrition_legacy_flat_tree,
)


@pytest.fixture
def authed_client(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    c = Client()
    c.force_login(u)
    return c


def _with_fake(authed_client, fake, url):
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        return authed_client.get(url)


def test_step_detail_returns_payload_with_primary_body(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_tree())
    response = _with_fake(
        authed_client, fake,
        "/api/opps/malaria-pilot/runs/r1/steps/idea-to-pdd",
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["skill_name"] == "idea-to-pdd"
    # Flat layout: no judge verdicts carried through.
    assert data["judge"] is None
    # idea-to-pdd's artifact is the opp-root pdd.md.
    assert any(a["name"] == "pdd.md" for a in data["artifacts"])
    assert "primary_body" in data
    assert "Malaria Pilot IDD" in data["primary_body"]


def test_step_detail_unknown_step_returns_404(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_tree())
    response = _with_fake(
        authed_client, fake,
        "/api/opps/malaria-pilot/runs/r1/steps/nonexistent",
    )
    assert response.status_code == 404


def test_step_detail_logs_when_artifact_body_read_fails(authed_client, caplog):
    """If get_content blows up on a step's artifact, the step view still
    returns 200 (other artifacts may be readable) but emits a warning
    with traceback so a real Drive permission / 503 doesn't go silent.
    Regression test for the swallowed-exception silence in views.py.

    Scenario: target ``pdd-to-learn-app`` on the nutrition-legacy
    fixture, whose ``app-summaries/learn-app-summary.md`` matches the
    manifest entry for that skill. load_opp doesn't read that file
    itself (it's only surfaced via manifest attribution), so failing
    it only trips the artifact-body loop inside step_detail.
    """
    fake = FakeDriveClient.from_tree(nutrition_legacy_flat_tree())
    real_get_content = fake.get_content
    learn_summary_id = fake.file_id(
        "ACE/nutrition-legacy/app-summaries/learn-app-summary.md"
    )

    def _selective_503(file_id, mime_type):
        if file_id == learn_summary_id:
            raise RuntimeError("simulated drive 503")
        return real_get_content(file_id, mime_type)

    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")), \
         patch.object(fake, "get_content", side_effect=_selective_503), \
         caplog.at_level(logging.WARNING, logger="apps.opps.views"):
        response = authed_client.get(
            "/api/opps/nutrition-legacy/runs/r1/steps/pdd-to-learn-app"
        )

    assert response.status_code == 200
    matching = [
        r for r in caplog.records
        if "step_detail" in r.getMessage()
        and "nutrition-legacy" in r.getMessage()
        and "pdd-to-learn-app" in r.getMessage()
    ]
    assert matching, "expected a warning naming opp + skill"
    assert matching[0].exc_info is not None, "log line should carry traceback"
