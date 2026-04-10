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
