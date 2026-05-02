"""CLIBackend injects NOVA_BEARER_TOKEN into the spawn env.

The bundled Nova plugin's ``.mcp.json`` (rewritten in the Dockerfile)
declares ``"Authorization": "Bearer ${NOVA_BEARER_TOKEN:-}"``. Claude
Code expands that env var when it loads the MCP server, so the value
of ``NOVA_BEARER_TOKEN`` in the spawn env is the entire Nova auth
contract — there's no headersHelper subprocess, no per-spawn .mcp.json
write, no detection logic.

These tests pin the contract: the env var is always set (empty when
not connected), refresh exceptions degrade to empty (chat keeps
working), and the value matches what nova_auth_flow returns.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.common.cli_backend import NOVA_BEARER_TOKEN_ENV, CLIBackend
from apps.sessions.models import Session


@pytest.fixture
def session():
    user = get_user_model().objects.create_user(email="a@dimagi.com")
    return Session.objects.create(owner=user, slug="abc", title="t")


@pytest.mark.django_db
def test_stage_env_for_sets_bearer_when_token_resolves(session):
    backend = CLIBackend()
    with patch(
        "apps.common.cli_backend.get_fresh_nova_token",
        return_value="jwt-bearer-abc",
    ):
        env, staged_home, _ = backend._stage_env_for(session)
    try:
        assert env[NOVA_BEARER_TOKEN_ENV] == "jwt-bearer-abc"
    finally:
        backend._teardown_staged_home(staged_home)


@pytest.mark.django_db
def test_stage_env_for_sets_empty_string_when_no_nova_token(session):
    """Empty string (not unset) so ${NOVA_BEARER_TOKEN:-} expands cleanly."""
    backend = CLIBackend()
    with patch("apps.common.cli_backend.get_fresh_nova_token", return_value=None):
        env, staged_home, _ = backend._stage_env_for(session)
    try:
        assert env[NOVA_BEARER_TOKEN_ENV] == ""
    finally:
        backend._teardown_staged_home(staged_home)


@pytest.mark.django_db
def test_stage_env_for_swallows_nova_refresh_errors(session):
    """A Nova outage must NOT take chat down — set empty and let MCP 401."""
    backend = CLIBackend()
    with patch(
        "apps.common.cli_backend.get_fresh_nova_token",
        side_effect=RuntimeError("network exploded"),
    ):
        env, staged_home, _ = backend._stage_env_for(session)
    try:
        assert env[NOVA_BEARER_TOKEN_ENV] == ""
    finally:
        backend._teardown_staged_home(staged_home)
