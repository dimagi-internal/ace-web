"""Tests for the nova_headers management command.

Claude Code invokes this command at MCP-connect time and merges the
JSON object on stdout into the headers it sends to mcp.commcare.app.
The contract is narrow: exit 0, single JSON object, no extra prose.
"""
from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.common import nova_auth_flow as nf


@pytest.mark.django_db
def test_nova_headers_emits_bearer_when_token_present():
    out = io.StringIO()
    with patch.object(nf, "get_fresh_token", return_value="jwt-abc"):
        call_command("nova_headers", stdout=out)
    headers = json.loads(out.getvalue())
    assert headers == {"Authorization": "Bearer jwt-abc"}


@pytest.mark.django_db
def test_nova_headers_emits_empty_object_when_no_token():
    out = io.StringIO()
    with patch.object(nf, "get_fresh_token", return_value=None):
        call_command("nova_headers", stdout=out)
    assert json.loads(out.getvalue()) == {}


@pytest.mark.django_db
def test_nova_headers_swallows_get_fresh_token_errors():
    """Helper crashing must NOT crash claude -p's plugin loader."""
    out = io.StringIO()
    with patch.object(nf, "get_fresh_token", side_effect=RuntimeError("boom")):
        call_command("nova_headers", stdout=out)
    assert json.loads(out.getvalue()) == {}
