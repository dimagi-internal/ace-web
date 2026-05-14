import pytest
from django.test import Client


@pytest.fixture
def client_authenticated_for():
    def _make(user):
        c = Client()
        c.force_login(user)
        return c
    return _make
