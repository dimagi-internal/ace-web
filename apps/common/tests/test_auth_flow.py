"""Tests for credential storage + live validation.

The PTY setup-token flow has been removed — the server no longer parses
interactive terminal output. A developer runs scripts/ace_cli_login.py
from their laptop to upload the local credential blob, and these tests
cover the persistence + validation side of that flow.
"""
import json
import os

import pytest

from apps.common import auth_flow


BLOB = {
    "claudeAiOauth": {
        "accessToken": "sk-ant-oat01-" + "a" * 90,
        "refreshToken": "rt-" + "b" * 40,
        "expiresAt": 1_700_000_000,
        "scopes": ["user:inference"],
    }
}


@pytest.mark.django_db
def test_store_credentials_blob_persists_to_db_and_file(tmp_path, monkeypatch, settings):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    settings.ACE_CLAUDE_HOME = str(tmp_path)

    token = auth_flow.store_credentials_blob(BLOB)

    from apps.common.models import SystemConfig
    blob_row = SystemConfig.objects.get(key="claude_credentials_blob")
    assert json.loads(blob_row.value) == BLOB
    token_row = SystemConfig.objects.get(key="claude_oauth_token")
    assert token_row.value == token
    assert token == BLOB["claudeAiOauth"]["accessToken"]
    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == token

    cred_file = tmp_path / ".claude" / ".credentials.json"
    assert cred_file.exists()
    assert json.loads(cred_file.read_text()) == BLOB


def test_store_credentials_blob_rejects_missing_access_token():
    with pytest.raises(ValueError):
        auth_flow.store_credentials_blob({"claudeAiOauth": {}})


def test_store_credentials_blob_rejects_malformed_prefix():
    with pytest.raises(ValueError):
        auth_flow.store_credentials_blob(
            {"claudeAiOauth": {"accessToken": "not-a-real-token"}}
        )


@pytest.mark.django_db
def test_load_stored_token_reads_blob_and_writes_file(tmp_path, settings, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    settings.ACE_CLAUDE_HOME = str(tmp_path)

    from apps.common.models import SystemConfig
    SystemConfig.objects.create(
        key="claude_credentials_blob", value=json.dumps(BLOB)
    )

    loaded = auth_flow.load_stored_token()
    assert loaded == BLOB["claudeAiOauth"]["accessToken"]
    assert (tmp_path / ".claude" / ".credentials.json").exists()


@pytest.mark.django_db
def test_load_stored_token_falls_back_to_legacy_token_key(monkeypatch):
    """A deploy that predates blob migration still has just the token row."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    from apps.common.models import SystemConfig
    SystemConfig.objects.create(
        key="claude_oauth_token",
        value="sk-ant-oat01-legacy-longish-ish-token-longer-than-40",
    )
    assert auth_flow.load_stored_token() == (
        "sk-ant-oat01-legacy-longish-ish-token-longer-than-40"
    )


@pytest.mark.django_db
def test_load_stored_token_backfills_env_to_db(monkeypatch):
    injected = "sk-ant-oat01-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", injected)
    from apps.common.models import SystemConfig
    SystemConfig.objects.filter(key="claude_oauth_token").delete()
    SystemConfig.objects.filter(key="claude_credentials_blob").delete()

    loaded = auth_flow.load_stored_token()
    assert loaded == injected
    row = SystemConfig.objects.get(key="claude_oauth_token")
    assert row.value == injected


def test_token_looks_real_rejects_placeholders_and_shorts():
    assert not auth_flow.token_looks_real(None)
    assert not auth_flow.token_looks_real("")
    assert not auth_flow.token_looks_real("sk-ant-api03-notoauth")
    assert not auth_flow.token_looks_real("sk-ant-oat01-short")
    assert not auth_flow.token_looks_real("sk-ant-oat01-placeholder" + "x" * 30)
    assert auth_flow.token_looks_real("sk-ant-oat01-" + "a" * 80)


def test_cli_is_ready_is_alias_for_validate():
    assert auth_flow.cli_is_ready is auth_flow.validate_stored_token
