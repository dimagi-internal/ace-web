# apps/sessions/tests/test_structure_endpoint.py
"""GET /api/sessions/<slug>/structure — on-demand structure tree.

Pattern copied verbatim from test_cost_endpoints.py: the endpoint mirrors
session_cost_breakdown for membership gating, 404-on-unknown, and 404-
(not-403)-on-other-user. Empty-state envelope shape (schema_version=0
+ unavailable_reason) matches the cost-breakdown empty shape.
"""
from __future__ import annotations

import gzip
from pathlib import Path

import pytest
from rest_framework.test import APIClient

from apps.sessions.models import IngestUpload, Session

FIXTURES = Path(__file__).parent.parent.parent / "ingest" / "tests" / "fixtures"

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="structure@example.com", display_name="structure"
    )


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(
        email="otherstructure@example.com", display_name="other-structure"
    )


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _make_session_with_blob(user, *, raw_bytes: bytes | None) -> Session:
    """Build a Session and attach an IngestUpload, optionally with raw_jsonl_gz."""
    session = Session.create_with_owner(owner=user, title="t")
    IngestUpload.objects.create(
        session=session,
        uploaded_by=user,
        source_path="fixture.jsonl",
        raw_bytes=len(raw_bytes) if raw_bytes else 0,
        line_count=0,
        cli_session_id="",
        content_sha256="",
        raw_jsonl_gz=gzip.compress(raw_bytes) if raw_bytes else None,
    )
    return session


@pytest.fixture
def session_with_blob(user) -> Session:
    """Session with a real JSONL blob persisted on its IngestUpload."""
    raw = (FIXTURES / "tool_use_session.jsonl").read_bytes()
    return _make_session_with_blob(user, raw_bytes=raw)


@pytest.fixture
def session_without_blob(user) -> Session:
    """Session with an IngestUpload that has raw_jsonl_gz=None."""
    return _make_session_with_blob(user, raw_bytes=None)


def test_structure_endpoint_returns_tree(client, session_with_blob):
    """A session with persisted raw JSONL returns the schema-v1 tree."""
    response = client.get(f"/api/sessions/{session_with_blob.slug}/structure")
    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert body["data"]["schema_version"] == 1
    assert "phases" in body["data"]
    assert body["data"]["session"]["wall_time_seconds"] >= 0


def test_structure_endpoint_returns_unavailable_for_no_blob(client, session_without_blob):
    """Older uploads without raw_jsonl_gz return schema_version=0 with the
    unavailable_reason marker, matching the cost-breakdown empty shape."""
    response = client.get(f"/api/sessions/{session_without_blob.slug}/structure")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["schema_version"] == 0
    assert body["data"]["unavailable_reason"] == "no-raw-jsonl"
    assert body["data"]["phases"] == []


def test_structure_endpoint_404_for_unknown_slug(client):
    """Unknown slug returns 404 envelope (matches cost endpoint)."""
    response = client.get("/api/sessions/does-not-exist/structure")
    assert response.status_code == 404


def test_structure_endpoint_404_for_other_users_session(other_user):
    """A session not owned/shared with the requester returns 404, not 403,
    so existence is not leaked. Mirrors the cost endpoint's behavior."""
    s = Session.create_with_owner(owner=other_user, title="other")
    c = APIClient()
    from apps.auth.models import User
    me = User.objects.create_user(email="me-structure@example.com", display_name="me")
    c.force_authenticate(user=me)
    response = c.get(f"/api/sessions/{s.slug}/structure")
    assert response.status_code == 404


def test_structure_endpoint_returns_parse_failed_for_corrupt_blob(
    client, session_with_blob, monkeypatch
):
    """A persisted blob that the parser/aggregator can't handle returns the
    parse-failed envelope instead of bubbling a 500.

    parse_session_file is forgiving (it skips invalid lines) so plain garbage
    bytes don't reliably raise. Monkeypatch the parser at its source module
    (the view imports it locally inside the function) to raise unconditionally
    — that's the load-bearing branch we need to prove returns the documented
    empty-envelope shape rather than 500.
    """
    def _boom(_path):
        raise ValueError("simulated parser failure")

    monkeypatch.setattr("apps.ingest.parser.parse_session_file", _boom)

    response = client.get(f"/api/sessions/{session_with_blob.slug}/structure")
    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert body["data"]["schema_version"] == 0
    assert body["data"]["session"] is None
    assert body["data"]["phases"] == []
    assert body["data"]["unavailable_reason"] == "parse-failed"
