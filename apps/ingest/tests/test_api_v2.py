"""Contract tests for apps.ingest.api_v2."""
import io

import pytest
from django.contrib.auth import get_user_model

from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()

_FAKE_UPLOAD_RESULT = {
    "session_slug": "sess-ingest-001",
    "messages_imported": 5,
    "cli_session_id": "cli-abc",
    "opp_slug": None,
    "opp_run_id": None,
    "opp_step_skill": None,
    "cost_breakdown": None,
}


@pytest.fixture
def member_client(db, client):
    user = User.objects.create_user(email="uploader@example.com")
    ws = Workspace.objects.create(
        slug="ingest-ws",
        display_name="Ingest WS",
        drive_root_folder_id="folder-ingest",
        created_by=user,
    )
    WorkspaceMembership.objects.create(workspace=ws, user=user, role="editor")
    client.force_login(user)
    return client, ws, user


@pytest.fixture
def anon_client(db, client):
    return client


# ---------------------------------------------------------------------------
# POST /ingest/upload
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_upload_201(member_client, monkeypatch):
    client, ws, _ = member_client
    monkeypatch.setattr(
        "apps.ingest.api_v2.process_ingest_upload",
        lambda **kwargs: _FAKE_UPLOAD_RESULT,
    )
    resp = client.post(
        "/api/ingest/upload",
        {
            "file": io.BytesIO(b'{"type":"text"}\n'),
            "workspace_slug": ws.slug,
        },
        format="multipart",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["session_slug"] == "sess-ingest-001"
    assert body["messages_imported"] == 5


@pytest.mark.django_db
def test_upload_anon_401(anon_client):
    resp = anon_client.post(
        "/api/ingest/upload",
        {"file": io.BytesIO(b"data")},
        format="multipart",
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_upload_bad_opp_field_422(member_client, monkeypatch):
    client, ws, _ = member_client
    resp = client.post(
        "/api/ingest/upload",
        {
            "file": io.BytesIO(b"data"),
            "opp_slug": "bad slug with spaces",
        },
        format="multipart",
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_upload_nonmember_workspace_404(member_client, db, monkeypatch):
    client, _, _ = member_client
    # workspace that doesn't exist
    resp = client.post(
        "/api/ingest/upload",
        {
            "file": io.BytesIO(b"data"),
            "workspace_slug": "nonexistent-ws",
        },
        format="multipart",
    )
    assert resp.status_code == 404
