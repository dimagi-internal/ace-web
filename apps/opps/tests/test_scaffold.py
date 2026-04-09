"""Sanity-check that the apps/opps module is registered and its URL include works."""
from django.apps import apps
from django.test import Client
from django.urls import reverse


def test_opps_app_is_registered():
    assert apps.is_installed("apps.opps")


def test_opps_health_endpoint_reverses():
    url = reverse("opps-health")
    assert url == "/api/opps/health"


def test_opps_health_endpoint_responds():
    client = Client()
    response = client.get("/api/opps/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"data": {"status": "ok", "module": "opps"}, "error": None}
