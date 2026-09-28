"""Tests for the sign-in admission gate (invite-only login).

Spec: docs/specs/2026-09-28-clone-and-release-design.md § A.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.auth.login_gate import admission_rule
from apps.auth.models import User
from apps.workspaces.models import Workspace, WorkspaceInvite, WorkspaceMembership

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _domain_list(settings):
    settings.ACE_ALLOWED_EMAIL_DOMAINS = ["dimagi.com"]


@pytest.fixture
def owner():
    return User.objects.create(email="owner@dimagi.com", display_name="Owner")


@pytest.fixture
def workspace(owner):
    return Workspace.objects.create(
        slug="spark", display_name="Spark", drive_root_folder_id="f-spark", created_by=owner
    )


def _invite(workspace, owner, email, **overrides):
    fields = {
        "workspace": workspace,
        "email": email,
        "role": "viewer",
        "invited_by": owner,
        "expires_at": timezone.now() + timedelta(days=7),
    }
    fields.update(overrides)
    return WorkspaceInvite.objects.create(**fields)


def test_admits_allowed_domain():
    assert admission_rule("jane@dimagi.com") == "domain"


def test_admits_everyone_when_domain_list_empty(settings):
    settings.ACE_ALLOWED_EMAIL_DOMAINS = []
    assert admission_rule("anyone@example.org") == "open"


def test_rejects_outsider_without_invite():
    assert admission_rule("anne@sparkmicrogrants.org") is None


def test_rejects_empty_email(workspace, owner):
    _invite(workspace, owner, "")
    assert admission_rule("") is None


def test_admits_pending_invite_case_insensitively(workspace, owner):
    _invite(workspace, owner, "Anne@SparkMicrogrants.org")
    assert admission_rule("anne@sparkmicrogrants.org") == "invite"


def test_rejects_expired_invite(workspace, owner):
    _invite(workspace, owner, "anne@sparkmicrogrants.org",
            expires_at=timezone.now() - timedelta(minutes=1))
    assert admission_rule("anne@sparkmicrogrants.org") is None


def test_rejects_revoked_invite(workspace, owner):
    _invite(workspace, owner, "anne@sparkmicrogrants.org", revoked_at=timezone.now())
    assert admission_rule("anne@sparkmicrogrants.org") is None


def test_admits_existing_member(workspace):
    anne = User.objects.create(email="anne@sparkmicrogrants.org", display_name="Anne")
    WorkspaceMembership.objects.create(workspace=workspace, user=anne, role="viewer")
    assert admission_rule("ANNE@sparkmicrogrants.org") == "membership"


def test_rejects_accepted_invite_after_membership_removed(workspace, owner):
    """Accepting uses the invite up; once the member is removed from every
    workspace, nothing admits them any more."""
    User.objects.create(email="anne@sparkmicrogrants.org", display_name="Anne")
    _invite(workspace, owner, "anne@sparkmicrogrants.org", accepted_at=timezone.now())
    assert admission_rule("anne@sparkmicrogrants.org") is None
