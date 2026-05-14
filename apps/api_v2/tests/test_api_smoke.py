import pytest
from django.test import Client


@pytest.mark.django_db
def test_openapi_schema_serves():
    client = Client()
    response = client.get("/api/v2/openapi.json")
    assert response.status_code == 200
    payload = response.json()
    assert payload["info"]["title"] == "ace-web API"
    assert payload["openapi"].startswith("3.1")


@pytest.mark.django_db
def test_unknown_route_returns_problem_json():
    client = Client()
    response = client.get("/api/v2/does-not-exist")
    assert response.status_code == 404


@pytest.mark.django_db
def test_scalar_docs_serves_html():
    client = Client()
    response = client.get("/api/docs/")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    assert b"api-reference" in response.content


@pytest.mark.django_db
def test_redoc_docs_serves_html():
    client = Client()
    response = client.get("/api/redoc/")
    assert response.status_code == 200
    assert b"redoc" in response.content
