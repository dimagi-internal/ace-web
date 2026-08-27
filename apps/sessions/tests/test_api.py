"""Contract tests for apps.sessions.api.

Pattern mirrors apps/opps/tests/test_api.py:
- Each helper is patched at its module-level name.
- member_client / non_member_client fixtures for workspace access control.
- anon_client fixture for 401 tests.
"""
import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()

# ---------------------------------------------------------------------------
# Fake data
# ---------------------------------------------------------------------------

_FAKE_SESSION_LIST = {
    "slug": "sess-0001",
    "title": "My session",
    "status": "active",
    "backend_kind": "cli",
    "source": "web",
    "cli_session_id": None,
    "created_at": "2026-05-14T09:00:00Z",
    "updated_at": "2026-05-14T10:00:00Z",
    "message_count": 0,
    "preview": "",
    "opp_slug": "",
    "opp_run_id": "",
    "opp_step_skill": "",
    "opp_display_name": "",
    "opp_step_skill_display": "",
}

_FAKE_COST_BREAKDOWN = {
    "schema_version": 0,
    "totals": None,
    "phases": [],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def member_client(db, client):
    creator = User.objects.create_user(email="creator@example.com")
    workspace = Workspace.objects.create(
        slug="ws1",
        display_name="WS1",
        drive_root_folder_id="folder-1",
        created_by=creator,
    )
    user = User.objects.create_user(email="member@example.com")
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="editor")
    client.force_login(user)
    return client, workspace, user


@pytest.fixture
def non_member_client(db, client):
    creator = User.objects.create_user(email="creator2@example.com")
    workspace = Workspace.objects.create(
        slug="ws1",
        display_name="WS1",
        drive_root_folder_id="folder-1",
        created_by=creator,
    )
    user = User.objects.create_user(email="outsider@example.com")
    client.force_login(user)
    return client, workspace, user


@pytest.fixture
def anon_client(db, client):
    creator = User.objects.create_user(email="creator3@example.com")
    workspace = Workspace.objects.create(
        slug="ws1",
        display_name="WS1",
        drive_root_folder_id="folder-1",
        created_by=creator,
    )
    return client, workspace


# ---------------------------------------------------------------------------
# 2.2.2 — GET / — list sessions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_sessions_returns_page(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.list_sessions_in_workspace",
        lambda ws, **kwargs: [_FAKE_SESSION_LIST],
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["slug"] == "sess-0001"


@pytest.mark.django_db
def test_list_sessions_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_list_sessions_anon_401(anon_client):
    client, workspace = anon_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_list_sessions_opp_filter_passed_through(member_client, monkeypatch):
    client, workspace, _ = member_client
    captured: dict = {}

    def _fake(ws, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr("apps.sessions.api.list_sessions_in_workspace", _fake)
    resp = client.get(f"/api/w/{workspace.slug}/sessions?opp_slug=some-opp")
    assert resp.status_code == 200
    assert captured["opp_slug"] == "some-opp"


@pytest.mark.django_db
def test_list_sessions_review_filters_passed_through(member_client, monkeypatch):
    """Every #706 review filter reaches the queryset builder, not just opp_slug."""
    client, workspace, _ = member_client
    captured: dict = {}

    def _fake(ws, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr("apps.sessions.api.list_sessions_in_workspace", _fake)
    resp = client.get(
        f"/api/w/{workspace.slug}/sessions"
        "?since=2026-08-01T00:00:00Z&source=upload&opp_run_id=20260801-1200"
        "&status=imported&halted=true"
    )
    assert resp.status_code == 200
    assert captured["since"] == "2026-08-01T00:00:00Z"
    assert captured["source"] == "upload"
    assert captured["opp_run_id"] == "20260801-1200"
    assert captured["status"] == "imported"
    assert captured["halted"] is True


# ---------------------------------------------------------------------------
# 2.2.3 — POST / — create session
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_session_201(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.create_session_in_workspace",
        lambda ws, user, body: {**_FAKE_SESSION_LIST, "title": body.title},
    )
    resp = client.post(
        f"/api/w/{workspace.slug}/sessions",
        {"title": "New chat"},
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "New chat"


@pytest.mark.django_db
def test_create_session_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.post(
        f"/api/w/{workspace.slug}/sessions",
        {"title": "x"},
        content_type="application/json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_create_session_anon_401(anon_client):
    client, workspace = anon_client
    resp = client.post(
        f"/api/w/{workspace.slug}/sessions",
        {"title": "x"},
        content_type="application/json",
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2.2.4 — GET /{slug} — session detail
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_session_detail_happy(member_client, monkeypatch):
    client, workspace, _ = member_client
    detail = {**_FAKE_SESSION_LIST, "messages": []}
    monkeypatch.setattr(
        "apps.sessions.api.get_session_detail",
        lambda ws, slug: detail if slug == "sess-0001" else None,
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001")
    assert resp.status_code == 200
    assert resp.json()["slug"] == "sess-0001"
    assert "messages" in resp.json()


@pytest.mark.django_db
def test_get_session_detail_unknown_slug_404(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr("apps.sessions.api.get_session_detail", lambda ws, slug: None)
    resp = client.get(f"/api/w/{workspace.slug}/sessions/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_get_session_detail_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_get_session_detail_anon_401(anon_client):
    client, workspace = anon_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2.2.5 — PATCH /{slug} — update session
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_patch_session_happy(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.patch_session_in_workspace",
        lambda ws, slug, updates: {**_FAKE_SESSION_LIST, **updates},
    )
    resp = client.patch(
        f"/api/w/{workspace.slug}/sessions/sess-0001",
        {"title": "Updated"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated"


@pytest.mark.django_db
def test_patch_session_not_found_404(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr("apps.sessions.api.patch_session_in_workspace", lambda *a, **k: None)
    resp = client.patch(
        f"/api/w/{workspace.slug}/sessions/no-such",
        {"title": "x"},
        content_type="application/json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_patch_session_invalid_status_422(member_client, monkeypatch):
    """Pydantic validates the Literal type before the handler runs; expect 422."""
    client, workspace, _ = member_client
    resp = client.patch(
        f"/api/w/{workspace.slug}/sessions/sess-0001",
        {"status": "deleted"},
        content_type="application/json",
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_patch_session_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.patch(
        f"/api/w/{workspace.slug}/sessions/s",
        {},
        content_type="application/json",
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2.2.6 — DELETE /{slug} — delete session
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_session_happy(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr("apps.sessions.api.delete_session_in_workspace", lambda ws, slug: True)
    resp = client.delete(f"/api/w/{workspace.slug}/sessions/sess-0001")
    assert resp.status_code == 204


@pytest.mark.django_db
def test_delete_session_not_found_404(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.delete_session_in_workspace", lambda ws, slug: False
    )
    resp = client.delete(f"/api/w/{workspace.slug}/sessions/no-such")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_delete_session_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.delete(f"/api/w/{workspace.slug}/sessions/s")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2.2.7 — GET /{slug}/messages — message history
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_messages_happy(member_client, monkeypatch):
    client, workspace, _ = member_client
    fake_msgs = [
        {
            "id": 1,
            "turn_index": 0,
            "role": "user",
            "content": {"type": "text", "text": "hi"},
            "plaintext": "hi",
            "status": "complete",
            "error_detail": None,
            "started_at": None,
            "completed_at": None,
            "created_at": "2026-05-14T09:00:00Z",
        }
    ]
    monkeypatch.setattr(
        "apps.sessions.api.list_messages_for_session",
        lambda ws, slug: fake_msgs,
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001/messages")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["role"] == "user"


@pytest.mark.django_db
def test_list_messages_not_found_404(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr("apps.sessions.api.list_messages_for_session", lambda ws, slug: None)
    resp = client.get(f"/api/w/{workspace.slug}/sessions/no-such/messages")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_list_messages_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/s/messages")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2.2.8 — GET /{slug}/participants — participant list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_participants_happy(member_client, monkeypatch):
    client, workspace, _ = member_client
    fake_parts = [
        {
            "user_id": 1,
            "email": "a@example.com",
            "display_name": "Alice",
            "role": "owner",
            "joined_at": "2026-05-14T09:00:00Z",
            "last_seen_at": None,
        }
    ]
    monkeypatch.setattr(
        "apps.sessions.api.list_participants_for_session",
        lambda ws, slug: fake_parts,
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001/participants")
    assert resp.status_code == 200
    assert resp.json()[0]["email"] == "a@example.com"


@pytest.mark.django_db
def test_list_participants_not_found_404(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.list_participants_for_session", lambda ws, slug: None
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/no-such/participants")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_list_participants_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/s/participants")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2.2.10 — GET /{slug}/cost — cost breakdown
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_cost_breakdown_happy(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.get_cost_breakdown",
        lambda ws, slug: _FAKE_COST_BREAKDOWN,
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001/cost")
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_version"] == 0
    assert body["totals"] is None


@pytest.mark.django_db
def test_cost_breakdown_not_found_404(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr("apps.sessions.api.get_cost_breakdown", lambda ws, slug: None)
    resp = client.get(f"/api/w/{workspace.slug}/sessions/no-such/cost")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_cost_breakdown_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/s/cost")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2.2.11 — GET /{slug}/structure — structure tree
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_structure_happy(member_client, monkeypatch):
    client, workspace, _ = member_client
    fake_tree = {
        "schema_version": 1,
        "session": None,
        "phases": [],
        "unavailable_reason": "no-raw-jsonl",
    }
    monkeypatch.setattr(
        "apps.sessions.api.get_structure_tree",
        lambda ws, slug, if_none_match=None: (fake_tree, None, False),
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001/structure")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_structure_304_when_etag_matches(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.get_structure_tree",
        lambda ws, slug, if_none_match=None: ({}, '"v1:abc"', True),
    )
    resp = client.get(
        f"/api/w/{workspace.slug}/sessions/sess-0001/structure",
        HTTP_IF_NONE_MATCH='"v1:abc"',
    )
    assert resp.status_code == 304


@pytest.mark.django_db
def test_structure_etag_in_response(member_client, monkeypatch):
    client, workspace, _ = member_client
    fake_tree = {"schema_version": 1, "session": None, "phases": []}
    monkeypatch.setattr(
        "apps.sessions.api.get_structure_tree",
        lambda ws, slug, if_none_match=None: (fake_tree, '"v1:abc123"', False),
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001/structure")
    assert resp.status_code == 200
    assert resp["ETag"] == '"v1:abc123"'


@pytest.mark.django_db
def test_structure_not_found_404(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.get_structure_tree",
        lambda ws, slug, if_none_match=None: (None, None, False),
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/no-such/structure")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_structure_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/s/structure")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /interrupted — resume-candidate detection (deploy-kill self-heal)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_interrupted_runs_endpoint_returns_items(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.interrupted_runs_in_workspace",
        lambda ws: [{
            "slug": "sess-killed", "opp_slug": "bednet-spot-check",
            "opp_run_id": "20260604-1551", "title": "seeded-run",
            "driver_heartbeat_at": None, "updated_at": None,
        }],
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/interrupted")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["slug"] == "sess-killed"
    assert items[0]["opp_run_id"] == "20260604-1551"


@pytest.mark.django_db
def test_interrupted_runs_route_not_shadowed_by_slug(member_client, monkeypatch):
    """`/interrupted` must hit the detector, not the /{slug} detail handler."""
    client, workspace, _ = member_client
    called = {}
    monkeypatch.setattr(
        "apps.sessions.api.interrupted_runs_in_workspace",
        lambda ws: called.setdefault("hit", True) or [],
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/interrupted")
    assert resp.status_code == 200
    assert called.get("hit") is True


@pytest.mark.django_db
def test_interrupted_runs_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/interrupted")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST resume / resume-interrupted — auto-resume (deploy-kill self-heal #3)
# ---------------------------------------------------------------------------


def _make_interrupted(workspace, user, opp_run_id="20260604-1551"):
    from datetime import timedelta

    from django.utils import timezone

    from apps.sessions.models import Message, Session
    s = Session.create_with_owner(
        owner=user, workspace=workspace, source="web",
        opp_slug="bednet-spot-check", opp_run_id=opp_run_id,
        driver_heartbeat_at=timezone.now() - timedelta(seconds=300),
    )
    Message.objects.create(
        session=s, turn_index=1, role="assistant", status="streaming", content={}
    )
    return s


@pytest.mark.django_db
def test_resume_interrupted_relaunches_ace_runs(member_client, monkeypatch):
    client, workspace, user = member_client
    _make_interrupted(workspace, user)
    spawned = []
    monkeypatch.setattr(
        "apps.sessions.turn_driver.start_turn_subprocess", lambda mid: spawned.append(mid)
    )
    resp = client.post(f"/api/w/{workspace.slug}/sessions/resume-interrupted")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["resumed"][0]["opp_run_id"] == "20260604-1551"
    assert len(spawned) == 1  # driver actually re-spawned


@pytest.mark.django_db
def test_resume_interrupted_skips_non_opp_sessions(member_client, monkeypatch):
    from datetime import timedelta

    from django.utils import timezone

    from apps.sessions.models import Message, Session
    client, workspace, user = member_client
    s = Session.create_with_owner(  # interrupted but NOT an opp run
        owner=user, workspace=workspace, source="web",
        driver_heartbeat_at=timezone.now() - timedelta(seconds=300),
    )
    Message.objects.create(
        session=s, turn_index=1, role="assistant", status="streaming", content={}
    )
    monkeypatch.setattr("apps.sessions.turn_driver.start_turn_subprocess", lambda mid: None)
    resp = client.post(f"/api/w/{workspace.slug}/sessions/resume-interrupted")
    assert resp.json()["count"] == 0


@pytest.mark.django_db
def test_resume_run_422_for_non_opp_session(member_client, monkeypatch):
    from apps.sessions.models import Session
    client, workspace, user = member_client
    s = Session.create_with_owner(owner=user, workspace=workspace, source="web")
    monkeypatch.setattr("apps.sessions.turn_driver.start_turn_subprocess", lambda mid: None)
    resp = client.post(f"/api/w/{workspace.slug}/sessions/{s.slug}/resume")
    assert resp.status_code == 422


@pytest.mark.django_db
def test_resume_run_routes_through_the_canopy_dispatch_seam(member_client, monkeypatch):
    """Mirror of the seeded-run seam test: the resume route must call
    run_dispatch.start_turn with the assistant message resume_session_run
    created, or flipping CANOPY_RUN_EXECUTION has no effect on a resume."""
    from apps.sessions.models import Session
    client, workspace, user = member_client
    s = Session.create_with_owner(
        owner=user, workspace=workspace, source="web",
        opp_slug="bednet-spot-check", opp_run_id="20260604-2058",
    )
    called = []
    monkeypatch.setattr("apps.canopy.run_dispatch.start_turn", lambda mid: called.append(mid))
    # Belt and braces: a regression to calling the subprocess directly would
    # otherwise spawn a REAL detached `manage.py drive_turn` in CI.
    spawned = []
    monkeypatch.setattr(
        "apps.sessions.turn_driver.start_turn_subprocess", lambda mid: spawned.append(mid)
    )
    resp = client.post(f"/api/w/{workspace.slug}/sessions/{s.slug}/resume")
    assert resp.status_code == 202
    assert called == [resp.json()["assistant_message_id"]]
    assert spawned == []  # the route went through the seam, not around it


@pytest.mark.django_db
def test_resume_interrupted_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.post(f"/api/w/{workspace.slug}/sessions/resume-interrupted")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_resume_interrupted_relaunches_graceful_cancel(member_client, monkeypatch):
    # The common deploy path: SIGTERM → turn marked error:'cancelled (...)'.
    # The bulk sweep must resume it (resumable_after_deploy, not interrupted).
    from datetime import timedelta

    from django.utils import timezone

    from apps.sessions.models import Message, Session
    client, workspace, user = member_client
    s = Session.create_with_owner(
        owner=user, workspace=workspace, source="web",
        opp_slug="bednet-spot-check", opp_run_id="20260604-2058",
    )
    Message.objects.create(
        session=s, turn_index=1, role="assistant", status="error",
        error_detail="cancelled (partial: 900 chars)",
        completed_at=timezone.now() - timedelta(seconds=60), content={},
    )
    spawned = []
    monkeypatch.setattr(
        "apps.sessions.turn_driver.start_turn_subprocess", lambda mid: spawned.append(mid)
    )
    resp = client.post(f"/api/w/{workspace.slug}/sessions/resume-interrupted")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert len(spawned) == 1


# ---------------------------------------------------------------------------
# The post-deploy sweep vs canopy-dispatched runs. Both cases below were found
# reviewing the dispatch seam (PR A) and are entry conditions for ever flipping
# CANOPY_RUN_EXECUTION on.
# ---------------------------------------------------------------------------

# Production's canopy wiring WITH the flag on. `config.settings.test` leaves
# CANOPY_BASE_URL and CANOPY_APP_CREDENTIAL empty, and run_dispatch.enabled()
# is an `and` chain that short-circuits on those BEFORE it reads the flag — so
# a test that does not set them says nothing about the flag.
_CANOPY_ON = dict(
    CANOPY_BASE_URL="http://canopy.test", CANOPY_APP_CREDENTIAL="c",
    CANOPY_WORKSPACE="connect", CANOPY_AGENT_SLUG="ace", CANOPY_RUN_EXECUTION=True,
)
_CANOPY_CONFIGURED_BUT_UNFLAGGED = {
    k: v for k, v in _CANOPY_ON.items() if k != "CANOPY_RUN_EXECUTION"
}


def _make_canopy_dispatched(workspace, user, *, opp_run_id, turn_id="turn-1"):
    """An interrupted-looking run whose execution already went to canopy."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.sessions.models import Message, Session
    s = Session.create_with_owner(
        owner=user, workspace=workspace, source="web",
        opp_slug="bednet-spot-check", opp_run_id=opp_run_id,
        canopy_session_id="sess-1",
        driver_heartbeat_at=timezone.now() - timedelta(seconds=300),
    )
    Message.objects.create(
        session=s, turn_index=1, role="assistant", status="streaming", content={},
        canopy_turn_id=turn_id,
    )
    return s


@pytest.mark.django_db
def test_resume_interrupted_survives_one_sessions_dispatch_failure(member_client, monkeypatch):
    """One bad session must not abort the sweep. Before this fix, DispatchError
    propagated out of the loop as an unhandled 500 and every session after the
    failing one was left unresumed AND unreported."""
    from apps.canopy.run_dispatch import DispatchError

    client, workspace, user = member_client
    _make_interrupted(workspace, user, opp_run_id="20260604-0001")
    _make_interrupted(workspace, user, opp_run_id="20260604-0002")

    calls = []

    def _boom(mid):
        calls.append(mid)
        if len(calls) == 1:
            raise DispatchError("canopy 403: nope")

    monkeypatch.setattr("apps.canopy.run_dispatch.start_turn", _boom)
    resp = client.post(f"/api/w/{workspace.slug}/sessions/resume-interrupted")

    assert resp.status_code == 200
    body = resp.json()
    assert len(calls) == 2, "the sweep stopped at the first failure"
    assert body["count"] == 1
    assert len(body["failed"]) == 1
    assert "403" in body["failed"][0]["error"]


@pytest.mark.django_db
def test_resume_interrupted_reports_the_failing_sessions_identity(member_client, monkeypatch):
    """A silent failure is the thing being fixed — the response must name which
    run did not restart, or the sweep's caller cannot act on it."""
    from apps.canopy.run_dispatch import DispatchError

    client, workspace, user = member_client
    s = _make_interrupted(workspace, user, opp_run_id="20260604-0003")
    monkeypatch.setattr(
        "apps.canopy.run_dispatch.start_turn",
        lambda mid: (_ for _ in ()).throw(DispatchError("canopy 502: down")),
    )
    resp = client.post(f"/api/w/{workspace.slug}/sessions/resume-interrupted")
    assert resp.json()["failed"] == [
        {"slug": s.slug, "opp_run_id": "20260604-0003", "error": "canopy 502: down"},
    ]


@pytest.mark.django_db
@override_settings(**_CANOPY_ON)
def test_resume_interrupted_does_not_redispatch_a_run_canopy_still_owns(
    member_client, monkeypatch,
):
    """The re-dispatch loop. A dispatched run sits `pending` with a beat that
    goes stale in 90s, so resumable_after_deploy matches it on every deploy —
    the sweep that dispatched it would keep re-dispatching it forever."""
    from unittest import mock

    client, workspace, user = member_client
    s = _make_canopy_dispatched(workspace, user, opp_run_id="20260604-0004")
    dispatched = []
    monkeypatch.setattr(
        "apps.canopy.run_dispatch.start_turn", lambda mid: dispatched.append(mid),
    )
    rows = [{"turn_id": "turn-1", "kind": "config", "reason": "no runner can take this session"}]
    with (
        mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}),
        mock.patch("apps.canopy.client.get_turn", return_value={"status": "queued"}),
        mock.patch("apps.canopy.client.list_unclaimable", return_value=rows),
    ):
        resp = client.post(f"/api/w/{workspace.slug}/sessions/resume-interrupted")

    assert resp.status_code == 200
    body = resp.json()
    assert dispatched == [], "the sweep re-dispatched a run canopy is still holding"
    assert body["count"] == 0
    assert body["skipped"] == [
        {"slug": s.slug, "opp_run_id": "20260604-0004", "state": "no_runner_configured"},
    ]
    # …and reconciling refreshed the beat, so the NEXT sweep skips it too.
    s.refresh_from_db()
    assert not type(s).resumable_after_deploy().filter(pk=s.pk).exists()


@pytest.mark.django_db
@override_settings(**_CANOPY_ON)
def test_resume_interrupted_still_resumes_a_run_whose_canopy_turn_died(
    member_client, monkeypatch,
):
    """The skip must be narrow: a canopy turn that FAILED is exactly what the
    self-heal exists for. Skipping it too would disable the sweep outright."""
    from unittest import mock

    client, workspace, user = member_client
    _make_canopy_dispatched(workspace, user, opp_run_id="20260604-0005")
    dispatched = []
    monkeypatch.setattr(
        "apps.canopy.run_dispatch.start_turn", lambda mid: dispatched.append(mid),
    )
    with (
        mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}),
        mock.patch(
            "apps.canopy.client.get_turn",
            return_value={"status": "failed", "result_note": "boom"},
        ),
    ):
        resp = client.post(f"/api/w/{workspace.slug}/sessions/resume-interrupted")
    assert resp.json()["count"] == 1
    assert len(dispatched) == 1


@pytest.mark.django_db
@override_settings(**_CANOPY_ON)
def test_resume_interrupted_does_not_resume_on_an_unreachable_canopy(
    member_client, monkeypatch,
):
    """UNKNOWN is not permission to act. canopy may still be executing the turn;
    resuming on a guess double-executes the run."""
    from unittest import mock

    from apps.canopy.client import CanopyError

    client, workspace, user = member_client
    _make_canopy_dispatched(workspace, user, opp_run_id="20260604-0006")
    dispatched = []
    monkeypatch.setattr(
        "apps.canopy.run_dispatch.start_turn", lambda mid: dispatched.append(mid),
    )
    with mock.patch(
        "apps.canopy.client.exchange_token", side_effect=CanopyError(502, "down"),
    ):
        resp = client.post(f"/api/w/{workspace.slug}/sessions/resume-interrupted")
    assert dispatched == []
    assert resp.json()["skipped"][0]["state"] == "unknown"


@pytest.mark.django_db
@override_settings(**_CANOPY_CONFIGURED_BUT_UNFLAGGED)
def test_resume_interrupted_consults_canopy_only_when_the_flag_is_on(
    member_client, monkeypatch,
):
    """Flag off ⇒ the sweep behaves exactly as it did before this PR. canopy is
    fully wired here, so the settings default is the only thing guarding it."""
    from unittest import mock

    from django.conf import settings

    assert settings.CANOPY_BASE_URL and settings.CANOPY_APP_CREDENTIAL
    client, workspace, user = member_client
    _make_canopy_dispatched(workspace, user, opp_run_id="20260604-0007")
    dispatched = []
    monkeypatch.setattr(
        "apps.canopy.run_dispatch.start_turn", lambda mid: dispatched.append(mid),
    )
    with mock.patch("apps.canopy.client.exchange_token") as ex:
        resp = client.post(f"/api/w/{workspace.slug}/sessions/resume-interrupted")
    ex.assert_not_called()
    assert resp.json()["count"] == 1
    assert len(dispatched) == 1


@pytest.mark.django_db
def test_resume_run_reports_a_dispatch_failure_as_a_problem_not_a_500(
    member_client, monkeypatch,
):
    from apps.canopy.run_dispatch import DispatchError
    from apps.sessions.models import Session

    client, workspace, user = member_client
    s = Session.create_with_owner(
        owner=user, workspace=workspace, source="web",
        opp_slug="bednet-spot-check", opp_run_id="20260604-0008",
    )
    monkeypatch.setattr(
        "apps.canopy.run_dispatch.start_turn",
        lambda mid: (_ for _ in ()).throw(DispatchError("canopy 403: nope")),
    )
    resp = client.post(f"/api/w/{workspace.slug}/sessions/{s.slug}/resume")
    assert resp.status_code == 502
    assert resp["Content-Type"].startswith("application/problem+json")
    assert "403" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /{slug}/execution — where this run's execution actually stands
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_execution_endpoint_reports_the_run_state(member_client, monkeypatch):
    from apps.sessions.models import Session

    client, workspace, user = member_client
    s = Session.create_with_owner(
        owner=user, workspace=workspace, source="web",
        opp_slug="bednet-spot-check", opp_run_id="20260604-1000",
    )
    monkeypatch.setattr(
        "apps.canopy.run_state.reconcile_session",
        lambda session: {
            "state": "no_runner_configured",
            "detail": "no runner can take this session",
            "canopy_turn_id": "turn-1",
            "canopy_session_id": "sess-1",
        },
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/{s.slug}/execution")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "no_runner_configured"
    assert body["detail"] == "no runner can take this session"


@pytest.mark.django_db
def test_execution_endpoint_404s_an_unknown_session(member_client):
    client, workspace, _ = member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/does-not-exist/execution")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_execution_endpoint_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/s/execution")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_execution_route_is_not_shadowed_by_the_slug_route(member_client, monkeypatch):
    """`/{slug}/execution` must not be swallowed by `/{slug}` — the same
    shadowing that `/interrupted` is registered early to avoid."""
    from apps.sessions.models import Session

    client, workspace, user = member_client
    s = Session.create_with_owner(owner=user, workspace=workspace, source="web")
    monkeypatch.setattr(
        "apps.canopy.run_state.reconcile_session",
        lambda session: {"state": "not_dispatched", "detail": "",
                         "canopy_turn_id": "", "canopy_session_id": ""},
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/{s.slug}/execution")
    assert resp.status_code == 200
    assert "state" in resp.json()


# ---------------------------------------------------------------------------
# 2.2.11 — /structure reads through the transcript SOURCE, not raw_jsonl_gz
# ---------------------------------------------------------------------------


def _session_in(workspace, user, **kwargs):
    from apps.sessions.models import Session

    return Session.create_with_owner(
        owner=user, workspace=workspace, title="t", source="web", **kwargs
    )


_STRUCT_LINE = (
    b'{"type":"assistant","timestamp":"2026-01-01T00:00:00.000Z","uuid":"u1","message":'
    b'{"role":"assistant","model":"claude-sonnet-4-6",'
    b'"content":[{"type":"text","text":"x"}],"usage":{"input_tokens":1,"output_tokens":1}}}\n'
)


@pytest.mark.django_db
def test_structure_reads_through_the_transcript_source(member_client):
    """/structure must not touch raw_jsonl_gz directly — a canopy-executed
    session has no local blob until the cache is seated."""
    from unittest import mock

    client, workspace, user = member_client
    session = _session_in(workspace, user, canopy_session_id="sess-1")
    from apps.ingest.sources import TranscriptRead

    with mock.patch(
        "apps.ingest.sources.read_session_transcript",
        return_value=TranscriptRead(_STRUCT_LINE, ""),
    ) as src:
        resp = client.get(f"/api/w/{workspace.slug}/sessions/{session.slug}/structure")
    assert resp.status_code == 200
    src.assert_called_once()
    assert "unavailable_reason" not in resp.json()


@pytest.mark.django_db
def test_structure_reports_no_raw_jsonl_when_the_source_has_nothing(member_client):
    from unittest import mock

    client, workspace, user = member_client
    session = _session_in(workspace, user, canopy_session_id="sess-1")
    from apps.ingest.sources import TranscriptRead

    with mock.patch(
        "apps.ingest.sources.read_session_transcript",
        return_value=TranscriptRead(None, "no-raw-jsonl"),
    ):
        resp = client.get(f"/api/w/{workspace.slug}/sessions/{session.slug}/structure")
    assert resp.status_code == 200
    assert resp.json()["unavailable_reason"] == "no-raw-jsonl"


@pytest.mark.django_db
def test_structure_of_a_local_session_still_comes_from_its_own_blob(member_client):
    """The regression that matters most: a pre-migration run's structure tree
    must be the same tree the aggregator builds from that run's own bytes —
    not merely a tree, which is all a truthiness check can tell you."""
    import gzip
    import json

    from apps.ingest.parser import parse_session_bytes
    from apps.ingest.structure_aggregator import aggregate
    from apps.sessions.models import IngestUpload

    client, workspace, user = member_client
    session = _session_in(workspace, user)
    IngestUpload.objects.create(
        session=session, uploaded_by=user, raw_jsonl_gz=gzip.compress(_STRUCT_LINE),
        content_sha256="abc123", line_count=1,
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/{session.slug}/structure")
    assert resp.status_code == 200
    body = resp.json()
    assert "unavailable_reason" not in body

    _parsed, events = parse_session_bytes(_STRUCT_LINE)
    expected = json.loads(json.dumps(aggregate(events), default=str))
    # `computed_at` is a wall clock; everything that describes the RUN must match.
    body.pop("computed_at", None)
    expected.pop("computed_at", None)
    assert body == expected


@pytest.mark.django_db
def test_structure_etag_is_the_hash_of_the_bytes_actually_served(member_client):
    """It used to be `IngestUpload.content_sha256` — the same number for every
    pre-existing row, but a session can now carry two rows and the seam can
    serve the local prefix when the canopy cache is unreachable, so a hash
    looked up from a row is no longer guaranteed to describe what went out."""
    import gzip
    import hashlib

    from apps.ingest.structure_aggregator import SCHEMA_VERSION
    from apps.sessions.models import IngestUpload

    client, workspace, user = member_client
    session = _session_in(workspace, user)
    IngestUpload.objects.create(
        session=session, uploaded_by=user, raw_jsonl_gz=gzip.compress(_STRUCT_LINE),
        content_sha256="abc123",   # deliberately NOT a hash of these bytes
    )
    url = f"/api/w/{workspace.slug}/sessions/{session.slug}/structure"
    resp = client.get(url)
    assert resp["ETag"] == f'"v{SCHEMA_VERSION}:{hashlib.sha256(_STRUCT_LINE).hexdigest()}"'
    again = client.get(url, HTTP_IF_NONE_MATCH=resp["ETag"])
    assert again.status_code == 304


@pytest.mark.django_db
def test_structure_reports_parse_failed_when_the_bytes_do_not_aggregate(member_client):
    from unittest import mock

    client, workspace, user = member_client
    session = _session_in(workspace, user, canopy_session_id="sess-1")
    from apps.ingest.sources import TranscriptRead

    with mock.patch(
        "apps.ingest.sources.read_session_transcript",
        return_value=TranscriptRead(_STRUCT_LINE, ""),
    ), mock.patch(
        "apps.ingest.structure_aggregator.aggregate", side_effect=RuntimeError("boom")
    ):
        resp = client.get(f"/api/w/{workspace.slug}/sessions/{session.slug}/structure")
    assert resp.status_code == 200
    assert resp.json()["unavailable_reason"] == "parse-failed"


@pytest.mark.django_db
@override_settings(**_CANOPY_CONFIGURED_BUT_UNFLAGGED)
def test_structure_never_reaches_canopy_with_the_flag_off(member_client):
    """Flag off ⇒ /structure behaves exactly as it did before this PR. canopy is
    fully wired here, so nothing but the absence of a `canopy_session_id` (which
    only a dispatch under the flag can write) is guarding the call."""
    import gzip
    from unittest import mock

    from django.conf import settings

    from apps.sessions.models import IngestUpload, Message

    assert settings.CANOPY_BASE_URL and settings.CANOPY_APP_CREDENTIAL
    client, workspace, user = member_client
    session = _session_in(workspace, user)
    # A turn id present without a session id is the shape that would tempt a
    # reader to go to canopy anyway. `canopy_session_id` is the discriminator,
    # and only a dispatch under the flag ever writes it.
    Message.objects.create(
        session=session, turn_index=1, role="assistant", content={"text": ""},
        status="complete", canopy_turn_id="turn-a",
    )
    IngestUpload.objects.create(
        session=session, uploaded_by=user, raw_jsonl_gz=gzip.compress(_STRUCT_LINE),
        content_sha256="abc123",
    )
    with mock.patch("apps.canopy.client.exchange_token") as ex:
        resp = client.get(f"/api/w/{workspace.slug}/sessions/{session.slug}/structure")
    ex.assert_not_called()
    assert resp.status_code == 200
    assert resp.json()["phases"]


@pytest.mark.django_db
@override_settings(**_CANOPY_ON)
def test_structure_of_a_hybrid_session_covers_its_local_phases_too(member_client):
    """A run that executed locally and was later dispatched to canopy must not
    lose its pre-flag phases from the structure tree."""
    import gzip
    from unittest import mock

    from apps.sessions.models import IngestUpload, Message

    client, workspace, user = member_client
    session = _session_in(workspace, user, canopy_session_id="sess-1")
    IngestUpload.objects.create(
        session=session, uploaded_by=user, source="local",
        raw_jsonl_gz=gzip.compress(_STRUCT_LINE),
    )
    Message.objects.create(
        session=session, turn_index=9, role="assistant", content={"text": ""},
        status="complete", canopy_turn_id="turn-a",
    )
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch("apps.canopy.transcripts.fetch_turn_transcript", return_value=b""):
        resp = client.get(f"/api/w/{workspace.slug}/sessions/{session.slug}/structure")
    assert resp.status_code == 200
    body = resp.json()
    assert "unavailable_reason" not in body
    assert body["phases"]   # the LOCAL half, which canopy never held


@pytest.mark.django_db
@override_settings(**_CANOPY_ON)
def test_structure_says_canopy_was_unreachable_rather_than_never_recorded(member_client):
    from unittest import mock

    from apps.canopy.client import CanopyError
    from apps.sessions.models import Message

    client, workspace, user = member_client
    session = _session_in(workspace, user, canopy_session_id="sess-1")
    Message.objects.create(
        session=session, turn_index=1, role="assistant", content={"text": ""},
        status="complete", canopy_turn_id="turn-a",
    )
    with mock.patch("apps.canopy.client.exchange_token", side_effect=CanopyError(502, "x")):
        resp = client.get(f"/api/w/{workspace.slug}/sessions/{session.slug}/structure")
    assert resp.json()["unavailable_reason"] == "canopy-unreachable"


@pytest.mark.django_db
def test_structure_of_a_corrupt_blob_still_says_parse_failed(member_client):
    """Pre-seam this surfaced as `parse-failed` because the gunzip sat inside
    `get_structure_tree`'s own try/except. Moving the gunzip into the seam must
    not silently retitle it — the two strings render different user messages."""
    from apps.sessions.models import IngestUpload

    client, workspace, user = member_client
    session = _session_in(workspace, user)
    IngestUpload.objects.create(
        session=session, uploaded_by=user, raw_jsonl_gz=b"not gzip at all",
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/{session.slug}/structure")
    assert resp.json()["unavailable_reason"] == "parse-failed"
