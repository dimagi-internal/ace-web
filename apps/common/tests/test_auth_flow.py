"""Tests for credential storage + live validation.

The PTY setup-token flow has been removed — the server no longer parses
interactive terminal output. A developer runs scripts/ace_cli_login.py
from their laptop to upload the local credential blob, and these tests
cover the persistence + validation side of that flow.
"""
import json

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


@pytest.fixture(autouse=True)
def _reset_module_caches():
    """Every test starts with a clean file-sync cache + validation cache.

    The module-level dicts outlive individual tests; without a reset, a
    prior test's DB write can make a later test's `get_stored_token()`
    skip the file write because the cached blob JSON matches.
    """
    auth_flow._FILE_SYNC_CACHE["blob_json"] = None
    auth_flow._invalidate_validation_cache()
    yield
    auth_flow._FILE_SYNC_CACHE["blob_json"] = None
    auth_flow._invalidate_validation_cache()


@pytest.mark.django_db
def test_store_credentials_blob_persists_to_db_and_file(tmp_path, settings):
    settings.ACE_CLAUDE_HOME = str(tmp_path)

    token = auth_flow.store_credentials_blob(BLOB)

    from apps.common.models import SystemConfig
    blob_row = SystemConfig.objects.get(key="claude_credentials_blob")
    assert json.loads(blob_row.value) == BLOB
    token_row = SystemConfig.objects.get(key="claude_oauth_token")
    assert token_row.value == token
    assert token == BLOB["claudeAiOauth"]["accessToken"]

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
def test_get_stored_token_reads_blob_and_writes_file(tmp_path, settings, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    settings.ACE_CLAUDE_HOME = str(tmp_path)

    from apps.common.models import SystemConfig
    SystemConfig.objects.create(
        key="claude_credentials_blob", value=json.dumps(BLOB)
    )

    loaded = auth_flow.get_stored_token()
    assert loaded == (BLOB["claudeAiOauth"]["accessToken"], "global")
    assert (tmp_path / ".claude" / ".credentials.json").exists()


@pytest.mark.django_db
def test_get_stored_token_picks_up_updated_blob_across_calls(
    tmp_path, settings, monkeypatch
):
    """Simulates the multi-task case: task B sees a fresh DB blob written
    by task A and syncs the local file + returned token on the next call.
    """
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    settings.ACE_CLAUDE_HOME = str(tmp_path)

    from apps.common.models import SystemConfig

    first = dict(BLOB)
    first["claudeAiOauth"] = dict(BLOB["claudeAiOauth"], accessToken="sk-ant-oat01-" + "c" * 80)
    SystemConfig.objects.create(
        key="claude_credentials_blob", value=json.dumps(first)
    )
    assert auth_flow.get_stored_token() == (first["claudeAiOauth"]["accessToken"], "global")

    second = dict(BLOB)
    second["claudeAiOauth"] = dict(BLOB["claudeAiOauth"], accessToken="sk-ant-oat01-" + "d" * 80)
    SystemConfig.objects.filter(key="claude_credentials_blob").update(
        value=json.dumps(second)
    )
    assert auth_flow.get_stored_token() == (second["claudeAiOauth"]["accessToken"], "global")
    on_disk = json.loads((tmp_path / ".claude" / ".credentials.json").read_text())
    assert on_disk == second


@pytest.mark.django_db
def test_get_stored_token_falls_back_to_legacy_token_key(monkeypatch):
    """A deploy that predates blob migration still has just the token row."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    from apps.common.models import SystemConfig
    SystemConfig.objects.create(
        key="claude_oauth_token",
        value="sk-ant-oat01-legacy-longish-ish-token-longer-than-40",
    )
    assert auth_flow.get_stored_token() == (
        "sk-ant-oat01-legacy-longish-ish-token-longer-than-40",
        "global",
    )


@pytest.mark.django_db
def test_get_stored_token_returns_none_when_no_db_rows(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    assert auth_flow.get_stored_token() is None


@pytest.mark.django_db
def test_load_stored_token_returns_bare_string(tmp_path, settings, monkeypatch):
    """``load_stored_token`` is a thin str-only wrapper over the resolver,
    kept so older callers that expect a bare access token continue to work.
    """
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    settings.ACE_CLAUDE_HOME = str(tmp_path)

    from apps.common.models import SystemConfig
    SystemConfig.objects.create(
        key="claude_credentials_blob", value=json.dumps(BLOB)
    )

    assert auth_flow.load_stored_token() == BLOB["claudeAiOauth"]["accessToken"]


@pytest.mark.django_db
def test_load_stored_token_returns_none_when_no_rows(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    assert auth_flow.load_stored_token() is None


def test_token_looks_real_rejects_placeholders_and_shorts():
    assert not auth_flow.token_looks_real(None)
    assert not auth_flow.token_looks_real("")
    assert not auth_flow.token_looks_real("sk-ant-api03-notoauth")
    assert not auth_flow.token_looks_real("sk-ant-oat01-short")
    assert not auth_flow.token_looks_real("sk-ant-oat01-placeholder" + "x" * 30)
    assert auth_flow.token_looks_real("sk-ant-oat01-" + "a" * 80)


def test_cli_is_ready_is_alias_for_validate():
    assert auth_flow.cli_is_ready is auth_flow.validate_stored_token
