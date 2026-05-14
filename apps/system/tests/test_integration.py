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
    data = resp.json()
    # Real plugin has at least ~19 phase skills + 1-2 utility
    assert len(data["skills"]) >= 19
    # Real plugin has at least 6 agents (phase agents + orchestrator +
    # specialties). Exact count varies as agents are added.
    assert len(data["agents"]) >= 6
    # Real manifest has 20+ artifacts
    assert len(data["artifacts"]) >= 20
    # Phases come as structured objects (name, display_name, ordinal, agent)
    assert len(data["phases"]) >= 4
    assert all("display_name" in p and "ordinal" in p for p in data["phases"])
    # idea-to-pdd is the first skill in the lifecycle (Phase 1, ordinal 1)
    pdd = next(s for s in data["skills"] if s["name"] == "idea-to-pdd")
    assert pdd["ordinal"] == 1
    assert pdd["has_judge"] is True
    assert pdd["display_name"] == "Idea to PDD"
    # Artifact relationships populated. Plugin 0.13.0+ moved per-run
    # artifacts under N-phase folders (`pdd.md` → `1-design/idea-to-pdd.md`).
    assert any(a["path"] == "1-design/idea-to-pdd.md" for a in pdd["artifacts_produced"])
    # Version info present
    assert data["plugin_version"] is not None


@pytest.mark.skipif(
    not os.path.isdir(ACE_PLUGIN_PATH),
    reason="ACE plugin repo not present in this environment",
)
@override_settings(ACE_PLUGIN_PATH=ACE_PLUGIN_PATH)
def test_skill_detail_with_real_plugin(authed_client):
    resp = authed_client.get("/api/system/skills/idea-to-pdd")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "idea-to-pdd"
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
    # The orchestrator is the one agent guaranteed to exist regardless of
    # how the phase agents get reshuffled.
    resp = authed_client.get("/api/system/agents/ace-orchestrator")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "ace-orchestrator"
    assert len(data["body_markdown"]) > 200


@pytest.mark.skipif(
    not os.path.isdir(ACE_PLUGIN_PATH),
    reason="ACE plugin repo not present in this environment",
)
@override_settings(ACE_PLUGIN_PATH=ACE_PLUGIN_PATH)
def test_version_endpoint_with_real_plugin(authed_client):
    resp = authed_client.get("/api/system/version")
    assert resp.status_code == 200
    data = resp.json()
    assert data["plugin_found"] is True
    assert data["plugin_version"] is not None
