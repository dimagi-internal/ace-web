import pytest
from rest_framework.test import APIClient


@pytest.fixture
def client_authenticated_for():
    def _make(user):
        c = APIClient()
        c.force_authenticate(user=user)
        # Also create a real Django session so plain async Django views
        # (stream_assistant_message) see an authenticated request.user,
        # not just DRF-authenticated requests.
        c.force_login(user)
        return c
    return _make
