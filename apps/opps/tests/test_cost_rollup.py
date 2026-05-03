# apps/opps/tests/test_cost_rollup.py
import pytest
from rest_framework.test import APIClient

from apps.sessions.models import Session
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="rollup@example.com", display_name="rollup"
    )


@pytest.fixture
def workspace(user):
    from apps.workspaces.models import Workspace, WorkspaceMembership
    ws = Workspace.objects.create(
        slug="ws1", display_name="WS 1", drive_root_folder_id="drv1", created_by=user,
    )
    WorkspaceMembership.objects.create(workspace=ws, user=user, role="owner")
    return ws


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _bd(input_tokens, cost):
    return {
        "schema_version": 1,
        "totals": {"input_tokens": input_tokens, "output_tokens": 0,
                   "cache_creation_tokens": 0, "cache_read_tokens": 0,
                   "estimated_cost_usd": cost, "cache_hit_ratio": 0.0,
                   "cost_is_partial": False, "wall_time_seconds": 60},
        "phases": [{
            "phase_name": "design-review", "phase_display": "Phase 1",
            "phase_ordinal": 1, "wall_time_seconds": 60,
            "tokens": {"input_tokens": input_tokens, "output_tokens": 0,
                       "cache_creation_tokens": 0, "cache_read_tokens": 0},
            "estimated_cost_usd": cost, "cost_is_partial": False, "skills": [],
        }],
    }


def test_cost_rollup_sums_across_linked_sessions(client, user, workspace):
    Session.create_with_owner(owner=user, workspace=workspace,
                              opp_slug="opp1", cost_breakdown=_bd(100, 0.10))
    Session.create_with_owner(owner=user, workspace=workspace,
                              opp_slug="opp1", cost_breakdown=_bd(250, 0.25))
    resp = client.get("/api/opps/opp1/cost-rollup",
                      headers={"X-ACE-Workspace": workspace.slug})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["totals"]["input_tokens"] == 350
    assert round(body["totals"]["estimated_cost_usd"], 4) == 0.35
    assert body["session_count"] == 2
    assert body["sessions_without_breakdown"] == 0
    phase = body["phases"][0]
    assert phase["phase_name"] == "design-review"
    assert phase["tokens"]["input_tokens"] == 350


def test_cost_rollup_counts_sessions_without_breakdown(client, user, workspace):
    Session.create_with_owner(owner=user, workspace=workspace,
                              opp_slug="opp2", cost_breakdown=_bd(100, 0.10))
    Session.create_with_owner(owner=user, workspace=workspace,
                              opp_slug="opp2", cost_breakdown={})
    resp = client.get("/api/opps/opp2/cost-rollup",
                      headers={"X-ACE-Workspace": workspace.slug})
    body = resp.json()["data"]
    assert body["session_count"] == 2
    assert body["sessions_without_breakdown"] == 1
    assert body["totals"]["input_tokens"] == 100  # only the populated one counts


def test_cost_rollup_empty_when_no_linked_sessions(client, workspace):
    resp = client.get("/api/opps/missing-opp/cost-rollup",
                      headers={"X-ACE-Workspace": workspace.slug})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["session_count"] == 0
    assert body["phases"] == []


def test_cost_rollup_workspace_scoped(client, user, workspace, django_user_model):
    """Sessions in other workspaces never appear in the rollup."""
    other_user = django_user_model.objects.create_user(
        email="o@example.com", display_name="o"
    )
    other_ws = Workspace.objects.create(
        slug="ws2", display_name="WS 2", drive_root_folder_id="drv2", created_by=other_user,
    )
    Session.create_with_owner(owner=other_user, workspace=other_ws,
                              opp_slug="opp1", cost_breakdown=_bd(999, 9.99))
    resp = client.get("/api/opps/opp1/cost-rollup",
                      headers={"X-ACE-Workspace": workspace.slug})
    body = resp.json()["data"]
    # Workspace ws1 has no opp1 sessions; the ws2 session must be invisible.
    assert body["session_count"] == 0
    assert body["totals"]["input_tokens"] == 0
