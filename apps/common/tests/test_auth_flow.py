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


# ── Persisted validation cache (issue #479) ─────────────────────


def _seed_global_blob(monkeypatch, tmp_path, settings):
    """Persist BLOB as the global credentials blob and clean env."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    settings.ACE_CLAUDE_HOME = str(tmp_path)
    from apps.common.models import SystemConfig

    SystemConfig.objects.update_or_create(
        key="claude_credentials_blob",
        defaults={"value": json.dumps(BLOB)},
    )


@pytest.mark.django_db
def test_persisted_cache_survives_process_restart(
    tmp_path, settings, monkeypatch
):
    """A second validate call after dropping the in-memory cache reads the
    persisted DB row and does NOT spawn ``claude -p``.

    This is the actual fix for the cold-start lie: a freshly-rolled ECS
    task starts with an empty ``_validation_cache`` dict but finds the
    recent positive result in SystemConfig and returns it immediately.
    """
    _seed_global_blob(monkeypatch, tmp_path, settings)
    cli_calls: list[None] = []

    def fake_check(blob_json=None, on_refresh=None):
        cli_calls.append(None)
        return True

    monkeypatch.setattr(auth_flow, "_check_token_via_cli", fake_check)
    # First call writes both tiers.
    assert auth_flow.validate_stored_token() is True
    assert len(cli_calls) == 1

    # Drop ONLY the in-memory tier (simulates process restart on deploy).
    auth_flow._validation_cache["checked_at"] = 0.0
    auth_flow._validation_cache["token"] = ""
    auth_flow._validation_cache["source"] = ""

    # Persistent cache should serve the result without re-spawning.
    assert auth_flow.validate_stored_token() is True
    assert len(cli_calls) == 1, (
        "persisted cache miss — subprocess was spawned again on restart"
    )


@pytest.mark.django_db
def test_persisted_cache_invalidates_on_token_rotation(
    tmp_path, settings, monkeypatch
):
    """Rotating the token (different hash) bypasses the persisted cache
    even if the in-memory cache is empty.
    """
    _seed_global_blob(monkeypatch, tmp_path, settings)
    cli_calls: list[None] = []

    def fake_check(blob_json=None, on_refresh=None):
        cli_calls.append(None)
        return True

    monkeypatch.setattr(auth_flow, "_check_token_via_cli", fake_check)
    assert auth_flow.validate_stored_token() is True
    assert len(cli_calls) == 1

    # Simulate process restart (drop in-memory) then token rotation in DB
    # without going through store_credentials_blob (which would clear the
    # persisted cache itself — we want to exercise hash-based invalidation).
    auth_flow._validation_cache["checked_at"] = 0.0
    auth_flow._validation_cache["token"] = ""
    auth_flow._validation_cache["source"] = ""

    rotated = {
        "claudeAiOauth": dict(
            BLOB["claudeAiOauth"], accessToken="sk-ant-oat01-" + "z" * 80
        )
    }
    from apps.common.models import SystemConfig

    SystemConfig.objects.filter(key="claude_credentials_blob").update(
        value=json.dumps(rotated)
    )

    assert auth_flow.validate_stored_token() is True
    assert len(cli_calls) == 2, (
        "rotated token returned stale cached result — hash mismatch did "
        "not invalidate"
    )


@pytest.mark.django_db
def test_persisted_cache_invalidates_on_source_change(
    tmp_path, settings, monkeypatch, django_user_model
):
    """A row cached under source=global must NOT satisfy a source=user
    lookup. The cache key includes source for exactly this reason.
    """
    _seed_global_blob(monkeypatch, tmp_path, settings)
    cli_calls: list[str] = []

    def fake_check(blob_json=None, on_refresh=None):
        cli_calls.append("call")
        return True

    monkeypatch.setattr(auth_flow, "_check_token_via_cli", fake_check)
    # Cache a positive result under source=global.
    assert auth_flow.validate_stored_token() is True
    assert len(cli_calls) == 1

    # Drop in-memory tier.
    auth_flow._validation_cache["checked_at"] = 0.0
    auth_flow._validation_cache["token"] = ""
    auth_flow._validation_cache["source"] = ""

    # Create a UserCredential with a DIFFERENT token so the resolver picks
    # source="user" — same store, but the persisted row's source field
    # won't match.
    user = django_user_model.objects.create_user(
        email="alice@example.com", display_name="Alice"
    )
    user_blob = {
        "claudeAiOauth": dict(
            BLOB["claudeAiOauth"], accessToken="sk-ant-oat01-" + "u" * 80
        )
    }
    auth_flow.store_user_credentials_blob(user, user_blob)
    # store_user_credentials_blob clears the cache; reset call counter so
    # we only count what the next validate spawns.
    cli_calls.clear()

    assert auth_flow.validate_stored_token(user=user) is True
    assert len(cli_calls) == 1, (
        "source change (global → user) served a stale cached result"
    )


@pytest.mark.django_db
def test_persisted_cache_written_for_both_pass_and_fail(
    tmp_path, settings, monkeypatch
):
    """The persistent row records negative results too — otherwise a
    failing token would always pay the subprocess cost on every restart.
    """
    _seed_global_blob(monkeypatch, tmp_path, settings)
    cli_calls: list[bool] = []

    def fake_check(blob_json=None, on_refresh=None):
        cli_calls.append(False)
        return False

    monkeypatch.setattr(auth_flow, "_check_token_via_cli", fake_check)
    assert auth_flow.validate_stored_token() is False

    from apps.common.models import SystemConfig

    row = SystemConfig.objects.get(key="cli_validation_state")
    state = json.loads(row.value)
    assert state["valid"] is False
    assert "token_hash" in state and len(state["token_hash"]) == 64


@pytest.mark.django_db
def test_store_credentials_clears_persisted_cache(
    tmp_path, settings, monkeypatch
):
    """A fresh upload must invalidate the persisted row so the next status
    poll re-runs the live check against the new blob.
    """
    settings.ACE_CLAUDE_HOME = str(tmp_path)
    monkeypatch.setattr(
        auth_flow, "_check_token_via_cli", lambda blob_json=None, on_refresh=None: True
    )
    # Seed a persisted row.
    auth_flow.store_credentials_blob(BLOB)
    assert auth_flow.validate_stored_token() is True

    from apps.common.models import SystemConfig

    assert SystemConfig.objects.filter(key="cli_validation_state").exists()
    # Re-upload (e.g. operator runs scripts/ace_cli_login.py).
    auth_flow.store_credentials_blob(BLOB)
    assert not SystemConfig.objects.filter(key="cli_validation_state").exists()


@pytest.mark.django_db
def test_in_memory_cache_promoted_from_persisted_tier(
    tmp_path, settings, monkeypatch
):
    """After serving from the persisted tier, the in-memory cache should
    be populated so subsequent hot-path calls in the same process don't
    re-hit the DB. (Verifies the TTL math doesn't break: hot path within
    _POSITIVE_CACHE_TTL must serve from memory.)
    """
    _seed_global_blob(monkeypatch, tmp_path, settings)

    def fake_check(blob_json=None, on_refresh=None):
        return True

    monkeypatch.setattr(auth_flow, "_check_token_via_cli", fake_check)
    auth_flow.validate_stored_token()
    # Drop in-memory, then call again — should be served from persisted.
    auth_flow._validation_cache["checked_at"] = 0.0
    auth_flow._validation_cache["token"] = ""
    auth_flow._validation_cache["source"] = ""
    auth_flow.validate_stored_token()

    # In-memory should now match the resolved token.
    expected_token = BLOB["claudeAiOauth"]["accessToken"]
    assert auth_flow._validation_cache["token"] == expected_token
    assert auth_flow._validation_cache["valid"] is True


@pytest.mark.django_db
def test_persisted_cache_respects_long_ttl(tmp_path, settings, monkeypatch):
    """A row older than ``_PERSISTED_CACHE_TTL`` must be treated as a miss
    so a long-running deploy outage still re-runs the live check.
    """
    _seed_global_blob(monkeypatch, tmp_path, settings)
    cli_calls: list[bool] = []

    def fake_check(blob_json=None, on_refresh=None):
        cli_calls.append(True)
        return True

    monkeypatch.setattr(auth_flow, "_check_token_via_cli", fake_check)
    auth_flow.validate_stored_token()
    assert len(cli_calls) == 1

    # Backdate the persisted row to TTL+1s.
    from apps.common.models import SystemConfig

    row = SystemConfig.objects.get(key="cli_validation_state")
    state = json.loads(row.value)
    state["checked_at"] -= auth_flow._PERSISTED_CACHE_TTL + 1
    row.value = json.dumps(state)
    row.save()

    # Drop in-memory tier; next call must spawn the subprocess again.
    auth_flow._validation_cache["checked_at"] = 0.0
    auth_flow._validation_cache["token"] = ""
    auth_flow._validation_cache["source"] = ""
    auth_flow.validate_stored_token()
    assert len(cli_calls) == 2
