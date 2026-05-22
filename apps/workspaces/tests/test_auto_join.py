"""Tests for apps.workspaces.auto_join."""

import pytest
from django.contrib.auth import get_user_model

from apps.workspaces.auto_join import ensure_auto_join_memberships
from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()


@pytest.fixture
def dimagi_ws(db):
    owner = User.objects.create_user(email="founder@dimagi.com")
    ws = Workspace.objects.create(
        slug="dimagi-team",
        display_name="Dimagi Team",
        drive_root_folder_id="folder-aj-1",
        created_by=owner,
        auto_join_domains=["dimagi.com", "dimagi-ai.com"],
    )
    WorkspaceMembership.objects.create(workspace=ws, user=owner, role="owner")
    return ws


def test_user_with_matching_domain_is_added_as_editor(db, dimagi_ws):
    user = User.objects.create_user(email="newbie@dimagi.com")
    joined = ensure_auto_join_memberships(user)

    assert [w.slug for w in joined] == ["dimagi-team"]
    m = WorkspaceMembership.objects.get(workspace=dimagi_ws, user=user)
    assert m.role == "editor"


def test_user_with_second_listed_domain_also_joins(db, dimagi_ws):
    user = User.objects.create_user(email="bot@dimagi-ai.com")
    joined = ensure_auto_join_memberships(user)
    assert [w.slug for w in joined] == ["dimagi-team"]


def test_user_with_non_matching_domain_is_not_added(db, dimagi_ws):
    user = User.objects.create_user(email="random@example.com")
    joined = ensure_auto_join_memberships(user)

    assert joined == []
    assert not WorkspaceMembership.objects.filter(
        workspace=dimagi_ws, user=user
    ).exists()


def test_user_without_email_is_a_noop(db, dimagi_ws):
    # The User model rejects empty emails at creation time, so simulate a
    # user-like object with no email instead. The helper should noop without
    # touching the DB.
    class _Fake:
        email = ""
    assert ensure_auto_join_memberships(_Fake()) == []


def test_is_idempotent_and_does_not_downgrade_existing_owner(db, dimagi_ws):
    # User already owns the workspace (e.g. founder)
    owner = User.objects.get(email="founder@dimagi.com")

    # Running auto-join shouldn't add a duplicate or change role
    joined1 = ensure_auto_join_memberships(owner)
    joined2 = ensure_auto_join_memberships(owner)

    assert joined1 == []  # already a member
    assert joined2 == []
    m = WorkspaceMembership.objects.get(workspace=dimagi_ws, user=owner)
    assert m.role == "owner"  # NOT downgraded to editor
    assert WorkspaceMembership.objects.filter(workspace=dimagi_ws, user=owner).count() == 1


def test_empty_auto_join_domains_means_no_auto_join(db):
    owner = User.objects.create_user(email="o@example.com")
    Workspace.objects.create(
        slug="ws-no-auto",
        display_name="No Auto-join",
        drive_root_folder_id="folder-aj-2",
        created_by=owner,
        auto_join_domains=[],
    )
    user = User.objects.create_user(email="someone@dimagi.com")
    assert ensure_auto_join_memberships(user) == []


def test_user_joins_all_matching_workspaces(db):
    o1 = User.objects.create_user(email="o1@example.com")
    o2 = User.objects.create_user(email="o2@example.com")
    ws_a = Workspace.objects.create(
        slug="ws-a",
        display_name="A",
        drive_root_folder_id="folder-aj-A",
        created_by=o1,
        auto_join_domains=["dimagi.com"],
    )
    ws_b = Workspace.objects.create(
        slug="ws-b",
        display_name="B",
        drive_root_folder_id="folder-aj-B",
        created_by=o2,
        auto_join_domains=["dimagi.com"],
    )
    user = User.objects.create_user(email="dual@dimagi.com")
    joined = ensure_auto_join_memberships(user)

    assert {w.slug for w in joined} == {"ws-a", "ws-b"}
    assert WorkspaceMembership.objects.filter(user=user).count() == 2
    assert WorkspaceMembership.objects.get(workspace=ws_a, user=user).role == "editor"
    assert WorkspaceMembership.objects.get(workspace=ws_b, user=user).role == "editor"


def test_domain_match_is_case_insensitive(db):
    o = User.objects.create_user(email="o@example.com")
    Workspace.objects.create(
        slug="ws-case",
        display_name="C",
        drive_root_folder_id="folder-aj-case",
        created_by=o,
        # Stored with mixed case + a stray leading @ — helper should still match
        auto_join_domains=["Dimagi.COM", "@dimagi-ai.com"],
    )
    u1 = User.objects.create_user(email="MixedCase@DIMAGI.com")
    u2 = User.objects.create_user(email="bot@dimagi-ai.com")
    assert ensure_auto_join_memberships(u1) != []
    assert ensure_auto_join_memberships(u2) != []
