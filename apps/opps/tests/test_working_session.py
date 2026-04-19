import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.models import OppWorkspace
from apps.sessions.models import Session, SessionParticipant


@pytest.fixture
def authed_client(db):
    User.objects.create(email="jon@dimagi.com", display_name="Jon")
    c = Client()
    c.force_login(User.objects.get(email="jon@dimagi.com"))
    return c


def test_returns_existing_working_session(authed_client, db):
    user = User.objects.get(email="jon@dimagi.com")
    session = Session.objects.create(
        owner=user, opp_slug="malaria-pilot", backend_kind="cli",
        status="active", source="web", title="x",
    )
    OppWorkspace.objects.create(
        slug="malaria-pilot", display_name="Malaria",
        working_session=session, created_by=user,
    )
    resp = authed_client.get("/api/opps/malaria-pilot/working-session")
    assert resp.status_code == 200
    assert resp.json()["data"]["working_session_slug"] == session.slug


def test_creates_session_when_workspace_has_none(authed_client, db):
    user = User.objects.get(email="jon@dimagi.com")
    OppWorkspace.objects.create(
        slug="malaria-pilot", display_name="Malaria", created_by=user,
    )
    resp = authed_client.get("/api/opps/malaria-pilot/working-session")
    assert resp.status_code == 200
    slug = resp.json()["data"]["working_session_slug"]
    session = Session.objects.get(slug=slug)
    assert session.opp_slug == "malaria-pilot"
    assert session.status == "active"

    # Workspace should now be pointing at the new session
    workspace = OppWorkspace.objects.get(slug="malaria-pilot")
    assert workspace.working_session_id == session.pk


def test_creates_workspace_and_session_for_drive_only_opp(authed_client, db):
    """No OppWorkspace row exists (e.g. Drive-only legacy opp)."""
    resp = authed_client.get("/api/opps/legacy-opp/working-session")
    assert resp.status_code == 200
    slug = resp.json()["data"]["working_session_slug"]
    assert Session.objects.get(slug=slug).opp_slug == "legacy-opp"
    assert OppWorkspace.objects.filter(slug="legacy-opp").exists()


def test_unauthenticated_returns_401(db):
    c = Client()
    resp = c.get("/api/opps/foo/working-session")
    assert resp.status_code in (401, 403)


def test_working_session_is_owner_participant(authed_client, db):
    """Regression: the working session returned by this endpoint must be
    readable by its own owner via GET /api/sessions/<slug>. Previously the
    session was created without a SessionParticipant row, so the owner got
    404 on their own working session — which surfaced as the chat pane
    spinning "Loading chat…" forever on the Workbench."""
    resp = authed_client.get("/api/opps/malaria-pilot/working-session")
    assert resp.status_code == 200
    session_slug = resp.json()["data"]["working_session_slug"]

    # The session row must carry an "owner" participant so downstream
    # participant-scoped reads succeed.
    session = Session.objects.get(slug=session_slug)
    user = User.objects.get(email="jon@dimagi.com")
    assert SessionParticipant.objects.filter(
        session=session, user=user, role="owner",
    ).exists()

    # And the participant-scoped detail endpoint must return 200 for the owner.
    detail = authed_client.get(f"/api/sessions/{session_slug}")
    assert detail.status_code == 200
