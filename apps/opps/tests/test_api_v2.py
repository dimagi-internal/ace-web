import pytest
from django.contrib.auth import get_user_model

from apps.opps.schemas import OppCardOut, OppSnapshotOut
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

    response = client.get("/api/v2/w/ws1/opps")
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
    response = client.get("/api/v2/w/ws2/opps")
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
    response = client.get("/api/v2/w/ws1/opps")
    assert response.status_code == 401
    assert response["Content-Type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# Task 2.1.3 — GET /w/{workspace_slug}/opps/{slug}
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_opp_returns_snapshot_with_etag(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api_v2.load_opp_snapshot",
        lambda workspace, slug, run_id=None: _FAKE_SNAPSHOT,
    )
    response = client.get("/api/v2/w/ws1/opps/opp-1")
    assert response.status_code == 200
    assert "ETag" in response
    body = response.json()
    OppSnapshotOut.model_validate(body)
    assert body["slug"] == "opp-1"


@pytest.mark.django_db
def test_get_opp_304_on_matching_etag(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api_v2.load_opp_snapshot",
        lambda workspace, slug, run_id=None: _FAKE_SNAPSHOT,
    )
    # First request — get the ETag.
    r1 = client.get("/api/v2/w/ws1/opps/opp-1")
    assert r1.status_code == 200
    etag = r1["ETag"]
    # Second request with matching If-None-Match → 304.
    r2 = client.get("/api/v2/w/ws1/opps/opp-1", HTTP_IF_NONE_MATCH=etag)
    assert r2.status_code == 304


@pytest.mark.django_db
def test_get_opp_404_non_member(non_member_client, monkeypatch):
    client, _, _ = non_member_client
    response = client.get("/api/v2/w/ws1/opps/opp-1")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


@pytest.mark.django_db
def test_get_opp_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator5@example.com"),
    )
    response = client.get("/api/v2/w/ws1/opps/opp-1")
    assert response.status_code == 401


@pytest.mark.django_db
def test_get_opp_404_unknown_slug(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.opps.api_v2.load_opp_snapshot",
        lambda workspace, slug, run_id=None: None,
    )
    response = client.get("/api/v2/w/ws1/opps/no-such-opp")
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
        "/api/v2/w/ws1/opps",
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
        "/api/v2/w/ws1/opps",
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
        "/api/v2/w/ws1/opps",
        data={"title": "New Opp", "slug": "new-opp", "idea": "An idea."},
        content_type="application/json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_create_opp_400_empty_title(member_client):
    client, workspace, _ = member_client
    response = client.post(
        "/api/v2/w/ws1/opps",
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
        "/api/v2/w/ws1/opps",
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
        "/api/v2/w/ws1/opps/opp-1",
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
        "/api/v2/w/ws1/opps/opp-1",
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
        "/api/v2/w/ws1/opps/opp-1",
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
        "/api/v2/w/ws1/opps/no-such-opp",
        data={"title": "Updated"},
        content_type="application/json",
    )
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


@pytest.mark.django_db
def test_patch_opp_400_empty_title(member_client):
    client, workspace, _ = member_client
    response = client.patch(
        "/api/v2/w/ws1/opps/opp-1",
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
    response = client.delete("/api/v2/w/ws1/opps/opp-1")
    assert response.status_code == 204


@pytest.mark.django_db
def test_delete_opp_404_non_member(non_member_client):
    client, _, _ = non_member_client
    response = client.delete("/api/v2/w/ws1/opps/opp-1")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")


@pytest.mark.django_db
def test_delete_opp_401_anonymous(db, client):
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator8@example.com"),
    )
    response = client.delete("/api/v2/w/ws1/opps/opp-1")
    assert response.status_code == 401


@pytest.mark.django_db
def test_delete_opp_404_unknown_slug(member_client, monkeypatch):
    client, workspace, user = member_client

    def _raise_not_found(workspace, slug):
        raise FileNotFoundError(f"no opp named {slug!r}")

    monkeypatch.setattr("apps.opps.api_v2.delete_opp_by_slug", _raise_not_found)
    response = client.delete("/api/v2/w/ws1/opps/no-such-opp")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")
