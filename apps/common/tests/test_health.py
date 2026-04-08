import pytest
from django.test import Client


@pytest.mark.django_db
def test_health_returns_ok():
    client = Client()
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "ok"
    assert body["error"] is None
