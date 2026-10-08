"""ace-web has no Slack surface (removed 2026-10-08; Slack is canopy's now).

Removed routes must 404 — no dead handlers, no redirect to a login page.
"""
import pytest


@pytest.mark.django_db
@pytest.mark.parametrize("path", [
    "/api/slack/commands",
    "/api/slack/events",
    "/api/slack/interactivity",
    "/api/slack/install",
    "/auth/slack/",
    "/api/w/dimagi-team/slack/status",
    "/api/w/dimagi-team/slack/channels",
    "/api/w/dimagi-team/slack/push-info",
])
def test_slack_routes_are_gone(client, path):
    assert client.get(path).status_code == 404
    assert client.post(path, data="{}", content_type="application/json").status_code == 404
