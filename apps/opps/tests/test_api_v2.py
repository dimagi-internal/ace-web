import pytest
from django.contrib.auth import get_user_model

from apps.opps.schemas import OppCardOut
from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()


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
