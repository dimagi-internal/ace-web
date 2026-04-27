from io import BytesIO
from pathlib import Path

import pytest
from rest_framework.test import APIClient

from apps.sessions.models import IngestUpload, Message, Session

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="t@example.com", display_name="t"
    )


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _upload_fixture(client, filename="simple_session.jsonl"):
    content = (FIXTURES / filename).read_bytes()
    file = BytesIO(content)
    file.name = filename
    return client.post("/api/ingest/upload", {"file": file}, format="multipart")


def test_upload_creates_session(client, user):
    resp = _upload_fixture(client)
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert "session_slug" in body
    assert body["message_count"] > 0
    assert body["cli_session_id"] == "sess_simple_001"
    session = Session.objects.get(slug=body["session_slug"])
    assert session.source == "upload"
    assert session.status == "imported"
    assert session.owner == user


def test_upload_creates_messages(client):
    resp = _upload_fixture(client)
    slug = resp.json()["data"]["session_slug"]
    messages = Message.objects.filter(session__slug=slug).order_by("turn_index")
    assert messages.count() >= 1
    assert messages.first().role == "assistant"


def test_upload_creates_ingest_record(client):
    resp = _upload_fixture(client)
    slug = resp.json()["data"]["session_slug"]
    record = IngestUpload.objects.get(session__slug=slug)
    assert record.cli_session_id == "sess_simple_001"
    assert record.raw_bytes > 0
    assert record.line_count == 4


def test_upload_duplicate_returns_409(client):
    resp1 = _upload_fixture(client)
    assert resp1.status_code == 201
    resp2 = _upload_fixture(client)
    assert resp2.status_code == 409


def test_upload_missing_file_returns_400(client):
    resp = client.post("/api/ingest/upload", {}, format="multipart")
    assert resp.status_code == 400


def test_upload_tool_use_session(client):
    resp = _upload_fixture(client, "tool_use_session.jsonl")
    assert resp.status_code == 201
    slug = resp.json()["data"]["session_slug"]
    messages = Message.objects.filter(session__slug=slug).order_by("turn_index")
    roles = list(messages.values_list("role", flat=True))
    assert "tool_use" in roles
    assert "tool_result" in roles


def test_upload_with_opp_linkage_populates_session_fields(client):
    """Plugin's upload-transcript skill passes opp_slug / opp_run_id /
    opp_step_skill as multipart form fields so the resulting Session is
    surfaced under the opp in the Workbench."""
    content = (FIXTURES / "simple_session.jsonl").read_bytes()
    file = BytesIO(content)
    file.name = "simple_session.jsonl"
    resp = client.post(
        "/api/ingest/upload",
        {
            "file": file,
            "opp_slug": "malaria-pilot",
            "opp_run_id": "r1",
            "opp_step_skill": "idea-to-pdd",
        },
        format="multipart",
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["opp_slug"] == "malaria-pilot"
    assert body["opp_run_id"] == "r1"
    assert body["opp_step_skill"] == "idea-to-pdd"
    session = Session.objects.get(slug=body["session_slug"])
    assert session.opp_slug == "malaria-pilot"
    assert session.opp_run_id == "r1"
    assert session.opp_step_skill == "idea-to-pdd"


def test_upload_without_opp_linkage_leaves_fields_blank(client):
    """Omitting opp_* fields is valid — upload still succeeds, linkage
    fields stay empty strings on the Session."""
    resp = _upload_fixture(client)
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["opp_slug"] is None
    session = Session.objects.get(slug=body["session_slug"])
    assert session.opp_slug == ""
    assert session.opp_run_id == ""
    assert session.opp_step_skill == ""


def test_upload_with_ace_root_folder_id_attaches_workspace(client, user):
    """Upload sent with ace_root_folder_id matching a workspace the user
    is a member of populates IngestUpload.workspace + Session.workspace."""
    from apps.workspaces.models import Workspace, WorkspaceMembership
    ws = Workspace.objects.create(
        slug="acme", display_name="Acme",
        drive_root_folder_id="folder-acme", created_by=user,
    )
    WorkspaceMembership.objects.create(workspace=ws, user=user, role="owner")

    content = (FIXTURES / "simple_session.jsonl").read_bytes()
    file = BytesIO(content)
    file.name = "simple_session.jsonl"
    resp = client.post(
        "/api/ingest/upload",
        {"file": file, "ace_root_folder_id": "folder-acme"},
        format="multipart",
    )
    assert resp.status_code == 201
    upload = IngestUpload.objects.get(uploaded_by=user)
    assert upload.workspace == ws
    assert upload.session.workspace == ws


def test_upload_with_unknown_folder_returns_404(client):
    content = (FIXTURES / "simple_session.jsonl").read_bytes()
    file = BytesIO(content)
    file.name = "simple_session.jsonl"
    resp = client.post(
        "/api/ingest/upload",
        {"file": file, "ace_root_folder_id": "no-such-folder"},
        format="multipart",
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "workspace-not-found"


def test_upload_to_workspace_user_is_not_member_of_returns_403(client, user):
    """A workspace exists for that folder, but the uploader isn't a member."""
    from apps.auth.models import User
    from apps.workspaces.models import Workspace
    other = User.objects.create_user(email="other@example.com", display_name="other")
    Workspace.objects.create(
        slug="other-ws", display_name="Other",
        drive_root_folder_id="folder-other", created_by=other,
    )

    content = (FIXTURES / "simple_session.jsonl").read_bytes()
    file = BytesIO(content)
    file.name = "simple_session.jsonl"
    resp = client.post(
        "/api/ingest/upload",
        {"file": file, "ace_root_folder_id": "folder-other"},
        format="multipart",
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "not-a-member"


def test_upload_without_folder_id_creates_orphan(client, user):
    """Backward compat: older plugin uploads (no ace_root_folder_id) work
    as orphan uploads — workspace=None, visible only to the uploader."""
    content = (FIXTURES / "simple_session.jsonl").read_bytes()
    file = BytesIO(content)
    file.name = "simple_session.jsonl"
    resp = client.post(
        "/api/ingest/upload",
        {"file": file},
        format="multipart",
    )
    assert resp.status_code == 201
    upload = IngestUpload.objects.get(uploaded_by=user)
    assert upload.workspace is None
    assert upload.session.workspace is None
