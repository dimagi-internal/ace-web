"""Integration tests for apps/sessions/sweep_api.py.

These exercise the real ORM (no monkeypatching) because the surface is
small and the CASCADE behavior is exactly what's being validated.
"""
import pytest
from django.contrib.auth import get_user_model

from apps.sessions.models import IngestUpload, Message, Session, ShareToken
from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()


@pytest.fixture
def two_workspaces(db):
    """Two workspaces; alice is Owner of ws1+Editor of ws2; bob is Viewer of ws1."""
    alice = User.objects.create_user(email="alice@example.com")
    bob = User.objects.create_user(email="bob@example.com")

    ws1 = Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1", created_by=alice
    )
    ws2 = Workspace.objects.create(
        slug="ws2", display_name="WS2", drive_root_folder_id="folder-2", created_by=alice
    )

    WorkspaceMembership.objects.create(workspace=ws1, user=alice, role="owner")
    WorkspaceMembership.objects.create(workspace=ws2, user=alice, role="editor")
    WorkspaceMembership.objects.create(workspace=ws1, user=bob, role="viewer")

    return {"alice": alice, "bob": bob, "ws1": ws1, "ws2": ws2}


def _make_session(workspace, owner, *, title="t", source="web", opp_slug="") -> Session:
    return Session.create_with_owner(
        owner=owner, workspace=workspace, title=title, source=source, opp_slug=opp_slug
    )


# ---------------------------------------------------------------------------
# GET /api/sessions/sweep
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sweep_list_returns_sessions_from_writable_workspaces(two_workspaces, client):
    alice = two_workspaces["alice"]
    ws1, ws2 = two_workspaces["ws1"], two_workspaces["ws2"]

    s1 = _make_session(ws1, alice, title="in ws1", source="upload", opp_slug="opp-a")
    s2 = _make_session(ws2, alice, title="in ws2", source="web")

    client.force_login(alice)
    resp = client.get("/api/sessions/sweep")
    assert resp.status_code == 200
    body = resp.json()
    slugs = {row["slug"] for row in body["sessions"]}
    assert slugs == {s1.slug, s2.slug}
    # ws1 row carries opp + source metadata through
    row1 = next(r for r in body["sessions"] if r["slug"] == s1.slug)
    assert row1["source"] == "upload"
    assert row1["opp_slug"] == "opp-a"
    assert row1["workspace_slug"] == "ws1"


@pytest.mark.django_db
def test_sweep_list_omits_viewer_workspaces(two_workspaces, client):
    """Bob is a Viewer of ws1 — sessions there must not appear in his sweep."""
    alice, bob = two_workspaces["alice"], two_workspaces["bob"]
    ws1 = two_workspaces["ws1"]

    _make_session(ws1, alice, title="alice's chat")

    client.force_login(bob)
    resp = client.get("/api/sessions/sweep")
    assert resp.status_code == 200
    assert resp.json() == {"sessions": [], "total_raw_bytes": 0}


@pytest.mark.django_db
def test_sweep_list_aggregates_upload_bytes(two_workspaces, client):
    alice = two_workspaces["alice"]
    ws1 = two_workspaces["ws1"]
    session = _make_session(ws1, alice)
    IngestUpload.objects.create(
        session=session,
        uploaded_by=alice,
        workspace=ws1,
        raw_bytes=1234,
    )
    IngestUpload.objects.create(
        session=session,
        uploaded_by=alice,
        workspace=ws1,
        raw_bytes=4321,
    )

    client.force_login(alice)
    resp = client.get("/api/sessions/sweep")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_raw_bytes"] == 5555
    assert body["sessions"][0]["upload_count"] == 2


@pytest.mark.django_db
def test_sweep_list_anon_401(client):
    resp = client.get("/api/sessions/sweep")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/sessions/sweep/delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sweep_delete_cascades_uploads_messages_and_share_tokens(two_workspaces, client):
    alice = two_workspaces["alice"]
    ws1 = two_workspaces["ws1"]
    session = _make_session(ws1, alice)
    IngestUpload.objects.create(
        session=session, uploaded_by=alice, workspace=ws1, raw_bytes=100
    )
    Message.objects.create(
        session=session, turn_index=0, role="user", content={}, plaintext="hi"
    )
    ShareToken.objects.create(session=session, created_by=alice, workspace=ws1)

    client.force_login(alice)
    resp = client.post(
        "/api/sessions/sweep/delete",
        {"session_ids": [session.id]},
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"deleted": 1, "failed": []}

    assert not Session.objects.filter(pk=session.pk).exists()
    assert not IngestUpload.objects.filter(session_id=session.pk).exists()
    assert not Message.objects.filter(session_id=session.pk).exists()
    assert not ShareToken.objects.filter(session_id=session.pk).exists()


@pytest.mark.django_db
def test_sweep_delete_refuses_viewer_workspace(two_workspaces, client):
    alice, bob = two_workspaces["alice"], two_workspaces["bob"]
    ws1 = two_workspaces["ws1"]
    session = _make_session(ws1, alice)

    client.force_login(bob)  # Viewer on ws1
    resp = client.post(
        "/api/sessions/sweep/delete",
        {"session_ids": [session.id]},
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] == 0
    assert body["failed"] == [{"session_id": session.id, "reason": "forbidden"}]
    assert Session.objects.filter(pk=session.pk).exists()


@pytest.mark.django_db
def test_sweep_delete_idempotent_returns_not_found(two_workspaces, client):
    alice = two_workspaces["alice"]
    ws1 = two_workspaces["ws1"]
    session = _make_session(ws1, alice)
    sid = session.id
    session.delete()

    client.force_login(alice)
    resp = client.post(
        "/api/sessions/sweep/delete",
        {"session_ids": [sid]},
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] == 0
    assert body["failed"] == [{"session_id": sid, "reason": "not_found"}]


@pytest.mark.django_db
def test_sweep_delete_dedupes_input(two_workspaces, client):
    alice = two_workspaces["alice"]
    ws1 = two_workspaces["ws1"]
    session = _make_session(ws1, alice)

    client.force_login(alice)
    resp = client.post(
        "/api/sessions/sweep/delete",
        {"session_ids": [session.id, session.id, session.id]},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 1, "failed": []}


@pytest.mark.django_db
def test_sweep_delete_empty_body_ok(two_workspaces, client):
    alice = two_workspaces["alice"]
    client.force_login(alice)
    resp = client.post(
        "/api/sessions/sweep/delete",
        {"session_ids": []},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 0, "failed": []}


@pytest.mark.django_db
def test_sweep_delete_anon_401(client):
    resp = client.post(
        "/api/sessions/sweep/delete",
        {"session_ids": [1]},
        content_type="application/json",
    )
    assert resp.status_code == 401
