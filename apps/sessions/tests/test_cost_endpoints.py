# apps/sessions/tests/test_cost_endpoints.py
import pytest
from rest_framework.test import APIClient

from apps.sessions.models import Session

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="cost@example.com", display_name="cost"
    )


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(
        email="other@example.com", display_name="other"
    )


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def populated_session(user):
    return Session.create_with_owner(
        owner=user,
        title="t",
        cost_breakdown={
            "schema_version": 1,
            "computed_at": "2026-05-03T18:00:00Z",
            "totals": {"input_tokens": 100, "output_tokens": 50,
                       "cache_creation_tokens": 0, "cache_read_tokens": 1000,
                       "estimated_cost_usd": 0.01, "cache_hit_ratio": 0.91,
                       "cost_is_partial": False, "wall_time_seconds": 60},
            "phases": [],
        },
    )


@pytest.fixture
def empty_session(user):
    return Session.create_with_owner(owner=user, title="empty")


def test_get_cost_breakdown_returns_payload(client, populated_session):
    resp = client.get(f"/api/sessions/{populated_session.slug}/cost-breakdown")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["schema_version"] == 1
    assert body["totals"]["input_tokens"] == 100


def test_get_cost_breakdown_empty_returns_zeroed_payload(client, empty_session):
    """Empty breakdown returns schema_version=0 + null totals so the UI can
    render the 'no cost data' state without a 404 round-trip."""
    resp = client.get(f"/api/sessions/{empty_session.slug}/cost-breakdown")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["schema_version"] == 0
    assert body["totals"] is None
    assert body["phases"] == []


def test_get_cost_breakdown_unknown_session_returns_404(client):
    resp = client.get("/api/sessions/no-such-session/cost-breakdown")
    assert resp.status_code == 404


def test_get_cost_breakdown_other_users_session_returns_404(other_user):
    s = Session.create_with_owner(owner=other_user, title="other")
    c = APIClient()
    # Authenticate as a different user.
    from apps.auth.models import User
    me = User.objects.create_user(email="me@example.com", display_name="me")
    c.force_authenticate(user=me)
    resp = c.get(f"/api/sessions/{s.slug}/cost-breakdown")
    # Workspace-scoped: non-member gets 404 (not 403) per the codebase convention.
    assert resp.status_code == 404
