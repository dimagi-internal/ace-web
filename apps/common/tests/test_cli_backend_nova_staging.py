"""CLIBackend stages a per-spawn .mcp.json with a fresh Nova bearer token.

When Nova creds are present, _stage_env_for must:
  - return an mcp_config_path pointing at <staged_home>/.mcp.json
  - the file contains the right URL + an Authorization header carrying
    the freshly-resolved access token

When Nova creds are absent (or refresh fails), it must return None and
NOT write the file — the spawn proceeds without Nova MCP available.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.common import nova_auth_flow as nf
from apps.common.cli_backend import CLIBackend
from apps.sessions.models import Session


@pytest.fixture
def session():
    user = get_user_model().objects.create_user(email="a@dimagi.com")
    return Session.objects.create(owner=user, slug="abc", title="t")


@pytest.mark.django_db
def test_stage_env_for_writes_mcp_json_when_nova_token_resolves(session):
    backend = CLIBackend()
    with patch("apps.common.cli_backend.get_fresh_nova_token", return_value="jwt-bearer-abc"):
        env, staged_home, source, mcp_config_path = backend._stage_env_for(session)

    try:
        assert mcp_config_path is not None
        assert mcp_config_path == f"{staged_home}/.mcp.json"
        config = json.loads(open(mcp_config_path).read())
        nova = config["mcpServers"]["nova"]
        assert nova["type"] == "http"
        assert nova["url"] == nf.NOVA_DEFAULT_RESOURCE
        assert nova["headers"]["Authorization"] == "Bearer jwt-bearer-abc"
    finally:
        backend._teardown_staged_home(staged_home)


@pytest.mark.django_db
def test_stage_env_for_omits_mcp_json_when_no_nova_creds(session):
    backend = CLIBackend()
    with patch("apps.common.cli_backend.get_fresh_nova_token", return_value=None):
        env, staged_home, source, mcp_config_path = backend._stage_env_for(session)

    try:
        assert mcp_config_path is None
    finally:
        backend._teardown_staged_home(staged_home)


@pytest.mark.django_db
def test_stage_env_for_swallows_nova_refresh_errors(session):
    """A Nova refresh exception must NOT take the chat down — just skip MCP."""
    backend = CLIBackend()
    with patch(
        "apps.common.cli_backend.get_fresh_nova_token",
        side_effect=RuntimeError("network exploded"),
    ):
        env, staged_home, source, mcp_config_path = backend._stage_env_for(session)

    try:
        assert mcp_config_path is None
    finally:
        backend._teardown_staged_home(staged_home)
