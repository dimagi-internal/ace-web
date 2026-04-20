import pytest
from django.db import IntegrityError

from apps.auth.models import User
from apps.opps.models import OppWorkspace


@pytest.fixture
def user(db):
    return User.objects.create(email="jon@dimagi.com", display_name="Jon")


def test_create_opp_workspace(user, db):
    w = OppWorkspace.objects.create(
        slug="malaria-pilot", display_name="Malaria Pilot", created_by=user,
    )
    assert w.slug == "malaria-pilot"
    assert w.working_session is None
    assert w.created_at is not None


def test_slug_uniqueness(user, db):
    OppWorkspace.objects.create(
        slug="malaria-pilot", display_name="A", created_by=user,
    )
    with pytest.raises(IntegrityError):
        OppWorkspace.objects.create(
            slug="malaria-pilot", display_name="B", created_by=user,
        )


def test_opp_workspace_tags_default_empty_and_settable(user, db):
    """Tags are a free-form list for grouping related opps (e.g. iterations
    of the same idea). See docs/plans/2026-04-20-drop-multi-run-simplify.md."""
    w = OppWorkspace.objects.create(
        slug="tagged-opp", display_name="Tagged Opp", created_by=user,
    )
    assert w.tags == []
    w.tags = ["turmeric", "smoke-test"]
    w.save()
    w.refresh_from_db()
    assert w.tags == ["turmeric", "smoke-test"]
