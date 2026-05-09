from unittest.mock import patch

import pytest
from django.test import Client


@pytest.mark.django_db
def test_health_returns_ok_when_db_and_redis_pass():
    with patch("apps.common.views._check_redis", return_value=(True, None)):
        client = Client()
        response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert body["data"]["status"] == "ok"
    assert body["data"]["checks"]["database"] == {"ok": True, "error": None}
    assert body["data"]["checks"]["redis"] == {"ok": True, "error": None}


@pytest.mark.django_db
def test_health_returns_503_when_redis_down():
    with patch("apps.common.views._check_redis", return_value=(False, "ConnectionError")):
        client = Client()
        response = client.get("/api/health")
    assert response.status_code == 503
    body = response.json()
    assert body["data"]["status"] == "unhealthy"
    assert body["data"]["checks"]["database"]["ok"] is True
    assert body["data"]["checks"]["redis"] == {"ok": False, "error": "ConnectionError"}


@pytest.mark.django_db
def test_health_returns_503_when_db_down():
    with (
        patch("apps.common.views._check_database", return_value=(False, "OperationalError")),
        patch("apps.common.views._check_redis", return_value=(True, None)),
    ):
        client = Client()
        response = client.get("/api/health")
    assert response.status_code == 503
    body = response.json()
    assert body["data"]["status"] == "unhealthy"
    assert body["data"]["checks"]["database"] == {"ok": False, "error": "OperationalError"}
    assert body["data"]["checks"]["redis"]["ok"] is True
