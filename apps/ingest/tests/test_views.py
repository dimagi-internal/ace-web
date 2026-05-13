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


def test_upload_with_workspace_slug_attaches_workspace(client, user):
    """Web UI upload path: the frontend sends `workspace_slug` from the URL
    so a user-driven upload lands in the workspace they're viewing,
    not as an orphan only the uploader can see.
    """
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
        {"file": file, "workspace_slug": "acme"},
        format="multipart",
    )
    assert resp.status_code == 201
    upload = IngestUpload.objects.get(uploaded_by=user)
    assert upload.workspace == ws
    assert upload.session.workspace == ws


def test_upload_workspace_slug_non_member_returns_404(client, user):
    """Non-membership on workspace_slug returns 404 (existence-hidden) —
    callers know the slug from the URL, but membership is the real gate.
    """
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
        {"file": file, "workspace_slug": "other-ws"},
        format="multipart",
    )
    assert resp.status_code == 404


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


def test_upload_populates_cost_breakdown(client):
    resp = _upload_fixture(client, "cost_session.jsonl")
    assert resp.status_code == 201
    slug = resp.json()["data"]["session_slug"]
    session = Session.objects.get(slug=slug)
    assert session.cost_breakdown
    assert session.cost_breakdown["schema_version"] == 1
    assert session.cost_breakdown["totals"]["input_tokens"] > 0


def test_upload_simple_session_has_breakdown_with_zero_or_minimal_costs(client):
    """The simple_session fixture has no usage blocks; breakdown should
    still populate with zero totals (not an empty dict)."""
    resp = _upload_fixture(client, "simple_session.jsonl")
    slug = resp.json()["data"]["session_slug"]
    session = Session.objects.get(slug=slug)
    assert session.cost_breakdown.get("schema_version") == 1
    assert session.cost_breakdown["totals"]["input_tokens"] == 0


def test_upload_honors_explicit_opp_run_id_verbatim(client):
    """The form-supplied opp_run_id must round-trip unchanged. Issue #274
    Bug 1: the response was reportedly returning a different run-id
    than the form sent. Code review showed no override logic, but lock
    the contract with a regression test."""
    content = (FIXTURES / "interactive_session.jsonl").read_bytes()
    file = BytesIO(content)
    file.name = "session.jsonl"
    resp = client.post(
        "/api/ingest/upload",
        {
            "file": file,
            "opp_slug": "leep-paint-collection",
            "opp_run_id": "20260509-1448",
        },
        format="multipart",
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["opp_run_id"] == "20260509-1448"
    session = Session.objects.get(slug=body["session_slug"])
    assert session.opp_run_id == "20260509-1448"


def test_upload_rejects_malformed_opp_run_id(client):
    """Hardening for issue #274 Bug 1: reject anything outside the
    [A-Za-z0-9_.-]{1,64} alphabet rather than storing it silently. The
    operator gets a 422 with a `validation_error` envelope so a typo
    surfaces immediately instead of producing a silently-misattributed
    Session."""
    content = (FIXTURES / "simple_session.jsonl").read_bytes()
    file = BytesIO(content)
    file.name = "simple_session.jsonl"
    resp = client.post(
        "/api/ingest/upload",
        {"file": file, "opp_slug": "x", "opp_run_id": "not a run id"},
        format="multipart",
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_upload_logs_opp_linkage_fields(client, caplog):
    """Issue #274 Bug 1 instrumentation: every upload logs the form-supplied
    opp linkage and the resulting stored values so prod regressions are
    visible in CloudWatch."""
    import logging
    caplog.set_level(logging.INFO, logger="apps.ingest.views")
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
    matches = [r for r in caplog.records if "ingest upload" in r.getMessage()]
    assert matches, "expected an INFO log line about the ingest upload"
    msg = matches[0].getMessage()
    assert "malaria-pilot" in msg
    assert "r1" in msg
    assert "idea-to-pdd" in msg


def test_upload_dedups_on_content_hash_when_no_cli_session_id(client):
    """Hardening for issue #274 Bug 2: even after the parser learns the
    Claude Code interactive envelope, transcripts that lack any session-id
    field must still dedup on raw-byte hash so re-uploads don't produce
    duplicate Session rows."""
    raw = b'{"type":"assistant","message":{"id":"m1","content":[{"type":"text","text":"hi"}]}}\n'
    f1 = BytesIO(raw)
    f1.name = "x.jsonl"
    resp1 = client.post("/api/ingest/upload", {"file": f1}, format="multipart")
    assert resp1.status_code == 201
    assert resp1.json()["data"]["cli_session_id"] == ""
    f2 = BytesIO(raw)
    f2.name = "x.jsonl"
    resp2 = client.post("/api/ingest/upload", {"file": f2}, format="multipart")
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "duplicate"


def test_upload_persists_raw_jsonl_gz(client):
    """Uploaded transcripts retain a gzipped copy of the raw bytes so the
    on-demand session structure view can re-parse without a transcript-shaped
    intermediate. Verifies both the raw round-trip and the read_raw_jsonl()
    convenience method."""
    import gzip

    raw = (FIXTURES / "tool_use_session.jsonl").read_bytes()
    file = BytesIO(raw)
    file.name = "tool_use_session.jsonl"
    resp = client.post("/api/ingest/upload", {"file": file}, format="multipart")
    assert resp.status_code == 201
    upload = IngestUpload.objects.latest("created_at")
    assert upload.raw_jsonl_gz, "blob should be populated"
    assert gzip.decompress(bytes(upload.raw_jsonl_gz)) == raw
    assert upload.read_raw_jsonl() == raw.decode("utf-8")


def test_ingest_upload_read_raw_jsonl_returns_none_when_blob_absent(client):
    """Older IngestUpload rows (pre-this-PR) have NULL raw_jsonl_gz;
    read_raw_jsonl() must return None rather than raising."""
    resp = _upload_fixture(client)
    assert resp.status_code == 201
    upload = IngestUpload.objects.latest("created_at")
    upload.raw_jsonl_gz = None
    upload.save(update_fields=["raw_jsonl_gz"])
    upload.refresh_from_db()
    assert upload.read_raw_jsonl() is None


def test_upload_aggregator_failure_does_not_block_ingest(client, monkeypatch):
    """If the aggregator raises, the session is still created with empty breakdown."""
    from apps.ingest import views as ingest_views
    def _boom(_events):
        raise RuntimeError("boom")
    monkeypatch.setattr(ingest_views, "aggregate", _boom)
    resp = _upload_fixture(client, "cost_session.jsonl")
    assert resp.status_code == 201
    slug = resp.json()["data"]["session_slug"]
    session = Session.objects.get(slug=slug)
    assert session.cost_breakdown == {}
