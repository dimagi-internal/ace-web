import pytest
from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()


@pytest.mark.django_db
def test_openapi_schema_serves():
    client = Client()
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    payload = response.json()
    assert payload["info"]["title"] == "ace-web API"
    assert payload["openapi"].startswith("3.1")


@pytest.mark.django_db
def test_unknown_route_returns_problem_json():
    client = Client()
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404


@pytest.mark.django_db
def test_scalar_docs_serves_html():
    client = Client()
    response = client.get("/api/docs/")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")  # pyright: ignore[reportIndexIssue]
    assert b"api-reference" in response.content


@pytest.mark.django_db
def test_redoc_docs_serves_html():
    client = Client()
    response = client.get("/api/redoc/")
    assert response.status_code == 200
    assert b"redoc" in response.content


@pytest.mark.django_db
def test_session_auth_rejects_anonymous(client):
    response = client.get("/api/_auth_smoke/")
    assert response.status_code == 401
    body = response.json()
    assert body["status"] == 401
    assert body["type"].endswith("/auth")


@pytest.mark.django_db
def test_session_auth_accepts_logged_in_user(client):
    user = User.objects.create_user(email="alice@example.com")
    client.force_login(user)
    response = client.get("/api/_auth_smoke/")
    assert response.status_code == 200
    assert response.json() == {"email": "alice@example.com"}
