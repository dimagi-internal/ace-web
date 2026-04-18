"""Tests for the opp pointer fields added to the Session model."""
import pytest

from apps.auth.models import User
from apps.sessions.models import Session


@pytest.fixture
def user(db):
    return User.objects.create(email="jon@dimagi.com", display_name="Jon")


@pytest.mark.django_db
def test_session_opp_pointer_defaults(user):
    session = Session.objects.create(owner=user, title="Test")
    assert session.opp_slug == ""
    assert session.opp_run_id == ""
    assert session.opp_step_skill == ""


@pytest.mark.django_db
def test_session_can_set_opp_pointers(user):
    session = Session.objects.create(
        owner=user,
        title="Discuss app-deploy",
        opp_slug="malaria-pilot",
        opp_run_id="2026-04-06-002",
        opp_step_skill="app-deploy",
    )
    session.refresh_from_db()
    assert session.opp_slug == "malaria-pilot"
    assert session.opp_run_id == "2026-04-06-002"
    assert session.opp_step_skill == "app-deploy"


@pytest.mark.django_db
def test_session_filter_by_opp_pointers(user):
    Session.objects.create(
        owner=user, title="a", opp_slug="malaria-pilot",
        opp_run_id="r1", opp_step_skill="app-deploy",
    )
    Session.objects.create(
        owner=user, title="b", opp_slug="malaria-pilot",
        opp_run_id="r1", opp_step_skill="idea-to-pdd",
    )
    Session.objects.create(
        owner=user, title="c", opp_slug="nutrition", opp_run_id="r1",
        opp_step_skill="app-deploy",
    )

    matches = Session.objects.filter(
        opp_slug="malaria-pilot", opp_run_id="r1", opp_step_skill="app-deploy"
    )
    assert matches.count() == 1
    assert matches.first().title == "a"
