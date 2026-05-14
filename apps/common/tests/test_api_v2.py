"""Contract tests for apps.common.api_v2."""
import pytest
from django.contrib.auth import get_user_model

User = get_user_model()

_FAKE_HEALTH_OK = {
    "status": "ok",
    "healthy": True,
    "checks": {
        "database": {"ok": True, "error": None},
        "redis": {"ok": True, "error": None},
    },
}

_FAKE_HEALTH_UNHEALTHY = {
    "status": "unhealthy",
    "healthy": False,
    "checks": {
        "database": {"ok": False, "error": "OperationalError"},
        "redis": {"ok": True, "error": None},
    },
}


@pytest.fixture
def anon_client(db, client):
    return client


# ---------------------------------------------------------------------------
# GET /health — public (no auth)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_health_200_when_healthy(anon_client, monkeypatch):
    monkeypatch.setattr(
        "apps.common.api_v2.get_health_status",
        lambda: _FAKE_HEALTH_OK,
    )
    resp = anon_client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["healthy"] is True
    assert body["checks"]["database"]["ok"] is True


@pytest.mark.django_db
def test_health_503_when_unhealthy(anon_client, monkeypatch):
    monkeypatch.setattr(
        "apps.common.api_v2.get_health_status",
        lambda: _FAKE_HEALTH_UNHEALTHY,
    )
    resp = anon_client.get("/api/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["database"]["ok"] is False


@pytest.mark.django_db
def test_health_accessible_without_auth(anon_client, monkeypatch):
    """Health check must be public — no session required."""
    monkeypatch.setattr(
        "apps.common.api_v2.get_health_status",
        lambda: _FAKE_HEALTH_OK,
    )
    # anon client — no login
    resp = anon_client.get("/api/health")
    assert resp.status_code == 200
