"""_stage_env_for skips per-spawn .mcp.json when the bundled plugin is wired.

In the prod container the Nova plugin's own .mcp.json carries a
``headersHelper`` (Dockerfile rewrites it). When that's the case we
must NOT also write a project-level .mcp.json — duplicate ``nova``
servers would surface tools under two prefixes
(``mcp__nova__*`` AND ``mcp__plugin_nova_nova__*``).

In local dev where the plugin isn't installed (or installed without
headersHelper), the per-spawn write is the only thing that gets Nova
into chat — so it must still kick in.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.common.cli_backend import CLIBackend, _plugin_nova_has_headers_helper
from apps.sessions.models import Session


def _seed_plugin_install(
    home: Path,
    *,
    with_headers_helper: bool,
    plugin_id: str = "nova@nova-marketplace",
) -> Path:
    """Build a fake ~/.claude/plugins/ tree mirroring the prod container layout."""
    install = home / ".claude" / "plugins" / "cache" / "nova-marketplace" / "nova" / "1.0.0"
    install.mkdir(parents=True)
    server: dict = {"type": "http", "url": "https://mcp.commcare.app/mcp"}
    if with_headers_helper:
        server["headersHelper"] = "cd /app && python manage.py nova_headers"
    (install / ".mcp.json").write_text(json.dumps({"mcpServers": {"nova": server}}))
    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    registry.write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    plugin_id: [
                        {
                            "scope": "user",
                            "installPath": str(install),
                            "version": "1.0.0",
                        }
                    ]
                },
            }
        )
    )
    return install


@pytest.mark.django_db
def test_detector_returns_true_when_plugin_has_headers_helper(tmp_path):
    _seed_plugin_install(tmp_path, with_headers_helper=True)
    assert _plugin_nova_has_headers_helper(str(tmp_path)) is True


@pytest.mark.django_db
def test_detector_returns_false_when_plugin_lacks_headers_helper(tmp_path):
    _seed_plugin_install(tmp_path, with_headers_helper=False)
    assert _plugin_nova_has_headers_helper(str(tmp_path)) is False


@pytest.mark.django_db
def test_detector_returns_false_when_no_installed_plugins_file(tmp_path):
    assert _plugin_nova_has_headers_helper(str(tmp_path)) is False


@pytest.mark.django_db
def test_detector_ignores_other_plugins_with_headers_helper(tmp_path):
    """A non-Nova plugin advertising headersHelper must NOT short-circuit Nova staging."""
    _seed_plugin_install(
        tmp_path, with_headers_helper=True, plugin_id="some-other@marketplace"
    )
    assert _plugin_nova_has_headers_helper(str(tmp_path)) is False


@pytest.mark.django_db
def test_detector_returns_false_on_malformed_json(tmp_path):
    registry = tmp_path / ".claude" / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True)
    registry.write_text("{not json")
    assert _plugin_nova_has_headers_helper(str(tmp_path)) is False


@pytest.mark.django_db
def test_stage_env_for_skips_per_spawn_write_when_plugin_wired(tmp_path, monkeypatch):
    _seed_plugin_install(tmp_path, with_headers_helper=True)
    monkeypatch.setenv("HOME", str(tmp_path))

    user = get_user_model().objects.create_user(email="d@dimagi.com")
    session = Session.objects.create(owner=user, slug="plug-detect", title="t")

    backend = CLIBackend()
    with patch(
        "apps.common.cli_backend.get_fresh_nova_token", return_value="jwt-x"
    ):
        env, staged_home, source, mcp_config_path = backend._stage_env_for(session)

    try:
        assert mcp_config_path is None  # plugin owns Nova
    finally:
        backend._teardown_staged_home(staged_home)


@pytest.mark.django_db
def test_stage_env_for_writes_per_spawn_when_plugin_lacks_headers_helper(
    tmp_path, monkeypatch
):
    _seed_plugin_install(tmp_path, with_headers_helper=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    user = get_user_model().objects.create_user(email="d@dimagi.com")
    session = Session.objects.create(owner=user, slug="plug-detect", title="t")

    backend = CLIBackend()
    with patch(
        "apps.common.cli_backend.get_fresh_nova_token", return_value="jwt-x"
    ):
        env, staged_home, source, mcp_config_path = backend._stage_env_for(session)

    try:
        assert mcp_config_path is not None
        assert mcp_config_path.endswith("/.mcp.json")
    finally:
        backend._teardown_staged_home(staged_home)
