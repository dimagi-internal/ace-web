import datetime as dt
import json

import pytest
from django.contrib.auth import get_user_model

from apps.opps.schemas import (
    ArtifactOut,
    ForkProgress,
    GateOut,
    OppCardOut,
    OppCompareOut,
    OppForkOut,
    OppHealthOut,
    OppRunOut,
    OppSnapshotOut,
    ScorecardOut,
    SeedChatOut,
    SeededRunIn,
    SeededRunOut,
    StepSnapshotOut,
)
from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()


# ---------------------------------------------------------------------------
# Shared fake data helpers
# ---------------------------------------------------------------------------

_FAKE_SNAPSHOT = {
    "slug": "opp-1",
    "title": "Opp One",
    "runs": [
        {
            "run_id": "run-001",
            "label": "Run 1",
            "started_at": "2026-05-14T09:00:00Z",
            "finished_at": None,
            "is_active": True,
            "scorecard": None,
        }
    ],
    "active_run_id": "run-001",
    "steps": [],
    "pending_gates": [],
    "scorecard": None,
    "updated_at": "2026-05-14T10:00:00Z",
}

_FAKE_CARD = {
    "slug": "opp-1",
    "title": "Opp One",
    "current_phase": None,
    "current_skill": None,
    "run_count": 1,
    "last_run_id": "run-001",
    "updated_at": "2026-05-14T10:00:00Z",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def member_client(db, client):
    workspace = Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator@example.com"),
    )
    user = User.objects.create_user(email="a@example.com")
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="editor")
    client.force_login(user)
    return client, workspace, user


@pytest.fixture
def non_member_client(db, client):
    creator = User.objects.create_user(email="creator2@example.com")
    workspace = Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=creator,
    )
    user = User.objects.create_user(email="b@example.com")
    client.force_login(user)
    return client, workspace, user


@pytest.mark.django_db
def test_list_opps_returns_pydantic_validated_payload(member_client, monkeypatch):
    client, workspace, _ = member_client
    fake_cards = [
        {
            "slug": "opp-1",
            "title": "Opp One",
            "current_phase": None,
            "current_skill": None,
            "run_count": 1,
            "last_run_id": "run-001",
            "updated_at": "2026-05-14T10:00:00Z",
        }
    ]
    monkeypatch.setattr(
        "apps.opps.api.list_opp_cards", lambda workspace: fake_cards
    )

    response = client.get("/api/w/ws1/opps")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    # Validate the items round-trip through the Pydantic schema.
    [OppCardOut.model_validate(item) for item in body["items"]]
    assert body["total"] == 1


@pytest.mark.django_db
def test_list_opps_passes_null_updated_at_through(member_client, monkeypatch):
    """Regression for #466.

    Opps with no completed run (idea-only / pre-run state) must serialise
    ``updated_at`` as null, not as the Unix epoch. Before the fix the v2
    list-opps endpoint fell back to ``1970-01-01T00:00:00Z`` which the
    frontend OppCard component rendered as ``last 12/31/1969``.
    """
    client, _, _ = member_client
    fake_cards = [
        {
            "slug": "cosmetics-fgd-pilot",
            "title": "Cosmetics FGD Pilot",
            "current_phase": None,
            "current_skill": None,
            "run_count": 0,
            "last_run_id": None,
            "updated_at": None,
        }
    ]
    monkeypatch.setattr(
        "apps.opps.api.list_opp_cards", lambda workspace: fake_cards
    )

    response = client.get("/api/w/ws1/opps")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    # Critical: null must round-trip as JSON null, not "1970-01-01..." or 0.
    assert item["updated_at"] is None
    # And the Pydantic schema must accept it.
    parsed = OppCardOut.model_validate(item)
    assert parsed.updated_at is None


def test_opp_card_normaliser_returns_none_for_missing_or_invalid_ts():
    """Unit-level guard for the timestamp-normalisation block in
    ``list_opp_cards``. Mirrors the production logic so a future refactor
    that re-introduces the ``_EPOCH`` fallback will break this test loudly.

    Regression for #466.
    """
    import datetime as dt

    def _normalize(raw_ts):
        if raw_ts:
            try:
                return dt.datetime.fromisoformat(
                    raw_ts.replace("Z", "+00:00") if raw_ts.endswith("Z") else raw_ts
                )
            except ValueError:
                return None
        return None

    # None → None (don't fall through to epoch).
    assert _normalize(None) is None
    # Malformed ISO → None.
    assert _normalize("not-an-iso-timestamp") is None
    # Empty string → None.
    assert _normalize("") is None
    # Well-formed string still parses.
    assert _normalize("2026-05-14T10:00:00Z") == dt.datetime(
        2026, 5, 14, 10, 0, tzinfo=dt.UTC
    )
    # Confirm we are NOT returning the old _EPOCH sentinel.
    assert _normalize(None) != dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


@pytest.mark.django_db
def test_list_opps_404s_non_member(non_member_client):
    client, _, _ = non_member_client
    creator = User.objects.create_user(email="creator3@example.com")
    Workspace.objects.create(
        slug="ws2", display_name="WS2", drive_root_folder_id="folder-2",
        created_by=creator,
    )
    response = client.get("/api/w/ws2/opps")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 404
    assert body["type"].endswith("/not-found")


@pytest.mark.django_db
def test_list_opps_401_anonymous(db, client):
    creator = User.objects.create_user(email="creator4@example.com")
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=creator,
    )
    response = client.get("/api/w/ws1/opps")
    assert response.status_code == 401
    assert response["Content-Type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# Task 2.1.3 — GET /w/{workspace_slug}/opps/{slug}
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_opp_returns_snapshot_with_etag(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.load_rich_opp_snapshot",
        lambda workspace, slug, run_id=None: _FAKE_SNAPSHOT,
    )
    response = client.get("/api/w/ws1/opps/opp-1")
    assert response.status_code == 200
    assert "ETag" in response
    body = response.json()
    OppSnapshotOut.model_validate(body)
    assert body["slug"] == "opp-1"


@pytest.mark.django_db
def test_get_opp_304_on_matching_etag(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.load_rich_opp_snapshot",
        lambda workspace, slug, run_id=None: _FAKE_SNAPSHOT,
    )
    # First request — get the ETag.
    r1 = client.get("/api/w/ws1/opps/opp-1")
    assert r1.status_code == 200
    etag = r1["ETag"]
    # Second request with matching If-None-Match → 304.
    r2 = client.get("/api/w/ws1/opps/opp-1", HTTP_IF_NONE_MATCH=etag)
    assert r2.status_code == 304


@pytest.mark.django_db
def test_get_opp_404_non_member(non_member_client, monkeypatch):
    client, _, _ = non_member_client
    response = client.get("/api/w/ws1/opps/opp-1")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


@pytest.mark.django_db
def test_get_opp_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator5@example.com"),
    )
    response = client.get("/api/w/ws1/opps/opp-1")
    assert response.status_code == 401


@pytest.mark.django_db
def test_get_opp_404_unknown_slug(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.load_rich_opp_snapshot",
        lambda workspace, slug, run_id=None: None,
    )
    response = client.get("/api/w/ws1/opps/no-such-opp")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"].endswith("/not-found")


# ---------------------------------------------------------------------------
# #484 — run selector freshness regression
#
# When a cached OppSnapshot exists and orchestration adds a new run folder
# in Drive externally, the Drive Changes API reports the new file's id but
# NOT its parent — so snapshot_cache.invalidate misses it, the cached
# snapshot keeps serving its stale runs_summary, and the workbench's run
# selector blinds itself to runs created after the page first loaded.
#
# Fix: on every cache hit, re-list the runs/ folder fresh and overlay the
# result onto the cached snapshot before serializing.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_load_rich_opp_snapshot_refreshes_runs_on_cache_hit(monkeypatch, db):
    """Cache-hit path must re-read runs/ from Drive so newly-created runs
    appear in the snapshot's runs[] (and thus the workbench dropdown)
    without waiting for cache invalidation. #484."""
    from apps.opps import access, snapshot_cache
    from apps.opps.api import load_rich_opp_snapshot
    from apps.opps.sync import (
        OppManifest,
        OppSnapshot,
        RunDetail,
        RunSummary,
    )

    user = User.objects.create_user(email=f"r484-1-{id(monkeypatch)}@example.com")
    workspace = Workspace.objects.filter(created_by=user).first()
    if workspace is None:
        workspace = Workspace.objects.first()

    cache_calls = {"list_opp_runs": 0}

    stale_run = RunSummary(
        run_id="20260515-1600",
        folder_id="folder-stale",
        current_phase="design",
        current_step=None,
        mode="default",
        last_actor="ace@dimagi-ai.com",
        last_actor_at="2026-05-15T16:00:00Z",
        lifecycle_status="in_progress",
        phases_total=10,
        phases_done=2,
        latest_phase_done="idea-to-pdd",
    )
    fresh_runs = [
        RunSummary(
            run_id="20260517-1829",
            folder_id="folder-new",
            current_phase="design",
            current_step=None,
            mode="default",
            last_actor="ace@dimagi-ai.com",
            last_actor_at="2026-05-17T18:29:00Z",
            lifecycle_status="in_progress",
            phases_total=10,
            phases_done=1,
            latest_phase_done="idea-to-pdd",
        ),
        stale_run,
    ]

    # Pre-populate the cache with a snapshot whose runs_summary only sees
    # the older run — simulating "cache was warm before orchestration
    # added a newer run in Drive externally."
    cached_snap = OppSnapshot(
        opp=OppManifest(
            slug="opp-1",
            display_name="Opp One",
            created_at=None,
            created_by=None,
            labels=[],
            current_run_id="20260515-1600",
        ),
        pdd_body="",
        opp_folder_id="opp-folder",
        current_run=RunDetail(
            run_id="20260515-1600",
            mode="default",
            status="ok",
            started_at=None,
            completed_at=None,
            current_phase="design",
            current_step=None,
            skill_versions={},
            notes="",
            steps=[],
            folder_id="folder-stale",
            decisions=[],
        ),
        runs_summary=[stale_run],
    )
    snapshot_cache.set(
        workspace_id=workspace.pk, slug="opp-1", run_id="20260515-1600",
        snap=cached_snap, file_ids={"opp-folder"},
    )

    # Stub the Drive client + access helpers so load_rich_opp_snapshot
    # takes the cache-hit branch and doesn't try to talk to real Drive.
    class _StubDrive:
        pass

    monkeypatch.setattr(
        "apps.opps.access.resolve_ace_root_folder_id",
        lambda ws: "ace-root",
    )
    monkeypatch.setattr(
        "apps.opps.drive_client.get_drive_client",
        lambda workspace=None: _StubDrive(),
    )
    # observe() → empty set (Changes API reported nothing, so invalidation
    # never fires — exactly the bug scenario).
    monkeypatch.setattr(
        "apps.opps.drive_changes.observe", lambda workspace, client: set(),
    )

    def _fake_list_opp_runs(client, *, ace_root_folder_id, opp_slug, opp_children=None):
        cache_calls["list_opp_runs"] += 1
        return list(fresh_runs)

    monkeypatch.setattr(
        "apps.opps.sync.list_opp_runs", _fake_list_opp_runs,
    )

    # Also stub overlay_workspace_display_name and CachedDriveClient so
    # the function doesn't touch unrelated paths.
    monkeypatch.setattr(
        access, "overlay_workspace_display_name",
        lambda manifest, slug, workspace=None: None,
    )

    payload = load_rich_opp_snapshot(workspace, "opp-1", run_id="20260515-1600")
    assert payload is not None
    # The serialized runs list must include the newer run that only Drive
    # knows about — proving the cache hit refreshed runs_summary.
    run_ids = [r["run_id"] for r in payload["runs"]]
    assert "20260517-1829" in run_ids
    assert "20260515-1600" in run_ids
    # And we did call list_opp_runs once — the fresh listing.
    assert cache_calls["list_opp_runs"] == 1


@pytest.mark.django_db
def test_load_rich_opp_snapshot_refresh_drive_failure_keeps_cached_runs(
    monkeypatch, db
):
    """If the runs/ re-listing fails (network blip, missing folder), the
    cached runs_summary survives — we degrade gracefully rather than
    serving an empty dropdown. #484."""
    from apps.opps import access, snapshot_cache
    from apps.opps.api import load_rich_opp_snapshot
    from apps.opps.sync import (
        OppManifest,
        OppSnapshot,
        RunDetail,
        RunSummary,
    )

    user = User.objects.create_user(email=f"r484-2-{id(monkeypatch)}@example.com")
    workspace = Workspace.objects.filter(created_by=user).first()
    if workspace is None:
        workspace = Workspace.objects.first()

    stale_run = RunSummary(
        run_id="20260515-1600",
        folder_id="folder-stale",
        current_phase="design",
        current_step=None,
        mode="default",
        last_actor="ace@dimagi-ai.com",
        last_actor_at="2026-05-15T16:00:00Z",
        lifecycle_status="in_progress",
        phases_total=10,
        phases_done=2,
        latest_phase_done="idea-to-pdd",
    )

    cached_snap = OppSnapshot(
        opp=OppManifest(
            slug="opp-1",
            display_name="Opp One",
            created_at=None,
            created_by=None,
            labels=[],
            current_run_id="20260515-1600",
        ),
        pdd_body="",
        opp_folder_id="opp-folder",
        current_run=RunDetail(
            run_id="20260515-1600",
            mode="default",
            status="ok",
            started_at=None,
            completed_at=None,
            current_phase="design",
            current_step=None,
            skill_versions={},
            notes="",
            steps=[],
            folder_id="folder-stale",
            decisions=[],
        ),
        runs_summary=[stale_run],
    )
    snapshot_cache.set(
        workspace_id=workspace.pk, slug="opp-1", run_id="20260515-1600",
        snap=cached_snap, file_ids={"opp-folder"},
    )

    class _StubDrive:
        pass

    monkeypatch.setattr(
        "apps.opps.access.resolve_ace_root_folder_id", lambda ws: "ace-root",
    )
    monkeypatch.setattr(
        "apps.opps.drive_client.get_drive_client",
        lambda workspace=None: _StubDrive(),
    )
    monkeypatch.setattr(
        "apps.opps.drive_changes.observe", lambda workspace, client: set(),
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("drive down")

    monkeypatch.setattr("apps.opps.sync.list_opp_runs", _boom)
    monkeypatch.setattr(
        access, "overlay_workspace_display_name",
        lambda manifest, slug, workspace=None: None,
    )

    payload = load_rich_opp_snapshot(workspace, "opp-1", run_id="20260515-1600")
    assert payload is not None
    run_ids = [r["run_id"] for r in payload["runs"]]
    # Cached runs_summary preserved — empty list would be a regression.
    assert run_ids == ["20260515-1600"]


# ---------------------------------------------------------------------------
# Task 2.1.4 — POST /w/{workspace_slug}/opps  (create opp)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_opp_happy_path(member_client, monkeypatch):
    client, workspace, user = member_client
    monkeypatch.setattr(
        "apps.opps.api.create_opp_and_return_card",
        lambda workspace, user, body: _FAKE_CARD,
    )
    response = client.post(
        "/api/w/ws1/opps",
        data={"title": "New Opp", "slug": "new-opp", "idea": "An idea."},
        content_type="application/json",
    )
    assert response.status_code == 201
    body = response.json()
    OppCardOut.model_validate(body)


@pytest.mark.django_db
def test_create_opp_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.post(
        "/api/w/ws1/opps",
        data={"title": "New Opp", "slug": "new-opp", "idea": "An idea."},
        content_type="application/json",
    )
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


@pytest.mark.django_db
def test_create_opp_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator6@example.com"),
    )
    response = client.post(
        "/api/w/ws1/opps",
        data={"title": "New Opp", "slug": "new-opp", "idea": "An idea."},
        content_type="application/json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_create_opp_400_empty_title(member_client):
    client, workspace, _ = member_client
    response = client.post(
        "/api/w/ws1/opps",
        data={"title": "", "slug": "new-opp", "idea": "An idea."},
        content_type="application/json",
    )
    assert response.status_code == 422


@pytest.mark.django_db
def test_create_opp_409_duplicate_slug(member_client, monkeypatch):
    from apps.opps.opp_creator import CreateOppError
    client, workspace, user = member_client

    def _raise_conflict(workspace, user, body):
        raise CreateOppError("slug-taken", "opp 'new-opp' already exists")

    monkeypatch.setattr("apps.opps.api.create_opp_and_return_card", _raise_conflict)
    response = client.post(
        "/api/w/ws1/opps",
        data={"title": "New Opp", "slug": "new-opp", "idea": "An idea."},
        content_type="application/json",
    )
    assert response.status_code == 409
    assert response["Content-Type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# Task 2.1.5 — PATCH /w/{workspace_slug}/opps/{slug}  (update opp)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_patch_opp_happy_path(member_client, monkeypatch):
    client, workspace, user = member_client
    monkeypatch.setattr(
        "apps.opps.api.patch_opp_and_return_card",
        lambda workspace, slug, body: _FAKE_CARD,
    )
    response = client.patch(
        "/api/w/ws1/opps/opp-1",
        data={"title": "Updated Title"},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    OppCardOut.model_validate(body)


@pytest.mark.django_db
def test_patch_opp_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.patch(
        "/api/w/ws1/opps/opp-1",
        data={"title": "Updated Title"},
        content_type="application/json",
    )
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


@pytest.mark.django_db
def test_patch_opp_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator7@example.com"),
    )
    response = client.patch(
        "/api/w/ws1/opps/opp-1",
        data={"title": "Updated"},
        content_type="application/json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_patch_opp_404_unknown_slug(member_client, monkeypatch):
    from apps.opps.opp_creator import CreateOppError
    client, workspace, user = member_client

    def _raise_not_found(workspace, slug, body):
        raise CreateOppError("opp-not-found", "opp not found")

    monkeypatch.setattr("apps.opps.api.patch_opp_and_return_card", _raise_not_found)
    response = client.patch(
        "/api/w/ws1/opps/no-such-opp",
        data={"title": "Updated"},
        content_type="application/json",
    )
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


@pytest.mark.django_db
def test_patch_opp_400_empty_title(member_client):
    client, workspace, _ = member_client
    response = client.patch(
        "/api/w/ws1/opps/opp-1",
        data={"title": ""},
        content_type="application/json",
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Task 2.1.6 — DELETE /w/{workspace_slug}/opps/{slug}
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_opp_happy_path(member_client, monkeypatch):
    client, workspace, user = member_client
    monkeypatch.setattr(
        "apps.opps.api.delete_opp_by_slug",
        lambda workspace, slug: None,
    )
    response = client.delete("/api/w/ws1/opps/opp-1")
    assert response.status_code == 204


@pytest.mark.django_db
def test_delete_opp_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.delete("/api/w/ws1/opps/opp-1")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


@pytest.mark.django_db
def test_delete_opp_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator8@example.com"),
    )
    response = client.delete("/api/w/ws1/opps/opp-1")
    assert response.status_code == 401


@pytest.mark.django_db
def test_delete_opp_404_unknown_slug(member_client, monkeypatch):
    client, workspace, user = member_client

    def _raise_not_found(workspace, slug):
        raise FileNotFoundError(f"no opp named {slug!r}")

    monkeypatch.setattr("apps.opps.api.delete_opp_by_slug", _raise_not_found)
    response = client.delete("/api/w/ws1/opps/no-such-opp")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# Shared fake runs data
# ---------------------------------------------------------------------------

_FAKE_RUNS = [
    {
        "run_id": "run-001",
        "label": "run-001",
        "started_at": "2026-05-14T09:00:00Z",
        "finished_at": None,
        "is_active": True,
        "scorecard": None,
    },
    {
        "run_id": "run-002",
        "label": "run-002",
        "started_at": "2026-05-13T09:00:00Z",
        "finished_at": None,
        "is_active": False,
        "scorecard": None,
    },
]

_FAKE_STEP = {
    "skill": "idea-to-pdd",
    "phase": "design",
    "status": "complete",
    "artifact_count": 1,
    "artifacts": [
        {
            "id": "file-abc",
            "name": "pdd.md",
            "mime_type": "text/plain",
            "size_bytes": 1024,
            "url": "https://drive.google.com/file/abc",
            "is_text": True,
            "preview": None,
        }
    ],
    "verdicts": [],
    "gate": None,
    "preview": None,
}

_FAKE_ARTIFACT = {
    "id": "file-abc",
    "name": "pdd.md",
    "mime_type": "text/plain",
    "size_bytes": 1024,
    "url": "https://drive.google.com/file/abc",
    "is_text": True,
    "preview": None,
}

_FAKE_SCORECARD = {
    "score": 87,
    "verdict": "pass",
    "rationale": "All checks passed.",
    "trend": [80, 84, 87],
    "decided_at": "2026-05-14T10:00:00Z",
}

_FAKE_GATE = {
    "skill": "idea-to-pdd",
    "decision": "approved",
    "decided_by": "a@example.com",
    "decided_at": "2026-05-14T10:00:00Z",
    "note": None,
}

_FAKE_FORK_RESULT = {
    "slug": "opp-1",
    "run_id": "run-002",
    "working_session_slug": "sess-xyz",
}

_FAKE_SNAPSHOT_A = {**_FAKE_SNAPSHOT, "slug": "opp-1", "active_run_id": "run-001"}
_FAKE_SNAPSHOT_B = {**_FAKE_SNAPSHOT, "slug": "opp-1", "active_run_id": "run-002"}


# ---------------------------------------------------------------------------
# Task 2.1.7 — GET /w/{ws}/opps/{slug}/runs
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_runs_happy_path(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.list_opp_runs_for_workspace",
        lambda workspace, slug: _FAKE_RUNS,
    )
    response = client.get("/api/w/ws1/opps/opp-1/runs")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert body["total"] == 2
    [OppRunOut.model_validate(item) for item in body["items"]]


@pytest.mark.django_db
def test_list_runs_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.get("/api/w/ws1/opps/opp-1/runs")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


@pytest.mark.django_db
def test_list_runs_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator-r1@example.com"),
    )
    response = client.get("/api/w/ws1/opps/opp-1/runs")
    assert response.status_code == 401


@pytest.mark.django_db
def test_list_runs_empty_for_unknown_slug(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.list_opp_runs_for_workspace",
        lambda workspace, slug: [],
    )
    response = client.get("/api/w/ws1/opps/no-such/runs")
    assert response.status_code == 200
    assert response.json()["total"] == 0


@pytest.mark.django_db
def test_list_runs_enriches_phase_display_and_ordinal(member_client, monkeypatch):
    """`/runs` enriches each run with phase_display + phase_ordinal so the
    OppCardRunsStrip can render a "P{ordinal}" chip instead of "—".

    Regression: when DRF was retired the new Ninja list_runs endpoint
    asdict'd RunSummary directly, which has no _display/_ordinal fields.
    The chip rendered "—" for every run even when latest_phase_done was
    populated.
    """
    from apps.opps.sync import RunSummary

    client, _, _ = member_client

    fake_run = RunSummary(
        run_id="20260514-2007",
        folder_id="fake-folder",
        current_phase=None,
        current_step=None,
        mode="default",
        last_actor="jjackson@dimagi.com",
        last_actor_at="2026-05-14T20:07:00Z",
        lifecycle_status="in_progress",
        phases_total=10,
        phases_done=3,
        latest_phase_done="commcare-setup",
    )

    class _StubDrive:
        pass

    monkeypatch.setattr(
        "apps.opps.access.resolve_ace_root_folder_id",
        lambda workspace: "ace-root",
    )
    monkeypatch.setattr(
        "apps.opps.drive_client.get_drive_client",
        lambda workspace: _StubDrive(),
    )
    monkeypatch.setattr(
        "apps.opps.sync.list_opp_runs",
        lambda drive, *, ace_root_folder_id, opp_slug: [fake_run],
    )

    response = client.get("/api/w/ws1/opps/opp-1/runs")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    item = items[0]
    # Display + ordinal come from the stub plugin's commcare-setup agent
    # frontmatter (phase_display: "CommCare Setup", phase_ordinal: 2).
    assert item["latest_phase_done"] == "commcare-setup"
    assert item["latest_phase_done_display"] == "CommCare Setup"
    assert item["latest_phase_done_ordinal"] == 2
    # current_phase is None on this fixture; enrichment fields stay null.
    assert item["current_phase_display"] is None
    assert item["current_phase_ordinal"] is None


# ---------------------------------------------------------------------------
# Task 2.1.8 — GET /w/{ws}/opps/{slug}/runs/{run_id}
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_run_happy_path(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.list_opp_runs_for_workspace",
        lambda workspace, slug: _FAKE_RUNS,
    )
    response = client.get("/api/w/ws1/opps/opp-1/runs/run-001")
    assert response.status_code == 200
    OppRunOut.model_validate(response.json())
    assert response.json()["run_id"] == "run-001"


@pytest.mark.django_db
def test_get_run_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.get("/api/w/ws1/opps/opp-1/runs/run-001")
    assert response.status_code == 404


@pytest.mark.django_db
def test_get_run_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator-r2@example.com"),
    )
    response = client.get("/api/w/ws1/opps/opp-1/runs/run-001")
    assert response.status_code == 401


@pytest.mark.django_db
def test_get_run_404_unknown_run_id(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.list_opp_runs_for_workspace",
        lambda workspace, slug: _FAKE_RUNS,
    )
    response = client.get("/api/w/ws1/opps/opp-1/runs/run-999")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


@pytest.mark.django_db
def test_get_run_404_unknown_slug(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.list_opp_runs_for_workspace",
        lambda workspace, slug: [],
    )
    response = client.get("/api/w/ws1/opps/no-such/runs/run-001")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Task 2.1.9 — DELETE /w/{ws}/opps/{slug}/runs/{run_id}
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_run_happy_path(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.delete_run_by_id",
        lambda workspace, slug, run_id: None,
    )
    response = client.delete("/api/w/ws1/opps/opp-1/runs/run-001")
    assert response.status_code == 204


@pytest.mark.django_db
def test_delete_run_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.delete("/api/w/ws1/opps/opp-1/runs/run-001")
    assert response.status_code == 404


@pytest.mark.django_db
def test_delete_run_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator-r3@example.com"),
    )
    response = client.delete("/api/w/ws1/opps/opp-1/runs/run-001")
    assert response.status_code == 401


@pytest.mark.django_db
def test_delete_run_404_unknown_run(member_client, monkeypatch):
    client, _, _ = member_client

    def _raise(workspace, slug, run_id):
        raise FileNotFoundError("no run named 'run-999'")

    monkeypatch.setattr("apps.opps.api.delete_run_by_id", _raise)
    response = client.delete("/api/w/ws1/opps/opp-1/runs/run-999")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# Task 2.1.10 — GET /w/{ws}/opps/{slug}/steps/{skill}
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_step_happy_path(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.load_step_snapshot",
        lambda workspace, slug, skill, run_id=None: _FAKE_STEP,
    )
    response = client.get("/api/w/ws1/opps/opp-1/steps/idea-to-pdd")
    assert response.status_code == 200
    StepSnapshotOut.model_validate(response.json())
    assert response.json()["skill"] == "idea-to-pdd"


@pytest.mark.django_db
def test_get_step_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.get("/api/w/ws1/opps/opp-1/steps/idea-to-pdd")
    assert response.status_code == 404


@pytest.mark.django_db
def test_get_step_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator-s1@example.com"),
    )
    response = client.get("/api/w/ws1/opps/opp-1/steps/idea-to-pdd")
    assert response.status_code == 401


@pytest.mark.django_db
def test_get_step_404_unknown_opp(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.load_step_snapshot",
        lambda workspace, slug, skill, run_id=None: None,
    )
    response = client.get("/api/w/ws1/opps/no-such/steps/idea-to-pdd")
    assert response.status_code == 404


@pytest.mark.django_db
def test_get_step_404_unknown_skill(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.load_step_snapshot",
        lambda workspace, slug, skill, run_id=None: {"_not_found": "skill"},
    )
    response = client.get("/api/w/ws1/opps/opp-1/steps/no-such-skill")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# Task 2.1.11 — GET /w/{ws}/opps/{slug}/artifacts/{artifact_id}
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_artifact_happy_path(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.load_artifact_meta",
        lambda workspace, slug, artifact_id, run_id=None: _FAKE_ARTIFACT,
    )
    response = client.get("/api/w/ws1/opps/opp-1/artifacts/file-abc")
    assert response.status_code == 200
    ArtifactOut.model_validate(response.json())
    assert response.json()["id"] == "file-abc"


@pytest.mark.django_db
def test_get_artifact_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.get("/api/w/ws1/opps/opp-1/artifacts/file-abc")
    assert response.status_code == 404


@pytest.mark.django_db
def test_get_artifact_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator-a1@example.com"),
    )
    response = client.get("/api/w/ws1/opps/opp-1/artifacts/file-abc")
    assert response.status_code == 401


@pytest.mark.django_db
def test_get_artifact_404_unknown(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.load_artifact_meta",
        lambda workspace, slug, artifact_id, run_id=None: {"_not_found": True},
    )
    response = client.get("/api/w/ws1/opps/opp-1/artifacts/no-such")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# Task 2.1.12 — GET /w/{ws}/opps/{slug}/artifacts/{artifact_id}/download
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_download_artifact_happy_path(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.download_artifact_bytes",
        lambda workspace, slug, artifact_id: (b"hello world", "text/plain"),
    )
    response = client.get("/api/w/ws1/opps/opp-1/artifacts/file-abc/download")
    assert response.status_code == 200
    assert response["Content-Type"] == "text/plain"
    assert response.content == b"hello world"


@pytest.mark.django_db
def test_download_artifact_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator-a2@example.com"),
    )
    response = client.get("/api/w/ws1/opps/opp-1/artifacts/file-abc/download")
    assert response.status_code == 401


@pytest.mark.django_db
def test_download_artifact_404_unknown(member_client, monkeypatch):
    client, _, _ = member_client

    def _raise(workspace, slug, artifact_id):
        raise FileNotFoundError("artifact not found")

    monkeypatch.setattr("apps.opps.api.download_artifact_bytes", _raise)
    response = client.get("/api/w/ws1/opps/opp-1/artifacts/no-such/download")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# Task 2.1.13 — POST /w/{ws}/opps/{slug}/fork
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_fork_opp_happy_path(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.fork_opp_and_return",
        lambda workspace, user, slug, body: _FAKE_FORK_RESULT,
    )
    response = client.post(
        "/api/w/ws1/opps/opp-1/fork",
        data={"fork_at_phase": "design"},
        content_type="application/json",
    )
    assert response.status_code == 201
    OppForkOut.model_validate(response.json())
    assert response.json()["run_id"] == "run-002"


@pytest.mark.django_db
def test_fork_opp_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.post(
        "/api/w/ws1/opps/opp-1/fork",
        data={"fork_at_phase": "design"},
        content_type="application/json",
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_fork_opp_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator-f1@example.com"),
    )
    response = client.post(
        "/api/w/ws1/opps/opp-1/fork",
        data={"fork_at_phase": "design"},
        content_type="application/json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_fork_opp_400_invalid_phase(member_client, monkeypatch):
    from apps.opps.opp_forker import ForkOppError

    client, _, _ = member_client

    def _raise(workspace, user, slug, body):
        raise ForkOppError("invalid-phase", "unknown phase 'bad-phase'")

    monkeypatch.setattr("apps.opps.api.fork_opp_and_return", _raise)
    response = client.post(
        "/api/w/ws1/opps/opp-1/fork",
        data={"fork_at_phase": "bad-phase"},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/problem+json")


@pytest.mark.django_db
def test_fork_opp_409_no_runs(member_client, monkeypatch):
    from apps.opps.opp_forker import ForkOppError

    client, _, _ = member_client

    def _raise(workspace, user, slug, body):
        raise ForkOppError("no-runs", "no runs to fork from")

    monkeypatch.setattr("apps.opps.api.fork_opp_and_return", _raise)
    response = client.post(
        "/api/w/ws1/opps/opp-1/fork",
        data={"fork_at_phase": "design"},
        content_type="application/json",
    )
    assert response.status_code == 409
    assert response["Content-Type"].startswith("application/problem+json")


@pytest.mark.django_db
def test_fork_opp_404_unknown_run(member_client, monkeypatch):
    from apps.opps.opp_forker import ForkOppError

    client, _, _ = member_client

    def _raise(workspace, user, slug, body):
        raise ForkOppError("source-run-not-found", "run not found")

    monkeypatch.setattr("apps.opps.api.fork_opp_and_return", _raise)
    response = client.post(
        "/api/w/ws1/opps/opp-1/fork",
        data={"fork_at_phase": "design", "source_run_id": "run-999"},
        content_type="application/json",
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_fork_opp_forwards_edits_to_forker(member_client, monkeypatch):
    """A5: body.edits must be forwarded as list[dict] to opp_forker.fork_opp."""
    from types import SimpleNamespace

    client, workspace, _user = member_client

    captured: dict = {}

    def _spy_fork_opp(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            opp_slug="opp-1",
            new_run_id="run-002",
            new_run_folder_id="folder-run-002",
            working_session=SimpleNamespace(slug="sess-xyz"),
        )

    # Stub external dependencies of fork_opp_and_return so it reaches the call.
    monkeypatch.setattr(
        "apps.opps.access.resolve_ace_root_folder_id",
        lambda ws: "ace-root-folder-id",
    )
    monkeypatch.setattr(
        "apps.opps.drive_client.get_drive_client",
        lambda workspace: object(),
    )
    monkeypatch.setattr("apps.opps.opp_forker.fork_opp", _spy_fork_opp)

    response = client.post(
        "/api/w/ws1/opps/opp-1/fork",
        data={
            "fork_at_phase": "design",
            "edits": [
                {"row_id": "row-7", "new_answer": "Q4 2026"},
                {"row_id": "row-12", "new_answer": "alpha-only"},
            ],
        },
        content_type="application/json",
    )

    assert response.status_code == 201, response.content
    # `override_reasoning` defaults to "" when not supplied in the request
    # body — the Pydantic OppForkEditIn schema fills it in.
    assert captured.get("edits") == [
        {"row_id": "row-7", "new_answer": "Q4 2026", "override_reasoning": ""},
        {"row_id": "row-12", "new_answer": "alpha-only", "override_reasoning": ""},
    ]
    # Sanity: other fields still flow through.
    assert captured.get("source_slug") == "opp-1"
    assert captured.get("fork_at_phase") == "design"


@pytest.mark.django_db
def test_fork_opp_empty_edits_passes_none(member_client, monkeypatch):
    """A5: an empty edits list (or omitted) should pass None to the forker."""
    from types import SimpleNamespace

    client, _workspace, _user = member_client

    captured: dict = {}

    def _spy_fork_opp(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            opp_slug="opp-1",
            new_run_id="run-002",
            new_run_folder_id="folder-run-002",
            working_session=SimpleNamespace(slug="sess-xyz"),
        )

    monkeypatch.setattr(
        "apps.opps.access.resolve_ace_root_folder_id",
        lambda ws: "ace-root-folder-id",
    )
    monkeypatch.setattr(
        "apps.opps.drive_client.get_drive_client",
        lambda workspace: object(),
    )
    monkeypatch.setattr("apps.opps.opp_forker.fork_opp", _spy_fork_opp)

    response = client.post(
        "/api/w/ws1/opps/opp-1/fork",
        data={"fork_at_phase": "design"},
        content_type="application/json",
    )

    assert response.status_code == 201, response.content
    assert captured.get("edits") is None


# ---------------------------------------------------------------------------
# Task 2.1.14 — GET /w/{ws}/opps/{slug}/fork/status
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_fork_status_happy_path(member_client, monkeypatch):
    client, _, _ = member_client
    fake_progress = {"status": "copying", "progress": 0.5, "files_total": 10, "files_copied": 5}
    monkeypatch.setattr(
        "django.core.cache.cache.get",
        lambda key: fake_progress,
    )
    response = client.get("/api/w/ws1/opps/opp-1/fork/status?source_run_id=run-001")
    assert response.status_code == 200
    ForkProgress.model_validate(response.json())
    assert response.json()["status"] == "copying"


@pytest.mark.django_db
def test_fork_status_unknown_when_no_cache(member_client):
    client, _, _ = member_client
    # No monkeypatch — cache.get returns None → status="unknown"
    response = client.get("/api/w/ws1/opps/opp-1/fork/status?source_run_id=run-999")
    assert response.status_code == 200
    assert response.json()["status"] == "unknown"


@pytest.mark.django_db
def test_fork_status_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator-fs1@example.com"),
    )
    response = client.get("/api/w/ws1/opps/opp-1/fork/status")
    assert response.status_code == 401


@pytest.mark.django_db
def test_fork_status_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.get("/api/w/ws1/opps/opp-1/fork/status")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Task 2.1.15 — GET /w/{ws}/opps/{slug}/scorecard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_scorecard_happy_path(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.load_scorecard_for_opp",
        lambda workspace, slug: _FAKE_SCORECARD,
    )
    response = client.get("/api/w/ws1/opps/opp-1/scorecard")
    assert response.status_code == 200
    ScorecardOut.model_validate(response.json())
    assert response.json()["score"] == 87


@pytest.mark.django_db
def test_get_scorecard_null_when_no_scorecard(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.load_scorecard_for_opp",
        lambda workspace, slug: {},
    )
    response = client.get("/api/w/ws1/opps/opp-1/scorecard")
    assert response.status_code == 200
    assert response.json() is None


@pytest.mark.django_db
def test_get_scorecard_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.get("/api/w/ws1/opps/opp-1/scorecard")
    assert response.status_code == 404


@pytest.mark.django_db
def test_get_scorecard_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator-sc1@example.com"),
    )
    response = client.get("/api/w/ws1/opps/opp-1/scorecard")
    assert response.status_code == 401


@pytest.mark.django_db
def test_get_scorecard_404_unknown_opp(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.load_scorecard_for_opp",
        lambda workspace, slug: None,
    )
    response = client.get("/api/w/ws1/opps/no-such/scorecard")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# Task 2.1.16 — POST /w/{ws}/opps/{slug}/gates/{skill}
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_record_gate_happy_path(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.record_gate_decision",
        lambda workspace, slug, skill, body, user: _FAKE_GATE,
    )
    response = client.post(
        "/api/w/ws1/opps/opp-1/gates/idea-to-pdd",
        data={"decision": "approved"},
        content_type="application/json",
    )
    assert response.status_code == 200
    GateOut.model_validate(response.json())
    assert response.json()["decision"] == "approved"


@pytest.mark.django_db
def test_record_gate_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.post(
        "/api/w/ws1/opps/opp-1/gates/idea-to-pdd",
        data={"decision": "approved"},
        content_type="application/json",
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_record_gate_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator-g1@example.com"),
    )
    response = client.post(
        "/api/w/ws1/opps/opp-1/gates/idea-to-pdd",
        data={"decision": "approved"},
        content_type="application/json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_record_gate_422_invalid_decision(member_client):
    client, _, _ = member_client
    response = client.post(
        "/api/w/ws1/opps/opp-1/gates/idea-to-pdd",
        data={"decision": "maybe"},
        content_type="application/json",
    )
    assert response.status_code == 422


@pytest.mark.django_db
def test_record_gate_404_unknown_opp(member_client, monkeypatch):
    client, _, _ = member_client

    def _raise(workspace, slug, skill, body, user):
        raise FileNotFoundError(f"no opp named {slug!r}")

    monkeypatch.setattr("apps.opps.api.record_gate_decision", _raise)
    response = client.post(
        "/api/w/ws1/opps/no-such/gates/idea-to-pdd",
        data={"decision": "approved"},
        content_type="application/json",
    )
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# Task 2.1.17 — GET /w/{ws}/opps/{slug}/compare
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_compare_runs_happy_path(member_client, monkeypatch):
    client, _, _ = member_client
    fake_compare = {
        "slug": "opp-1",
        "run_ids": ["run-001", "run-002"],
        "snapshots": [_FAKE_SNAPSHOT_A, _FAKE_SNAPSHOT_B],
    }
    monkeypatch.setattr(
        "apps.opps.api.compare_opp_runs",
        lambda workspace, slug, run_ids: fake_compare,
    )
    response = client.get(
        "/api/w/ws1/opps/opp-1/compare",
        {"run_ids": ["run-001", "run-002"]},
    )
    assert response.status_code == 200
    result = OppCompareOut.model_validate(response.json())
    assert len(result.snapshots) == 2


@pytest.mark.django_db
def test_compare_runs_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.get("/api/w/ws1/opps/opp-1/compare?run_ids=run-001&run_ids=run-002")
    assert response.status_code == 404


@pytest.mark.django_db
def test_compare_runs_400_too_few_run_ids(member_client):
    client, _, _ = member_client
    response = client.get("/api/w/ws1/opps/opp-1/compare?run_ids=run-001")
    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# Task 2.1.18 — POST /w/{ws}/opps/{slug}/actions/seed-chat
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_seed_chat_happy_path(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.seed_chat_for_step",
        lambda workspace, slug, user, body: {"session_slug": "sess-abc"},
    )
    response = client.post(
        "/api/w/ws1/opps/opp-1/actions/seed-chat",
        data={"step_skill": "idea-to-pdd"},
        content_type="application/json",
    )
    assert response.status_code == 201
    SeedChatOut.model_validate(response.json())
    assert response.json()["session_slug"] == "sess-abc"


@pytest.mark.django_db
def test_seed_chat_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.post(
        "/api/w/ws1/opps/opp-1/actions/seed-chat",
        data={"step_skill": "idea-to-pdd"},
        content_type="application/json",
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_seed_chat_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator-seed1@example.com"),
    )
    response = client.post(
        "/api/w/ws1/opps/opp-1/actions/seed-chat",
        data={"step_skill": "idea-to-pdd"},
        content_type="application/json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_seed_chat_422_empty_step_skill(member_client):
    client, _, _ = member_client
    response = client.post(
        "/api/w/ws1/opps/opp-1/actions/seed-chat",
        data={"step_skill": ""},
        content_type="application/json",
    )
    assert response.status_code == 422


@pytest.mark.django_db
def test_seed_chat_404_opp_not_found(member_client, monkeypatch):
    client, _, _ = member_client

    def _raise(workspace, slug, user, body):
        raise FileNotFoundError("no opp named 'no-such'")

    monkeypatch.setattr("apps.opps.api.seed_chat_for_step", _raise)
    response = client.post(
        "/api/w/ws1/opps/no-such/actions/seed-chat",
        data={"step_skill": "idea-to-pdd"},
        content_type="application/json",
    )
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# POST /w/{ws}/opps/{slug}/actions/seeded-run
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_seeded_run_happy_path(member_client, monkeypatch):
    client, _, _ = member_client
    captured = {}

    def _fake(workspace, slug, user, body):
        captured["only"] = body.only
        captured["golden"] = body.golden_run_id
        return {
            "session_slug": "sess-seeded",
            "assistant_message_id": 4242,
            "run_id": "20260601-1200",
        }

    driven = {}
    monkeypatch.setattr("apps.opps.api.seed_run_for_opp", _fake)
    monkeypatch.setattr(
        "apps.sessions.turn_driver.start_turn_subprocess",
        lambda mid: driven.update(mid=mid),
    )
    response = client.post(
        "/api/w/ws1/opps/opp-1/actions/seeded-run",
        data={"golden_run_id": "20260531-2258", "only": "3,4,6"},
        content_type="application/json",
    )
    assert response.status_code == 202
    SeededRunOut.model_validate(response.json())
    assert response.json()["session_slug"] == "sess-seeded"
    assert response.json()["assistant_message_id"] == 4242
    assert response.json()["run_id"] == "20260601-1200"
    assert captured == {"only": "3,4,6", "golden": "20260531-2258"}
    # The turn driver was launched (detached) against the assistant placeholder.
    assert driven == {"mid": 4242}


@pytest.mark.django_db
def test_seeded_run_routes_through_the_canopy_dispatch_seam(member_client, monkeypatch):
    """The route must call run_dispatch.start_turn, not the subprocess directly —
    otherwise flipping CANOPY_RUN_EXECUTION has no effect on the seeded run."""
    client, _, _ = member_client
    called = []
    monkeypatch.setattr("apps.canopy.run_dispatch.start_turn", lambda mid: called.append(mid))
    # Belt and braces: if the route ever regresses to calling the subprocess
    # directly, patching only the seam would let it spawn a REAL detached
    # `manage.py drive_turn` in CI before the assertion below fired.
    spawned = []
    monkeypatch.setattr(
        "apps.sessions.turn_driver.start_turn_subprocess", lambda mid: spawned.append(mid)
    )
    monkeypatch.setattr(
        "apps.opps.api.seed_run_for_opp",
        lambda *a, **k: {"session_slug": "s", "assistant_message_id": 4242, "run_id": "r"},
    )
    response = client.post(
        "/api/w/ws1/opps/opp-1/actions/seeded-run",
        data={"golden_run_id": "20260531-2258"},
        content_type="application/json",
    )
    assert response.status_code == 202
    assert called == [4242]
    assert spawned == []  # the route went through the seam, not around it


@pytest.mark.django_db
def test_seeded_run_defaults_only_to_3_4_6(member_client, monkeypatch):
    client, _, _ = member_client
    captured = {}

    def _fake(workspace, slug, user, body):
        captured["only"] = body.only
        return {"session_slug": "s", "assistant_message_id": 1, "run_id": "r"}

    monkeypatch.setattr("apps.opps.api.seed_run_for_opp", _fake)
    monkeypatch.setattr("apps.sessions.turn_driver.start_turn_subprocess", lambda mid: None)
    response = client.post(
        "/api/w/ws1/opps/opp-1/actions/seeded-run",
        data={"golden_run_id": "20260531-2258"},
        content_type="application/json",
    )
    assert response.status_code == 202
    assert captured["only"] == "3,4,6"


@pytest.mark.django_db
def test_seeded_run_skip_evals_defaults_true(member_client, monkeypatch):
    """Seeded runs are the test harness; evals don't gate, so they default off."""
    client, _, _ = member_client
    captured = {}

    def _fake(workspace, slug, user, body):
        captured["skip_evals"] = body.skip_evals
        return {"session_slug": "s", "assistant_message_id": 1, "run_id": "r"}

    monkeypatch.setattr("apps.opps.api.seed_run_for_opp", _fake)
    monkeypatch.setattr("apps.sessions.turn_driver.start_turn_subprocess", lambda mid: None)
    response = client.post(
        "/api/w/ws1/opps/opp-1/actions/seeded-run",
        data={"golden_run_id": "20260531-2258"},
        content_type="application/json",
    )
    assert response.status_code == 202
    assert captured["skip_evals"] is True


@pytest.mark.django_db
def test_seeded_run_skip_evals_can_be_disabled(member_client, monkeypatch):
    client, _, _ = member_client
    captured = {}

    def _fake(workspace, slug, user, body):
        captured["skip_evals"] = body.skip_evals
        return {"session_slug": "s", "assistant_message_id": 1, "run_id": "r"}

    monkeypatch.setattr("apps.opps.api.seed_run_for_opp", _fake)
    monkeypatch.setattr("apps.sessions.turn_driver.start_turn_subprocess", lambda mid: None)
    response = client.post(
        "/api/w/ws1/opps/opp-1/actions/seeded-run",
        data={"golden_run_id": "20260531-2258", "skip_evals": False},
        content_type="application/json",
    )
    assert response.status_code == 202
    assert captured["skip_evals"] is False


@pytest.mark.django_db
def test_seeded_run_422_bad_only_shape(member_client):
    client, _, _ = member_client
    response = client.post(
        "/api/w/ws1/opps/opp-1/actions/seeded-run",
        data={"golden_run_id": "20260531-2258", "only": "three,4"},
        content_type="application/json",
    )
    assert response.status_code == 422


@pytest.mark.django_db
def test_seeded_run_422_empty_golden(member_client):
    client, _, _ = member_client
    response = client.post(
        "/api/w/ws1/opps/opp-1/actions/seeded-run",
        data={"golden_run_id": ""},
        content_type="application/json",
    )
    assert response.status_code == 422


@pytest.mark.django_db
def test_seeded_run_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.post(
        "/api/w/ws1/opps/opp-1/actions/seeded-run",
        data={"golden_run_id": "20260531-2258"},
        content_type="application/json",
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_seeded_run_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator-seeded1@example.com"),
    )
    response = client.post(
        "/api/w/ws1/opps/opp-1/actions/seeded-run",
        data={"golden_run_id": "20260531-2258"},
        content_type="application/json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_seeded_run_404_golden_not_found(member_client, monkeypatch):
    client, _, _ = member_client

    def _raise(workspace, slug, user, body):
        raise FileNotFoundError("run 20260101-0000 not found")

    monkeypatch.setattr("apps.opps.api.seed_run_for_opp", _raise)
    response = client.post(
        "/api/w/ws1/opps/opp-1/actions/seeded-run",
        data={"golden_run_id": "20260101-0000"},
        content_type="application/json",
    )
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


@pytest.mark.django_db
def test_seed_run_for_opp_forks_then_plain_resume(member_client, monkeypatch):
    """The real seed_run_for_opp forks the golden with the structural shape
    (run_phases + no session), then seeds a PLAIN resume command — no
    --seed-from/--only flags — and returns the new run_id (ace#672)."""
    from apps.opps import api as opps_api
    from apps.opps.opp_forker import ForkOppResult
    from apps.sessions.models import Session

    _, workspace, user = member_client
    captured: dict = {}

    def _fake_fork(**kwargs):
        captured.update(kwargs)
        return ForkOppResult(
            opp_slug=kwargs["source_slug"],
            new_run_id="20260601-0900",
            new_run_folder_id="folder-new",
            working_session=None,
        )

    monkeypatch.setattr("apps.opps.access.resolve_ace_root_folder_id", lambda ws: "ace-root")
    monkeypatch.setattr("apps.opps.drive_client.get_drive_client", lambda workspace: object())
    monkeypatch.setattr("apps.opps.opp_forker.fork_opp", _fake_fork)
    monkeypatch.setattr(
        "apps.opps.skills.all_phases",
        lambda: ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"],
    )

    body = SeededRunIn(golden_run_id="20260531-2258", only="3,4,6", skip_evals=False)
    result = opps_api.seed_run_for_opp(workspace, "opp-1", user, body)

    # Fork was asked for the structural shape: target ordinals pending, no
    # session, fork at the lowest ordinal's phase (p3).
    assert captured["run_phases"] == [3, 4, 6]
    assert captured["create_session"] is False
    assert captured["fork_at_phase"] == "p3"
    assert captured["source_run_id"] == "20260531-2258"
    assert captured["mode"] == "keep-all"

    # Returns the NEW forked run-id.
    assert result["run_id"] == "20260601-0900"

    # The seeded turn is a PLAIN resume — no flag interpretation.
    session = Session.objects.get(slug=result["session_slug"])
    turn0 = session.messages.get(turn_index=0)
    assert turn0.plaintext == "/ace:run opp-1/20260601-0900"
    assert "--seed-from" not in turn0.plaintext
    assert "--only" not in turn0.plaintext
    # Assistant placeholder is pending for the headless driver.
    assert session.messages.get(turn_index=1).status == "pending"


@pytest.mark.django_db
def test_seed_run_for_opp_default_skips_evals(member_client, monkeypatch):
    """With the default skip_evals=True, the seeded resume appends --no-evals
    (seeded runs are the test harness; evals don't gate)."""
    from apps.opps import api as opps_api
    from apps.opps.opp_forker import ForkOppResult
    from apps.sessions.models import Session

    _, workspace, user = member_client

    monkeypatch.setattr("apps.opps.access.resolve_ace_root_folder_id", lambda ws: "ace-root")
    monkeypatch.setattr("apps.opps.drive_client.get_drive_client", lambda workspace: object())
    monkeypatch.setattr(
        "apps.opps.opp_forker.fork_opp",
        lambda **kw: ForkOppResult(
            opp_slug=kw["source_slug"], new_run_id="20260601-0900",
            new_run_folder_id="folder-new", working_session=None,
        ),
    )
    monkeypatch.setattr(
        "apps.opps.skills.all_phases",
        lambda: ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"],
    )

    body = SeededRunIn(golden_run_id="20260531-2258", only="3,4,6")  # skip_evals defaults True
    result = opps_api.seed_run_for_opp(workspace, "opp-1", user, body)

    session = Session.objects.get(slug=result["session_slug"])
    assert session.messages.get(turn_index=0).plaintext == "/ace:run opp-1/20260601-0900 --no-evals"


# ---------------------------------------------------------------------------
# Nova preflight — ace-web#636
# ---------------------------------------------------------------------------


def test_nova_preflight_raises_when_nova_phase_selected_and_auth_dead(monkeypatch):
    from apps.opps import api as opps_api

    monkeypatch.setattr("apps.common.nova_auth_flow.validate_any_token", lambda: False)
    phases = ["p1", "p2", "commcare-setup", "p4"]
    with pytest.raises(opps_api.NovaAuthInvalid):
        opps_api.nova_preflight([3, 4], phases)


def test_nova_preflight_skips_when_nova_phase_not_selected(monkeypatch):
    from apps.opps import api as opps_api

    probed = []
    monkeypatch.setattr(
        "apps.common.nova_auth_flow.validate_any_token",
        lambda: probed.append(1) is None and False,
    )
    opps_api.nova_preflight([4], ["p1", "p2", "commcare-setup", "p4"])
    assert probed == []  # no live probe when the Nova phase isn't in the run


def test_nova_preflight_skips_when_registry_lacks_nova_phase(monkeypatch):
    from apps.opps import api as opps_api

    monkeypatch.setattr("apps.common.nova_auth_flow.validate_any_token", lambda: False)
    opps_api.nova_preflight([3], ["p1", "p2", "p3"])  # must not raise


def test_nova_preflight_passes_when_auth_valid(monkeypatch):
    from apps.opps import api as opps_api

    monkeypatch.setattr("apps.common.nova_auth_flow.validate_any_token", lambda: True)
    opps_api.nova_preflight([3], ["p1", "p2", "commcare-setup"])  # must not raise


@pytest.mark.django_db
def test_seeded_run_409_nova_auth_invalid(member_client, monkeypatch):
    """A dead Nova auth turns the seeded-run action into 409 nova_auth_invalid
    instead of minting a run doomed to halt at Phase 3 (ace-web#636)."""
    from apps.opps import api as opps_api

    client, _, _ = member_client

    def _raise(workspace, slug, user, body):
        raise opps_api.NovaAuthInvalid("Nova auth is not valid")

    monkeypatch.setattr("apps.opps.api.seed_run_for_opp", _raise)
    response = client.post(
        "/api/w/ws1/opps/opp-1/actions/seeded-run",
        data={"golden_run_id": "20260531-2258"},
        content_type="application/json",
    )
    assert response.status_code == 409
    assert response["Content-Type"].startswith("application/problem+json")
    body = response.json()
    assert body["extras"]["code"] == "nova_auth_invalid"
    assert "nova/initiate" in body["extras"]["reconnect_url"]


@pytest.mark.django_db
def test_seed_run_for_opp_rejects_out_of_range_only(member_client, monkeypatch):
    """An --only ordinal past the phase count raises ValueError (→ 404 at the route)."""
    from apps.opps import api as opps_api

    _, workspace, user = member_client
    monkeypatch.setattr("apps.opps.access.resolve_ace_root_folder_id", lambda ws: "ace-root")
    monkeypatch.setattr("apps.opps.drive_client.get_drive_client", lambda workspace: object())
    monkeypatch.setattr("apps.opps.skills.all_phases", lambda: ["p1", "p2", "p3"])

    body = SeededRunIn(golden_run_id="20260531-2258", only="9")
    with pytest.raises(ValueError, match="out of range"):
        opps_api.seed_run_for_opp(workspace, "opp-1", user, body)


# ---------------------------------------------------------------------------
# Task 2.1.19 — GET /w/{ws}/opps/{slug}/health
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_opp_health_reachable(member_client, monkeypatch):
    client, _, _ = member_client
    now = dt.datetime(2026, 5, 14, 10, 0, tzinfo=dt.UTC)
    monkeypatch.setattr(
        "apps.opps.api.probe_opp_health",
        lambda workspace, slug: {"reachable": True, "last_checked_at": now, "error": None},
    )
    response = client.get("/api/w/ws1/opps/opp-1/health")
    assert response.status_code == 200
    result = OppHealthOut.model_validate(response.json())
    assert result.reachable is True
    assert result.error is None


@pytest.mark.django_db
def test_opp_health_unreachable(member_client, monkeypatch):
    client, _, _ = member_client
    now = dt.datetime(2026, 5, 14, 10, 0, tzinfo=dt.UTC)
    monkeypatch.setattr(
        "apps.opps.api.probe_opp_health",
        lambda workspace, slug: {
            "reachable": False, "last_checked_at": now, "error": "connection refused",
        },
    )
    response = client.get("/api/w/ws1/opps/opp-1/health")
    assert response.status_code == 200
    result = OppHealthOut.model_validate(response.json())
    assert result.reachable is False
    assert result.error == "connection refused"


@pytest.mark.django_db
def test_opp_health_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.get("/api/w/ws1/opps/opp-1/health")
    assert response.status_code == 404


@pytest.mark.django_db
def test_opp_health_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator-h1@example.com"),
    )
    response = client.get("/api/w/ws1/opps/opp-1/health")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Task 2.1.20 — POST /w/{ws}/opps/{slug}/snapshot/invalidate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invalidate_snapshot_happy_path(db, client, monkeypatch):
    """Staff user (write-global) can invalidate the cache."""
    staff_user = User.objects.create_user(email="staff@example.com")
    staff_user.is_staff = True
    staff_user.save(update_fields=["is_staff"])
    workspace = Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=staff_user,
    )
    WorkspaceMembership.objects.create(workspace=workspace, user=staff_user, role="owner")
    client.force_login(staff_user)
    monkeypatch.setattr(
        "apps.opps.api.invalidate_opp_snapshot_cache",
        lambda workspace: None,
    )
    response = client.post("/api/w/ws1/opps/opp-1/snapshot/invalidate")
    assert response.status_code == 204


@pytest.mark.django_db
def test_invalidate_snapshot_403_non_admin(member_client, monkeypatch):
    """Regular editor cannot invalidate."""
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api.invalidate_opp_snapshot_cache",
        lambda workspace: None,
    )
    response = client.post("/api/w/ws1/opps/opp-1/snapshot/invalidate")
    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/problem+json")


@pytest.mark.django_db
def test_invalidate_snapshot_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator-inv1@example.com"),
    )
    response = client.post("/api/w/ws1/opps/opp-1/snapshot/invalidate")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Run execution state on the runs list (spec 2026-07-26, item 6)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_run_execution_for_is_none_when_the_run_never_went_to_canopy(member_client):
    from apps.opps.api import _run_execution_for
    from apps.sessions.models import Session

    _, workspace, user = member_client
    Session.create_with_owner(
        owner=user, workspace=workspace, source="web",
        opp_slug="opp-a", opp_run_id="run-1",  # no canopy_session_id
    )
    assert _run_execution_for(workspace, "opp-a", "run-1") is None


@pytest.mark.django_db
def test_run_execution_for_reports_the_canopy_state(member_client, monkeypatch):
    from apps.opps.api import _run_execution_for
    from apps.sessions.models import Session

    _, workspace, user = member_client
    Session.create_with_owner(
        owner=user, workspace=workspace, source="web",
        opp_slug="opp-a", opp_run_id="run-1", canopy_session_id="sess-1",
    )
    monkeypatch.setattr(
        "apps.canopy.run_state.execution_state",
        lambda s: {"state": "no_runner_configured", "detail": "no runner",
                   "canopy_turn_id": "turn-1", "canopy_session_id": "sess-1"},
    )
    assert _run_execution_for(workspace, "opp-a", "run-1")["state"] == "no_runner_configured"


@pytest.mark.django_db
def test_run_execution_for_never_raises(member_client, monkeypatch):
    """The runs list is the opp workbench's primary read. A bad minute on
    canopy must degrade the badge, not 500 the whole page."""
    from apps.opps.api import _run_execution_for
    from apps.sessions.models import Session

    _, workspace, user = member_client
    Session.create_with_owner(
        owner=user, workspace=workspace, source="web",
        opp_slug="opp-a", opp_run_id="run-1", canopy_session_id="sess-1",
    )
    monkeypatch.setattr(
        "apps.canopy.run_state.execution_state",
        lambda s: (_ for _ in ()).throw(RuntimeError("kaboom")),
    )
    assert _run_execution_for(workspace, "opp-a", "run-1") is None


@pytest.mark.django_db
def test_run_execution_for_does_not_write(member_client, monkeypatch):
    """A list read must not reconcile — `reconcile_session` writes rows, and a
    GET of the opp page is not permission to mutate every run under it."""
    from apps.opps.api import _run_execution_for
    from apps.sessions.models import Session

    _, workspace, user = member_client
    Session.create_with_owner(
        owner=user, workspace=workspace, source="web",
        opp_slug="opp-a", opp_run_id="run-1", canopy_session_id="sess-1",
    )
    monkeypatch.setattr(
        "apps.canopy.run_state.execution_state",
        lambda s: {"state": "queued", "detail": "", "canopy_turn_id": "t",
                   "canopy_session_id": "sess-1"},
    )
    import apps.canopy.run_state as _rs
    monkeypatch.setattr(
        _rs, "reconcile_session",
        lambda s: (_ for _ in ()).throw(AssertionError("the list read reconciled")),
    )
    assert _run_execution_for(workspace, "opp-a", "run-1")["state"] == "queued"


@pytest.mark.django_db
def test_runs_list_carries_the_execution_state(member_client, monkeypatch):
    """The enrichment must actually reach the payload, or the frontend badge is
    dead code: `RunSummary.execution` would always be undefined."""
    from apps.opps import api as opps_api
    from apps.opps.sync import RunSummary

    _, workspace, _user = member_client
    monkeypatch.setattr(
        "apps.opps.access.resolve_ace_root_folder_id", lambda ws: "root-1",
    )
    monkeypatch.setattr("apps.opps.drive_client.get_drive_client", lambda workspace: object())
    monkeypatch.setattr(
        "apps.opps.sync.list_opp_runs",
        lambda drive, *, ace_root_folder_id, opp_slug: [
            RunSummary(
                run_id="run-1", folder_id="f", current_phase=None, current_step=None,
                mode=None, last_actor=None, last_actor_at=None,
            ),
        ],
    )
    monkeypatch.setattr(
        opps_api, "_run_execution_for",
        lambda ws, slug, run_id: {"state": "no_runner_configured", "detail": "no runner",
                                  "canopy_turn_id": "t", "canopy_session_id": "s"},
    )
    runs = opps_api.list_opp_runs_for_workspace(workspace, "opp-a")
    assert runs[0]["execution"]["state"] == "no_runner_configured"


# ---------------------------------------------------------------------------
# Public per-run summary — internal links are member-only
#
# The footer's "See the full build process" pointed at the Workbench,
# which 404s (not "sign in") for anyone who isn't a signed-in member —
# and ace-web rejects non-@dimagi.com sign-ins at the OAuth callback, so
# for an external reviewer it can never work. Indistinguishable from
# "this run doesn't exist".
# ---------------------------------------------------------------------------


def _summary_drive():
    from apps.opps.tests.fixtures.fake_drive import FakeDriveClient

    return FakeDriveClient.from_tree({
        "ACE": {
            "turmeric": {
                "opp.yaml": "display_name: Turmeric\nslug: turmeric\n",
                "runs": {"20260503-0835": {"run_state.yaml": "phases: {}\n"}},
            },
        },
    })


@pytest.fixture
def summary_workspace(db, monkeypatch):
    from django.core.cache import cache

    cache.clear()
    drive = _summary_drive()
    creator = User.objects.create_user(email="summary-creator@example.com")
    workspace = Workspace.objects.create(
        slug="summary-ws", display_name="Summary WS",
        drive_root_folder_id=drive.folder_id("ACE"), created_by=creator,
    )
    monkeypatch.setattr(
        "apps.opps.drive_client.get_drive_client", lambda workspace=None: drive,
    )
    return workspace


_SUMMARY_URL = "/api/opps/public/summary-ws/turmeric/runs/20260503-0835/summary"


@pytest.mark.django_db
def test_public_summary_serves_the_workbench_link_to_anonymous_visitors(
    client, summary_workspace
):
    """Gated links are shown and tagged, not hidden — an outsider who is
    shown nothing can't tell a gated link from a run that doesn't exist."""
    body = client.get(_SUMMARY_URL).json()
    assert body["opp"]["slug"] == "turmeric"
    assert body["workbench"]["url"] == "/w/summary-ws/opps/turmeric/runs/20260503-0835"
    assert body["workbench"]["access"] == "admin"
    assert body["viewer"] == {"is_member": False}


@pytest.mark.django_db
def test_public_summary_marks_a_member_so_the_page_drops_the_tags(
    client, summary_workspace
):
    user = User.objects.create_user(email="summary-member@example.com")
    WorkspaceMembership.objects.create(
        workspace=summary_workspace, user=user, role="editor",
    )
    client.force_login(user)
    body = client.get(_SUMMARY_URL).json()
    assert body["workbench"]["url"] == "/w/summary-ws/opps/turmeric/runs/20260503-0835"
    assert body["viewer"] == {"is_member": True}


@pytest.mark.django_db
def test_public_summary_cache_does_not_leak_the_member_variant(
    client, summary_workspace
):
    """Both variants are cached; the anonymous one must not be served a
    payload built for a member (or vice versa)."""
    user = User.objects.create_user(email="summary-member2@example.com")
    WorkspaceMembership.objects.create(
        workspace=summary_workspace, user=user, role="editor",
    )
    client.force_login(user)
    assert client.get(_SUMMARY_URL).json()["viewer"]["is_member"] is True
    client.logout()
    assert client.get(_SUMMARY_URL).json()["viewer"]["is_member"] is False


# ---------------------------------------------------------------------------
# Public decision reactions — the write half of the review surface
#
# #708 shipped 42 decision rows on the public summary with no way to say
# anything about any of them. These cover the endpoint: it writes where
# skills/feedback-ledger reads, it refuses what it can't route, it
# invalidates the cache it shares with the read path, and it is bounded.
# ---------------------------------------------------------------------------


_REACTION_DECISIONS = """\
schema_version: 4
opp: turmeric
run_id: '20260503-0835'
decisions:
  - id: visit-window
    phase: 1-design
    question: How long is the visit window?
    ai-default: 30 days
    evidence_basis: inferred
"""


@pytest.fixture
def reaction_workspace(db, monkeypatch):
    from django.core.cache import cache

    from apps.opps.tests.fixtures.fake_drive import FakeDriveClient

    cache.clear()
    drive = FakeDriveClient.from_tree({
        "ACE": {
            "turmeric": {
                "opp.yaml": "display_name: Turmeric\nslug: turmeric\n",
                "runs": {
                    "20260503-0835": {
                        "run_state.yaml": "phases: {}\n",
                        "decisions.yaml": _REACTION_DECISIONS,
                    },
                },
            },
        },
    })
    creator = User.objects.create_user(email="reaction-creator@example.com")
    Workspace.objects.create(
        slug="summary-ws", display_name="Summary WS",
        drive_root_folder_id=drive.folder_id("ACE"), created_by=creator,
    )
    monkeypatch.setattr(
        "apps.opps.drive_client.get_drive_client", lambda workspace=None: drive,
    )
    return drive


_REACTION_URL = (
    "/api/opps/public/summary-ws/turmeric/runs/20260503-0835"
    "/decisions/visit-window/reactions"
)


def _react(client, **body):
    payload = {"reviewer": "Anne Kuhlmann", "comment": "30 days is too long here."}
    payload.update(body)
    return client.post(_REACTION_URL, payload, content_type="application/json")


@pytest.mark.django_db
def test_anonymous_visitor_can_react_to_a_decision(client, reaction_workspace):
    """No auth, by design: the page a partner is handed has no login, and
    sending them somewhere else to respond is how a response never happens."""
    resp = _react(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["decision_id"] == "visit-window"
    assert body["feedback_ref"].endswith("/visit-window")
    assert body["reviewer"] == "Anne Kuhlmann"

    names = [f.name for f in reaction_workspace.list_files(
        reaction_workspace.folder_id("ACE/turmeric/feedback"),
    )]
    assert names and names[0].endswith(".yaml") and "-public-" in names[0]


@pytest.mark.django_db
def test_reaction_shows_up_on_the_next_summary_read(client, reaction_workspace):
    """The read path caches for 60s. A comment that takes a minute to
    appear reads as a comment that was lost."""
    summary_url = "/api/opps/public/summary-ws/turmeric/runs/20260503-0835/summary"
    assert client.get(summary_url).json()["reactions"]["total"] == 0
    _react(client)
    reactions = client.get(summary_url).json()["reactions"]
    assert reactions["total"] == 1
    assert reactions["by_decision"]["visit-window"][0]["reviewer"] == "Anne Kuhlmann"

    # …and again on the update path, which touches an existing record
    # rather than creating the folder (a different cache key).
    _react(client, comment="One more thought on the same row.")
    assert client.get(summary_url).json()["reactions"]["total"] == 2


@pytest.mark.django_db
def test_reaction_requires_a_name(client, reaction_workspace):
    assert _react(client, reviewer="").status_code == 422
    assert _react(client, reviewer=" a ").status_code == 400


@pytest.mark.django_db
def test_reaction_rejects_html(client, reaction_workspace):
    resp = _react(client, comment="<script>alert(1)</script> and also this")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_reaction_to_an_unknown_decision_404s(client, reaction_workspace):
    resp = client.post(
        "/api/opps/public/summary-ws/turmeric/runs/20260503-0835"
        "/decisions/no-such-row/reactions",
        {"reviewer": "Anne Kuhlmann", "comment": "this row does not exist"},
        content_type="application/json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_reaction_to_an_unknown_run_404s(client, reaction_workspace):
    resp = client.post(
        "/api/opps/public/summary-ws/turmeric/runs/no-such-run"
        "/decisions/visit-window/reactions",
        {"reviewer": "Anne Kuhlmann", "comment": "no such run"},
        content_type="application/json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_reaction_rate_limit_kicks_in(client, reaction_workspace):
    from apps.opps.api import PUBLIC_WRITE_BURST_LIMIT as REACTION_BURST_LIMIT

    for i in range(REACTION_BURST_LIMIT):
        assert _react(client, comment=f"comment number {i}").status_code == 201
    assert _react(client, comment="one over the line").status_code == 429


@pytest.mark.django_db
def test_oversized_comment_is_refused_before_any_drive_write(client, reaction_workspace):
    resp = _react(client, comment="x" * 5000)
    assert resp.status_code == 422
    root = reaction_workspace.folder_id("ACE/turmeric")
    assert "feedback" not in [f.name for f in reaction_workspace.list_files(root)]


# ---------------------------------------------------------------------------
# Public decision EDIT — anyone with the link may change an answer.
#
# The bar to start engaging with ACE has to be very low because it is
# speculative AI work, so this surface deliberately has no account
# requirement, no proposal state, and no promotion gate. What makes that
# safe is not permission — it is that every change is attributed,
# reversible, and lands in the same store a member's edit lands in.
# ---------------------------------------------------------------------------

_EDIT_URL = (
    "/api/opps/public/summary-ws/turmeric/runs/20260503-0835"
    "/decisions/visit-window/edit"
)
_SUMMARY_URL = "/api/opps/public/summary-ws/turmeric/runs/20260503-0835/summary"


def _edit(client, **body):
    payload = {"value": "14 days", "reviewer": "Anne Kuhlmann"}
    payload.update(body)
    return client.post(_EDIT_URL, payload, content_type="application/json")


def _overrides_rows(drive):
    import yaml as _yaml
    inputs = drive.folder_id("ACE/turmeric/inputs")
    f = next(x for x in drive.list_files(inputs) if x.name == "decision-overrides.yaml")
    return _yaml.safe_load(drive.get_content(f.id, f.mime_type).content)["overrides"]


@pytest.mark.django_db
def test_anonymous_visitor_can_change_a_decision(client, reaction_workspace):
    resp = _edit(client, reasoning="Two weeks matches the payment cycle.")
    assert resp.status_code == 200
    body = resp.json()
    assert body["override"] == "14 days"
    assert body["decided_by_name"] == "Anne Kuhlmann"
    assert body["decided_by_verified"] is False

    rows = _overrides_rows(reaction_workspace)
    assert [r["id"] for r in rows] == ["visit-window"]
    assert rows[0]["override"] == "14 days"
    assert rows[0]["ai_default"] == "30 days"
    assert rows[0]["decided_by_verified"] is False


@pytest.mark.django_db
def test_the_public_edit_lands_in_the_store_the_workbench_writes(
    client, reaction_workspace,
):
    """Not a parallel store: `inputs/decision-overrides.yaml` is exactly
    what the Workbench's authenticated editor saves and what the plugin's
    `decisions_append_rows` binds on the next run."""
    from apps.opps.decision_overrides import OVERRIDES_FILENAME, fetch_saved_overrides

    _edit(client)
    inputs = reaction_workspace.folder_id("ACE/turmeric/inputs")
    assert OVERRIDES_FILENAME in [f.name for f in reaction_workspace.list_files(inputs)]

    saved = fetch_saved_overrides(
        reaction_workspace, opp_folder_id=reaction_workspace.folder_id("ACE/turmeric"),
    )
    assert saved["visit-window"]["override"] == "14 days"


@pytest.mark.django_db
def test_a_signed_in_member_is_never_anonymous(client, reaction_workspace):
    """Logged in ⇒ the session identity wins and the typed name is
    discarded. Two names on one change is worse than one."""
    user = User.objects.create_user(email="ada@dimagi.com", display_name="Ada Member")
    client.force_login(user)
    resp = _edit(client, reviewer="Somebody Else")
    assert resp.status_code == 200
    body = resp.json()
    assert body["decided_by_name"] == "Ada Member"
    assert body["decided_by_verified"] is True
    assert _overrides_rows(reaction_workspace)[0]["decided_by"] == "ada@dimagi.com"


@pytest.mark.django_db
def test_reviewer_two_can_change_reviewer_one_and_the_first_answer_survives(
    client, reaction_workspace,
):
    """The whole model: last-writer-wins is acceptable only because the
    loser is recoverable."""
    _edit(client, value="14 days", reviewer="Anne Kuhlmann")
    resp = _edit(client, value="21 days", reviewer="Ben Okoro")
    assert resp.status_code == 200

    row = _overrides_rows(reaction_workspace)[0]
    assert row["override"] == "21 days"
    assert row["decided_by_name"] == "Ben Okoro"
    assert [h["override"] for h in row["history"]] == ["14 days"]
    assert row["history"][0]["decided_by_name"] == "Anne Kuhlmann"

    served = client.get(_SUMMARY_URL).json()["decision_edits"]["visit-window"]
    assert served["override"] == "21 days"
    assert [h["override"] for h in served["history"]] == ["14 days"]


@pytest.mark.django_db
def test_an_edit_is_reversible_from_the_ui(client, reaction_workspace):
    """Restoring the AI default is a normal edit, and leaves the trail
    rather than erasing it."""
    _edit(client, value="14 days", reviewer="Anne Kuhlmann")
    resp = _edit(client, value="30 days", reviewer="Anne Kuhlmann")
    assert resp.status_code == 200
    assert resp.json()["is_revert"] is True

    row = _overrides_rows(reaction_workspace)[0]
    assert row["override"] == "30 days"
    assert [h["override"] for h in row["history"]] == ["14 days"]


@pytest.mark.django_db
def test_an_edit_naming_an_unknown_decision_is_refused_not_stored(
    client, reaction_workspace,
):
    resp = client.post(
        "/api/opps/public/summary-ws/turmeric/runs/20260503-0835"
        "/decisions/no-such-row/edit",
        {"value": "whatever", "reviewer": "Anne Kuhlmann"},
        content_type="application/json",
    )
    assert resp.status_code == 404
    root = reaction_workspace.folder_id("ACE/turmeric")
    assert "inputs" not in [f.name for f in reaction_workspace.list_files(root)]


@pytest.mark.django_db
def test_an_anonymous_edit_requires_a_name(client, reaction_workspace):
    assert _edit(client, reviewer=None).status_code == 400
    assert _edit(client, reviewer=" a ").status_code == 400


@pytest.mark.django_db
def test_edit_rejects_html_rather_than_mangling_it(client, reaction_workspace):
    assert _edit(client, value="<b>14 days</b>").status_code == 400
    assert _edit(client, reasoning="<script>alert(1)</script>").status_code == 400


@pytest.mark.django_db
def test_oversized_edit_is_refused_before_any_drive_write(client, reaction_workspace):
    assert _edit(client, value="x" * 900).status_code == 422
    root = reaction_workspace.folder_id("ACE/turmeric")
    assert "inputs" not in [f.name for f in reaction_workspace.list_files(root)]


@pytest.mark.django_db
def test_edit_shows_up_on_the_next_summary_read(client, reaction_workspace):
    """The read path caches for 60s. A change that takes a minute to
    appear reads as a change that was lost."""
    assert client.get(_SUMMARY_URL).json()["decision_edits"] == {}
    _edit(client)
    assert client.get(_SUMMARY_URL).json()["decision_edits"]["visit-window"][
        "override"
    ] == "14 days"


@pytest.mark.django_db
def test_public_payload_never_carries_a_reviewer_email(client, reaction_workspace):
    user = User.objects.create_user(email="ada@dimagi.com", display_name="Ada Member")
    client.force_login(user)
    _edit(client)
    client.logout()
    served = client.get(_SUMMARY_URL).json()["decision_edits"]["visit-window"]
    assert "decided_by" not in served
    assert "ada@dimagi.com" not in json.dumps(served)


@pytest.mark.django_db
def test_edits_and_comments_share_one_per_ip_budget(client, reaction_workspace):
    """Two public write endpoints with separate budgets is just double
    the budget."""
    from apps.opps.api import PUBLIC_WRITE_BURST_LIMIT

    for i in range(PUBLIC_WRITE_BURST_LIMIT):
        assert _edit(client, value=f"{i} days").status_code == 200
    assert _react(client).status_code == 429
