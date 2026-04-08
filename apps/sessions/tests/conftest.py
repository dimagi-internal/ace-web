import pytest
from rest_framework.test import APIClient


@pytest.fixture
def client_authenticated_for():
    """Return a factory that creates an APIClient authenticating as the given user.

    For DRF views (session_collection, session_detail, send_message), force_authenticate
    is sufficient.

    For plain Django async views (stream_assistant_message), IAPHeaderAuthMiddleware
    sets request.user from the IAP email header and ignores DRF force_authenticate.
    This factory therefore also injects the matching IAP header so the middleware
    resolves the correct user on both sync DRF views and the async streaming view.
    """
    def _make(user):
        c = APIClient()
        c.force_authenticate(user=user)
        # Inject IAP email header so IAPHeaderAuthMiddleware resolves this user.
        # The middleware reads HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL from META and
        # strips an "accounts.google.com:" prefix.
        c.defaults["HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL"] = f"accounts.google.com:{user.email}"
        c.defaults["HTTP_X_GOOG_AUTHENTICATED_USER_ID"] = f"accounts.google.com:{user.pk}"
        return c
    return _make
