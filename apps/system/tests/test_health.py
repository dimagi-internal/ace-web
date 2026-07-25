"""Tests for apps.system.health — Nova auth + op-inject health (ace-web#636)."""
import pytest

from apps.system import health


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    health._cache.clear()
    yield
    health._cache.clear()


# ---------------------------------------------------------------------------
# nova_auth_health
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_nova_auth_health_no_blob(monkeypatch):
    monkeypatch.setattr("apps.common.nova_auth_flow.get_blob", lambda: None)
    out = health.nova_auth_health()
    assert out == {
        "connected": False,
        "valid": False,
        "expires_at": None,
        "last_refresh_error": None,
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
    assert out["expires_at"].startswith("2025-06-15")


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
        },
    )
    monkeypatch.setattr(
        "apps.system.health.env_inject_health",
        lambda: {"status": "failed", "error": "boom"},
    )
    data = system_api.get_version_info()
    assert data["nova_auth"]["valid"] is False
    assert data["env_inject"]["status"] == "failed"
    VersionOut.model_validate(data)
