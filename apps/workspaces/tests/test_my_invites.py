"""GET /api/invites/mine — the signed-in user's own pending invites (#911)."""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.workspaces.models import Workspace, WorkspaceInvite, WorkspaceMembership

User = get_user_model()


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@example.com", display_name="Olive Owner")


def _workspace(owner, slug, name):
    ws = Workspace.objects.create(
        slug=slug, display_name=name, drive_root_folder_id=f"folder-{slug}", created_by=owner
    )
    WorkspaceMembership.objects.create(workspace=ws, user=owner, role="owner")
    return ws


def _invite(ws, owner, email, role="editor", **kw):
    return WorkspaceInvite.objects.create(
        workspace=ws, email=email, role=role, invited_by=owner,
        expires_at=kw.pop("expires_at", timezone.now() + timedelta(days=7)), **kw,
    )


@pytest.fixture
def visitor(db):
    return User.objects.create_user(email="Visitor@Partner.org", display_name="Vi Sitor")


def _mine(client, user, **params):
    client.force_login(user)
    return client.get("/api/invites/mine", params)


def test_returns_my_own_invite_matched_case_insensitively(client, owner, visitor):
    spark = _workspace(owner, "spark", "Spark Microgrants")
    invite = _invite(spark, owner, "visitor@partner.ORG", role="viewer")

    resp = _mine(client, visitor)

    assert resp.status_code == 200
    assert resp.json() == [
        {
            "workspace_slug": "spark",
            "workspace_display_name": "Spark Microgrants",
            "role": "viewer",
            "invited_by_email": "owner@example.com",
            "expires_at": resp.json()[0]["expires_at"],
            "accept_url": f"/invite/{invite.token}",
        }
    ]


def test_never_returns_another_emails_invites(client, owner, visitor):
    spark = _workspace(owner, "spark", "Spark Microgrants")
    _invite(spark, owner, "someone-else@partner.org")
    _invite(spark, owner, "visitor@partner.org.evil.com")

    resp = _mine(client, visitor)

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.parametrize(
    "kw",
    [
        {"expires_at": timezone.now() - timedelta(minutes=1)},
        {"accepted_at": timezone.now()},
        {"revoked_at": timezone.now()},
    ],
    ids=["expired", "accepted", "revoked"],
)
def test_used_or_expired_invites_are_excluded(client, owner, visitor, kw):
    spark = _workspace(owner, "spark", "Spark Microgrants")
    _invite(spark, owner, visitor.email, **kw)

    assert _mine(client, visitor).json() == []


def test_workspace_filter(client, owner, visitor):
    spark = _workspace(owner, "spark", "Spark Microgrants")
    kmc = _workspace(owner, "kmc", "Kangaroo Care")
    _invite(spark, owner, visitor.email)
    _invite(kmc, owner, visitor.email, role="admin")

    both = _mine(client, visitor).json()
    assert sorted(i["workspace_slug"] for i in both) == ["kmc", "spark"]

    only_kmc = _mine(client, visitor, workspace="kmc").json()
    assert [(i["workspace_slug"], i["role"]) for i in only_kmc] == [("kmc", "admin")]

    # An unknown slug answers the same empty list as a workspace you were
    # not invited to — no existence leak.
    assert _mine(client, visitor, workspace="no-such-workspace").json() == []


def test_anonymous_gets_401(client, owner):
    spark = _workspace(owner, "spark", "Spark Microgrants")
    _invite(spark, owner, "visitor@partner.org")

    resp = client.get("/api/invites/mine")

    assert resp.status_code == 401


def test_mine_does_not_shadow_token_preview(client, owner):
    spark = _workspace(owner, "spark", "Spark Microgrants")
    invite = _invite(spark, owner, "visitor@partner.org")

    resp = client.get(f"/api/invites/{invite.token}")

    assert resp.status_code == 200
    assert resp.json()["workspace_slug"] == "spark"
