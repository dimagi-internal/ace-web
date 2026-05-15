from unittest.mock import patch

import pytest
from django.test import Client


@pytest.mark.django_db
def test_health_returns_ok_when_db_and_redis_pass():
    with patch("apps.common.api.get_health_status", return_value={
        "status": "ok",
        "healthy": True,
        "checks": {
            "database": {"ok": True, "error": None},
            "redis": {"ok": True, "error": None},
        },
    }):
        client = Client()
        response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == {"ok": True, "error": None}
    assert body["checks"]["redis"] == {"ok": True, "error": None}


@pytest.mark.django_db
def test_health_returns_503_when_redis_down():
    with patch("apps.common.api.get_health_status", return_value={
        "status": "unhealthy",
        "healthy": False,
        "checks": {
            "database": {"ok": True, "error": None},
            "redis": {"ok": False, "error": "ConnectionError"},
        },
    }):
        client = Client()
        response = client.get("/api/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["redis"] == {"ok": False, "error": "ConnectionError"}


@pytest.mark.django_db
def test_health_returns_503_when_db_down():
    with patch("apps.common.api.get_health_status", return_value={
        "status": "unhealthy",
        "healthy": False,
        "checks": {
            "database": {"ok": False, "error": "OperationalError"},
            "redis": {"ok": True, "error": None},
        },
    }):
        client = Client()
        response = client.get("/api/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["database"] == {"ok": False, "error": "OperationalError"}
    assert body["checks"]["redis"]["ok"] is True
