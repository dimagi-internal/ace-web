"""Integration smoke test against the real ACE plugin repo.

Skipped when the ACE plugin is not available (CI without the sibling repo).
"""
import os

import pytest
from django.test import Client, override_settings

from apps.auth.models import User

ACE_PLUGIN_PATH = "/Users/jjackson/emdash-projects/ace"


@pytest.fixture
def authed_client(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    c = Client()
    c.force_login(u)
    return c


@pytest.mark.skipif(
    not os.path.isdir(ACE_PLUGIN_PATH),
    reason="ACE plugin repo not present in this environment",
)
@override_settings(ACE_PLUGIN_PATH=ACE_PLUGIN_PATH)
def test_overview_endpoint_with_real_plugin(authed_client):
    resp = authed_client.get("/api/system/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    data = body["data"]
    # Real plugin has 19 registered + 2 utility skills
    assert len(data["skills"]) >= 19
    # Real plugin has 6 agents
    assert len(data["agents"]) == 6
    # Real manifest has 30+ artifacts
    assert len(data["artifacts"]) >= 20
    # idea-to-idd is the first skill
    idd = next(s for s in data["skills"] if s["name"] == "idea-to-idd")
    assert idd["ordinal"] == 1
    assert idd["phase"] == "app-building"
    assert idd["has_judge"] is True
    assert idd["is_gate"] is True
    assert idd["display_name"] == "Idea to IDD"
    # Artifact relationships populated
    assert any(a["path"] == "idd.md" for a in idd["artifacts_produced"])
    # Version info present
    assert data["plugin_version"] is not None


@pytest.mark.skipif(
    not os.path.isdir(ACE_PLUGIN_PATH),
    reason="ACE plugin repo not present in this environment",
)
@override_settings(ACE_PLUGIN_PATH=ACE_PLUGIN_PATH)
def test_skill_detail_with_real_plugin(authed_client):
    resp = authed_client.get("/api/system/skills/idea-to-idd")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["name"] == "idea-to-idd"
    # Full markdown body should be substantial
    assert len(data["body_markdown"]) > 500
    # Body should contain the Process section
    assert "## Process" in data["body_markdown"]


@pytest.mark.skipif(
    not os.path.isdir(ACE_PLUGIN_PATH),
    reason="ACE plugin repo not present in this environment",
)
@override_settings(ACE_PLUGIN_PATH=ACE_PLUGIN_PATH)
def test_agent_detail_with_real_plugin(authed_client):
    resp = authed_client.get("/api/system/agents/app-builder")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["name"] == "app-builder"
    assert len(data["body_markdown"]) > 200


@pytest.mark.skipif(
    not os.path.isdir(ACE_PLUGIN_PATH),
    reason="ACE plugin repo not present in this environment",
)
@override_settings(ACE_PLUGIN_PATH=ACE_PLUGIN_PATH)
def test_version_endpoint_with_real_plugin(authed_client):
    resp = authed_client.get("/api/system/version")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["plugin_found"] is True
    assert data["plugin_version"] is not None
