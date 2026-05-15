import datetime as dt

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
        "apps.opps.api_v2.list_opp_cards", lambda workspace: fake_cards
    )

    response = client.get("/api/w/ws1/opps")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    # Validate the items round-trip through the Pydantic schema.
    [OppCardOut.model_validate(item) for item in body["items"]]
    assert body["total"] == 1


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
        "apps.opps.api_v2.load_rich_opp_snapshot",
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
        "apps.opps.api_v2.load_rich_opp_snapshot",
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
        "apps.opps.api_v2.load_rich_opp_snapshot",
        lambda workspace, slug, run_id=None: None,
    )
    response = client.get("/api/w/ws1/opps/no-such-opp")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"].endswith("/not-found")


# ---------------------------------------------------------------------------
# Task 2.1.4 — POST /w/{workspace_slug}/opps  (create opp)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_opp_happy_path(member_client, monkeypatch):
    client, workspace, user = member_client
    monkeypatch.setattr(
        "apps.opps.api_v2.create_opp_and_return_card",
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

    monkeypatch.setattr("apps.opps.api_v2.create_opp_and_return_card", _raise_conflict)
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
        "apps.opps.api_v2.patch_opp_and_return_card",
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

    monkeypatch.setattr("apps.opps.api_v2.patch_opp_and_return_card", _raise_not_found)
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
        "apps.opps.api_v2.delete_opp_by_slug",
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

    monkeypatch.setattr("apps.opps.api_v2.delete_opp_by_slug", _raise_not_found)
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
        "apps.opps.api_v2.list_opp_runs_for_workspace",
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
        "apps.opps.api_v2.list_opp_runs_for_workspace",
        lambda workspace, slug: [],
    )
    response = client.get("/api/w/ws1/opps/no-such/runs")
    assert response.status_code == 200
    assert response.json()["total"] == 0


# ---------------------------------------------------------------------------
# Task 2.1.8 — GET /w/{ws}/opps/{slug}/runs/{run_id}
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_run_happy_path(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api_v2.list_opp_runs_for_workspace",
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
        "apps.opps.api_v2.list_opp_runs_for_workspace",
        lambda workspace, slug: _FAKE_RUNS,
    )
    response = client.get("/api/w/ws1/opps/opp-1/runs/run-999")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


@pytest.mark.django_db
def test_get_run_404_unknown_slug(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api_v2.list_opp_runs_for_workspace",
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
        "apps.opps.api_v2.delete_run_by_id",
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

    monkeypatch.setattr("apps.opps.api_v2.delete_run_by_id", _raise)
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
        "apps.opps.api_v2.load_step_snapshot",
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
        "apps.opps.api_v2.load_step_snapshot",
        lambda workspace, slug, skill, run_id=None: None,
    )
    response = client.get("/api/w/ws1/opps/no-such/steps/idea-to-pdd")
    assert response.status_code == 404


@pytest.mark.django_db
def test_get_step_404_unknown_skill(member_client, monkeypatch):
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api_v2.load_step_snapshot",
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
        "apps.opps.api_v2.load_artifact_meta",
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
        "apps.opps.api_v2.load_artifact_meta",
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
        "apps.opps.api_v2.download_artifact_bytes",
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

    monkeypatch.setattr("apps.opps.api_v2.download_artifact_bytes", _raise)
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
        "apps.opps.api_v2.fork_opp_and_return",
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

    monkeypatch.setattr("apps.opps.api_v2.fork_opp_and_return", _raise)
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

    monkeypatch.setattr("apps.opps.api_v2.fork_opp_and_return", _raise)
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

    monkeypatch.setattr("apps.opps.api_v2.fork_opp_and_return", _raise)
    response = client.post(
        "/api/w/ws1/opps/opp-1/fork",
        data={"fork_at_phase": "design", "source_run_id": "run-999"},
        content_type="application/json",
    )
    assert response.status_code == 404


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
        "apps.opps.api_v2.load_scorecard_for_opp",
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
        "apps.opps.api_v2.load_scorecard_for_opp",
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
        "apps.opps.api_v2.load_scorecard_for_opp",
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
        "apps.opps.api_v2.record_gate_decision",
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

    monkeypatch.setattr("apps.opps.api_v2.record_gate_decision", _raise)
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
        "apps.opps.api_v2.compare_opp_runs",
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
        "apps.opps.api_v2.seed_chat_for_step",
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

    monkeypatch.setattr("apps.opps.api_v2.seed_chat_for_step", _raise)
    response = client.post(
        "/api/w/ws1/opps/no-such/actions/seed-chat",
        data={"step_skill": "idea-to-pdd"},
        content_type="application/json",
    )
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# Task 2.1.19 — GET /w/{ws}/opps/{slug}/health
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_opp_health_reachable(member_client, monkeypatch):
    client, _, _ = member_client
    now = dt.datetime(2026, 5, 14, 10, 0, tzinfo=dt.UTC)
    monkeypatch.setattr(
        "apps.opps.api_v2.probe_opp_health",
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
        "apps.opps.api_v2.probe_opp_health",
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
        "apps.opps.api_v2.invalidate_opp_snapshot_cache",
        lambda workspace: None,
    )
    response = client.post("/api/w/ws1/opps/opp-1/snapshot/invalidate")
    assert response.status_code == 204


@pytest.mark.django_db
def test_invalidate_snapshot_403_non_admin(member_client, monkeypatch):
    """Regular editor cannot invalidate."""
    client, _, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api_v2.invalidate_opp_snapshot_cache",
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
