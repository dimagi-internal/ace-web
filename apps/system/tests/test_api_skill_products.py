"""Contract tests for GET /api/system/skill-products."""
import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def auth_client(db, client):
    user = User.objects.create_user(email="sptest@example.com")
    client.force_login(user)
    return client


@pytest.fixture
def anon_client(db, client):
    return client


@pytest.mark.django_db
def test_skill_products_endpoint_returns_map(auth_client, monkeypatch):
    fake_map = {
        "idea-to-pdd": ["1-design/idea-to-pdd.md"],
        "pdd-to-work-order": ["1-design/pdd-to-work-order.gdoc"],
    }
    monkeypatch.setattr(
        "apps.system.api.get_skill_products_map",
        lambda: fake_map,
    )
    resp = auth_client.get("/api/system/skill-products")
    assert resp.status_code == 200
    assert resp.json() == fake_map


@pytest.mark.django_db
def test_skill_products_endpoint_requires_auth(anon_client):
    resp = anon_client.get("/api/system/skill-products")
    assert resp.status_code in (401, 403, 302)
