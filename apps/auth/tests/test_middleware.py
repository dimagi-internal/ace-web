import pytest
from django.test import Client, override_settings

from apps.auth.models import User


@pytest.mark.django_db
def test_health_endpoint_skips_auth():
    """Health check should not require auth even with IAP_REQUIRED=True."""
    with override_settings(IAP_REQUIRED=True):
        client = Client()
        response = client.get("/api/health")
        assert response.status_code == 200


@pytest.mark.django_db
def test_iap_required_blocks_unauthenticated():
    """When IAP_REQUIRED is True, requests without IAP headers get 401."""
    with override_settings(IAP_REQUIRED=True):
        client = Client()
        response = client.get("/admin/")
        # IAP middleware returns 401 before Django auth kicks in
        assert response.status_code == 401


@pytest.mark.django_db
def test_iap_creates_user_on_first_sight():
    """First request with IAP headers creates the User row."""
    assert not User.objects.filter(email="new@example.com").exists()
    with override_settings(IAP_REQUIRED=True):
        client = Client()
        client.get(
            "/admin/login/",
            HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL="accounts.google.com:new@example.com",
            HTTP_X_GOOG_AUTHENTICATED_USER_ID="accounts.google.com:abc123",
        )
        assert User.objects.filter(email="new@example.com").exists()
        user = User.objects.get(email="new@example.com")
        assert user.google_sub == "abc123"


@pytest.mark.django_db
def test_iap_dev_fake_email_when_not_required():
    """When IAP is not required, dev fake email is used."""
    with override_settings(IAP_REQUIRED=False, IAP_DEV_FAKE_EMAIL="dev@example.com"):
        client = Client()
        client.get("/admin/login/")
        assert User.objects.filter(email="dev@example.com").exists()
