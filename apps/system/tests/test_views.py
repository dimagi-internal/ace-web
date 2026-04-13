"""Tests for apps.system DRF views."""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User


@pytest.fixture
def authed_user(db):
    return User.objects.create(email="jon@dimagi.com", display_name="Jon")


@pytest.fixture
def authed_client(authed_user):
    c = Client()
    c.force_login(authed_user)
    return c


MOCK_OVERVIEW = {
    "skills": [
        {
            "name": "idea-to-idd",
            "display_name": "Idea to IDD",
            "description": "Iterate on an idea.",
            "ordinal": 1,
            "phase": "app-building",
            "has_judge": True,
            "is_gate": True,
            "is_recurring": False,
            "primary_output": "idd.md",
            "artifacts_produced": [],
            "artifacts_consumed": [],
        }
    ],
    "agents": [{"name": "app-builder", "description": "Builds apps.", "model": "inherit"}],
    "artifacts": [],
    "phases": ["app-building", "connect-setup", "llo-management", "closeout"],
    "warning": None,
}

MOCK_VERSION = {
    "plugin_found": True,
    "plugin_version": "0.1.10",
    "remote_version": "0.1.11",
    "update_available": True,
    "plugin_path": "/tmp/ace",
}


class TestOverviewView:
    @patch("apps.system.views.check_version", return_value=MOCK_VERSION)
    @patch("apps.system.views.load_system_overview", return_value=dict(MOCK_OVERVIEW))
    def test_returns_skills_and_agents(self, mock_load, mock_ver, authed_client):
        resp = authed_client.get("/api/system/overview")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["skills"]) == 1
        assert data["skills"][0]["name"] == "idea-to-idd"
        assert len(data["agents"]) == 1
        assert data["plugin_version"] == "0.1.10"
        assert data["remote_version"] == "0.1.11"
        assert data["update_available"] is True

    def test_unauthenticated_returns_401(self, db):
        c = Client()
        resp = c.get("/api/system/overview")
        assert resp.status_code in (401, 403)


class TestSkillDetailView:
    @patch(
        "apps.system.views.load_skill_detail",
        return_value={
            "name": "idea-to-idd",
            "display_name": "Idea to IDD",
            "description": "...",
            "ordinal": 1,
            "phase": "app-building",
            "has_judge": True,
            "is_gate": True,
            "is_recurring": False,
            "primary_output": "idd.md",
            "artifacts_produced": [],
            "artifacts_consumed": [],
            "body_markdown": "# Idea to IDD\n\nBody here.",
        },
    )
    def test_returns_skill_with_body(self, mock_load, authed_client):
        resp = authed_client.get("/api/system/skills/idea-to-idd")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["name"] == "idea-to-idd"
        assert "Body here" in data["body_markdown"]

    @patch("apps.system.views.load_skill_detail", return_value=None)
    def test_unknown_skill_returns_404(self, mock_load, authed_client):
        resp = authed_client.get("/api/system/skills/nonexistent")
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "skill-not-found"


class TestAgentDetailView:
    @patch(
        "apps.system.views.load_agent_detail",
        return_value={
            "name": "app-builder",
            "description": "Builds apps.",
            "model": "inherit",
            "body_markdown": "# App Builder\n\nWorkflow here.",
        },
    )
    def test_returns_agent_with_body(self, mock_load, authed_client):
        resp = authed_client.get("/api/system/agents/app-builder")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["name"] == "app-builder"
        assert "Workflow here" in data["body_markdown"]

    @patch("apps.system.views.load_agent_detail", return_value=None)
    def test_unknown_agent_returns_404(self, mock_load, authed_client):
        resp = authed_client.get("/api/system/agents/nonexistent")
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "agent-not-found"


class TestVersionView:
    @patch("apps.system.views.check_version", return_value=MOCK_VERSION)
    def test_returns_version_info(self, mock_ver, authed_client):
        resp = authed_client.get("/api/system/version")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["plugin_version"] == "0.1.10"
        assert data["update_available"] is True
