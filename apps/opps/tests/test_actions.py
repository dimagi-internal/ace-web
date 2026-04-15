import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.models import OppWorkspace
from apps.sessions.models import Session


@pytest.fixture
def opp(db):
    user = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    session = Session.objects.create(
        owner=user, opp_slug="malaria-pilot", opp_run_id="run-001",
        backend_kind="cli", status="active", source="web",
        title="Malaria — working",
    )
    workspace = OppWorkspace.objects.create(
        slug="malaria-pilot", display_name="Malaria",
        working_session=session, created_by=user,
    )
    return workspace, user


def test_run_action_injects_chat_message(opp, db):
    workspace, user = opp
    c = Client()
    c.force_login(user)
    resp = c.post(
        "/api/opps/malaria-pilot/runs/run-001/actions/run",
        data={"skill": "idea-to-pdd"}, content_type="application/json",
    )
    assert resp.status_code == 200
    msgs = list(workspace.working_session.messages.order_by("turn_index"))
    assert any("idea-to-pdd" in m.plaintext for m in msgs)
    assert any("run" in m.plaintext.lower() for m in msgs)


def test_approve_action(opp, db):
    workspace, user = opp
    c = Client()
    c.force_login(user)
    resp = c.post(
        "/api/opps/malaria-pilot/runs/run-001/actions/approve",
        data={"skill": "idea-to-pdd"}, content_type="application/json",
    )
    assert resp.status_code == 200
    latest = workspace.working_session.messages.order_by("-turn_index").first()
    assert "approve" in latest.plaintext.lower()
    assert "idea-to-pdd" in latest.plaintext


def test_reject_action_requires_reason(opp, db):
    workspace, user = opp
    c = Client()
    c.force_login(user)
    resp = c.post(
        "/api/opps/malaria-pilot/runs/run-001/actions/reject",
        data={"skill": "idea-to-pdd"}, content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "reason-required"
    resp = c.post(
        "/api/opps/malaria-pilot/runs/run-001/actions/reject",
        data={"skill": "idea-to-pdd", "reason": "needs more detail"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    latest = workspace.working_session.messages.order_by("-turn_index").first()
    assert "reject" in latest.plaintext.lower()
    assert "needs more detail" in latest.plaintext


def test_unknown_action_returns_400(opp, db):
    workspace, user = opp
    c = Client()
    c.force_login(user)
    resp = c.post(
        "/api/opps/malaria-pilot/runs/run-001/actions/nonsense",
        data={"skill": "idea-to-pdd"}, content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unknown-action"


def test_no_workspace_returns_404(db):
    user = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    c = Client()
    c.force_login(user)
    resp = c.post(
        "/api/opps/no-such-opp/runs/run-001/actions/run",
        data={"skill": "idea-to-pdd"}, content_type="application/json",
    )
    assert resp.status_code == 404


def test_no_active_session_returns_409(db):
    user = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    OppWorkspace.objects.create(
        slug="no-session-opp", display_name="X", created_by=user,
    )
    c = Client()
    c.force_login(user)
    resp = c.post(
        "/api/opps/no-session-opp/runs/run-001/actions/run",
        data={"skill": "idea-to-pdd"}, content_type="application/json",
    )
    assert resp.status_code == 409
