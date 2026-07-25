"""Tests for apps.system.health — Nova auth + op-inject health (ace-web#636)."""
import pytest

from apps.common import nova_auth_flow as _nova_auth_flow
from apps.system import health

# Bound at import time so the autouse _no_pat patch can't shadow it in the
# get_pat_key parsing tests below.
_real_get_pat_key = _nova_auth_flow.get_pat_key


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    health._cache.clear()
    yield
    health._cache.clear()


@pytest.fixture(autouse=True)
def _no_pat(monkeypatch):
    """Default: no PAT override present; individual tests re-patch."""
    monkeypatch.setattr("apps.common.nova_auth_flow.get_pat_key", lambda: None)


# ---------------------------------------------------------------------------
# nova_auth_health
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_nova_auth_health_no_blob_no_pat(monkeypatch):
    monkeypatch.setattr("apps.common.nova_auth_flow.get_blob", lambda: None)
    out = health.nova_auth_health()
    assert out == {
        "connected": False,
        "valid": False,
        "expires_at": None,
        "last_refresh_error": None,
        "pat_present": False,
        "pat_valid": False,
        "usable": False,
    }


@pytest.mark.django_db
def test_nova_auth_health_epoch_expiry_normalised(monkeypatch):
    monkeypatch.setattr(
        "apps.common.nova_auth_flow.get_blob", lambda: {"expires_at": 1750000000}
    )
    monkeypatch.setattr("apps.common.nova_auth_flow.validate_token", lambda: True)
    out = health.nova_auth_health()
    assert out["connected"] is True
    assert out["valid"] is True
    assert out["usable"] is True
    assert out["expires_at"].startswith("2025-06-15")


@pytest.mark.django_db
def test_nova_auth_health_pat_only_is_usable(monkeypatch):
    """Dead blob + healthy PAT override → usable (the labs 2026-07-24 state)."""
    monkeypatch.setattr("apps.common.nova_auth_flow.get_blob", lambda: None)
    monkeypatch.setattr("apps.common.nova_auth_flow.get_pat_key", lambda: "nova-pat")
    monkeypatch.setattr(
        "apps.common.nova_auth_flow._probe_bearer", lambda token: token == "nova-pat"
    )
    out = health.nova_auth_health()
    assert out["connected"] is False
    assert out["pat_present"] is True
    assert out["pat_valid"] is True
    assert out["usable"] is True


@pytest.mark.django_db
def test_nova_auth_health_probe_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "apps.common.nova_auth_flow.get_blob",
        lambda: {"expires_at": "2026-01-01T00:00:00+00:00"},
    )
    monkeypatch.setattr(
        "apps.common.nova_auth_flow.validate_token",
        lambda: calls.append(1) is None and False,
    )
    assert health.nova_auth_health()["valid"] is False
    assert health.nova_auth_health()["valid"] is False
    assert len(calls) == 1  # second read served from the short TTL cache


@pytest.mark.django_db
def test_nova_auth_health_surfaces_last_refresh_failure(monkeypatch):
    from django.core.cache import cache

    from apps.common import nova_auth_flow

    cache.set(nova_auth_flow.LAST_REFRESH_FAILURE_KEY, "2026-07-24T00:00:00Z: boom", None)
    try:
        monkeypatch.setattr("apps.common.nova_auth_flow.get_blob", lambda: None)
        out = health.nova_auth_health()
        assert out["last_refresh_error"] == "2026-07-24T00:00:00Z: boom"
    finally:
        cache.delete(nova_auth_flow.LAST_REFRESH_FAILURE_KEY)


# ---------------------------------------------------------------------------
# nova_auth_flow.get_pat_key / validate_any_token
# ---------------------------------------------------------------------------


def test_get_pat_key_reads_rendered_env(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text('OTHER=1\nNOVA_API_KEY="nova-pat-123"\n')
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    assert _real_get_pat_key() == "nova-pat-123"


def test_get_pat_key_rejects_unresolved_op_ref(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("NOVA_API_KEY=op://AI-Agents/nova/key\n")
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    assert _real_get_pat_key() is None


def test_get_pat_key_none_when_env_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "absent"))
    assert _real_get_pat_key() is None


def test_validate_any_token_pat_short_circuits(monkeypatch):
    from apps.common import nova_auth_flow

    monkeypatch.setattr("apps.common.nova_auth_flow.get_pat_key", lambda: "pat")
    monkeypatch.setattr("apps.common.nova_auth_flow._probe_bearer", lambda t: True)
    monkeypatch.setattr(
        "apps.common.nova_auth_flow.validate_token",
        lambda: (_ for _ in ()).throw(AssertionError("blob path must not be hit")),
    )
    assert nova_auth_flow.validate_any_token() is True


def test_validate_any_token_falls_back_to_blob(monkeypatch):
    from apps.common import nova_auth_flow

    monkeypatch.setattr("apps.common.nova_auth_flow.get_pat_key", lambda: None)
    monkeypatch.setattr("apps.common.nova_auth_flow.validate_token", lambda: True)
    assert nova_auth_flow.validate_any_token() is True


# ---------------------------------------------------------------------------
# env_inject_health
# ---------------------------------------------------------------------------


def test_env_inject_unknown_when_status_file_missing(settings, tmp_path):
    settings.ACE_OP_INJECT_STATUS_PATH = str(tmp_path / "absent")
    assert health.env_inject_health() == {"status": "unknown", "error": None}


def test_env_inject_ok(settings, tmp_path):
    p = tmp_path / "op-inject.status"
    p.write_text("ok\n")
    settings.ACE_OP_INJECT_STATUS_PATH = str(p)
    assert health.env_inject_health() == {"status": "ok", "error": None}


def test_env_inject_failed_carries_stderr_excerpt(settings, tmp_path):
    p = tmp_path / "op-inject.status"
    p.write_text("failed\n[ERROR] item 'X' does not have a field 'y'\n")
    settings.ACE_OP_INJECT_STATUS_PATH = str(p)
    out = health.env_inject_health()
    assert out["status"] == "failed"
    assert "[ERROR]" in out["error"]


def test_env_inject_skipped_has_no_error(settings, tmp_path):
    p = tmp_path / "op-inject.status"
    p.write_text("skipped\nOP_SERVICE_ACCOUNT_TOKEN not set\n")
    settings.ACE_OP_INJECT_STATUS_PATH = str(p)
    assert health.env_inject_health() == {"status": "skipped", "error": None}


# ---------------------------------------------------------------------------
# get_version_info composition
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_version_info_includes_health_blocks(monkeypatch):
    from apps.system import api as system_api
    from apps.system.schemas import VersionOut

    monkeypatch.setattr(
        "apps.system.version.check_version",
        lambda p: {
            "plugin_found": True,
            "plugin_version": "1.0",
            "remote_version": "1.0",
            "update_available": False,
            "plugin_path": "/app/vendor/ace",
        },
    )
    monkeypatch.setattr(
        "apps.system.health.nova_auth_health",
        lambda: {
            "connected": True,
            "valid": False,
            "expires_at": "2026-05-13T20:02:42+00:00",
            "last_refresh_error": None,
            "pat_present": True,
            "pat_valid": True,
            "usable": True,
        },
    )
    monkeypatch.setattr(
        "apps.system.health.env_inject_health",
        lambda: {"status": "failed", "error": "boom"},
    )
    data = system_api.get_version_info()
    assert data["nova_auth"]["usable"] is True
    assert data["env_inject"]["status"] == "failed"
    VersionOut.model_validate(data)
