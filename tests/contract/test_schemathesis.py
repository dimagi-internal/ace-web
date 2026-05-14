"""Property-based contract tests: fuzz the OpenAPI spec against the live WSGI app.

Strategy
--------
Uses ``schemathesis.openapi.from_wsgi`` to run in-process without a live server.
Auth is provided via a ``PersonalToken`` (Bearer header) created in a session-
scoped fixture.

Checks run
----------
Only two checks are enabled:
- ``not_a_server_error`` — no 5xx responses.
- ``response_schema_conformance`` — if a 2xx is returned, the body must match the
  declared Pydantic/OpenAPI schema.

The following checks are intentionally skipped (schema is not yet fully annotated):
- ``status_code_conformance`` — endpoints don't yet declare 401/404/422 error codes.
  Follow-up: add `{401: ProblemOut, 404: ProblemOut}` to every protected route.
- ``ignored_auth`` — sessions are established via Bearer token; schemathesis also
  generates random cookie values which our auth layer accepts via Django session,
  producing false positives for this check.
- All other stateful / negative-data checks — out of scope for Phase 6.

Tags excluded from this run (require external services):
- ``opps`` — reads through to Google Drive (no SA key in test env)
- ``mobile`` — orchestrates EC2 / SSM (no AWS in test env)
- ``system`` — reads the bundled ACE plugin from disk (present in CI but not reliably
  populated in unit test runs; system-level unit tests handle this surface)
- ``ingest`` — requires multipart JSONL upload; covered by dedicated unit tests

The test is marked ``@pytest.mark.contract`` so it can be run in isolation:
    uv run pytest tests/contract/ -v -m contract
"""
from __future__ import annotations

import pytest
import schemathesis
from django.contrib.auth import get_user_model
from schemathesis.checks import not_a_server_error
from schemathesis.specs.openapi.checks import response_schema_conformance

User = get_user_model()

# ---------------------------------------------------------------------------
# Schema + auth fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def wsgi_app(django_db_setup, django_db_blocker):
    """Return the Django WSGI application for schemathesis.from_wsgi."""
    from django.core.wsgi import get_wsgi_application
    return get_wsgi_application()


@pytest.fixture(scope="session")
def contract_auth_headers(django_db_setup, django_db_blocker):
    """Create a test user + PersonalToken and return Bearer headers.

    Session-scoped so the same token is reused across all 40+ parametrized
    test cases — avoids re-inserting DB rows on every case.
    """
    from apps.auth.models import PersonalToken
    from apps.workspaces.models import Workspace, WorkspaceMembership

    with django_db_blocker.unblock():
        user, _ = User.objects.get_or_create(
            email="contract-test@example.com",
            defaults={"display_name": "Contract Test"},
        )
        # Revoke any stale tokens from previous runs
        PersonalToken.objects.filter(user=user).update(revoked_at=None)

        raw_token, _token = PersonalToken.create_for_user(user=user, label="contract-ci")

        # Create a test workspace so workspace-scoped list endpoints return
        # 200 rather than an empty queryset that still passes but gives less
        # signal.
        ws, _created = Workspace.objects.get_or_create(
            slug="contract-ws",
            defaults={
                "display_name": "Contract Test Workspace",
                "drive_root_folder_id": "fake-drive-folder-id",
                "created_by": user,
            },
        )
        WorkspaceMembership.objects.get_or_create(
            workspace=ws,
            user=user,
            defaults={"role": "owner"},
        )

    return {"Authorization": f"Bearer {raw_token}"}


# ---------------------------------------------------------------------------
# Schemathesis schema object — module-level so @schema.parametrize() works
# ---------------------------------------------------------------------------
# We build the schema lazily via a fixture-backed lazy proxy to avoid importing
# the WSGI app at module import time (which would trigger Django setup before
# pytest-django has configured the settings). Instead, tests receive the schema
# via the `schema` pytest fixture below and @schema.parametrize() references
# the same object.
#
# Note: schemathesis.openapi.from_wsgi requires the app at decoration time
# (the @schema.parametrize() call). We work around this by building the schema
# once in a module-level lazy init triggered by the first test run, using the
# app fixture indirectly. The canonical schemathesis pattern for pytest+wsgi is
# to call from_wsgi at module scope — which requires Django to be set up. Since
# pytest-django sets DJANGO_SETTINGS_MODULE via the ini option, this works when
# the test module is imported by pytest (settings are already configured at that
# point).

def _build_schema():
    from django.core.wsgi import get_wsgi_application
    app = get_wsgi_application()
    return (
        schemathesis.openapi.from_wsgi("/api/openapi.json", app)
        # --- Skip tags that require unavailable external services ---
        # opps: Google Drive (no SA key), mobile: EC2/SSM (no AWS),
        # system: bundled plugin on disk (not in unit-test env),
        # ingest: multipart JSONL upload (dedicated unit tests)
        .exclude(tag="opps")
        .exclude(tag="mobile")
        .exclude(tag="system")
        .exclude(tag="ingest")
        # Exclude the internal smoke route (not a real endpoint)
        .exclude(path="/api/_auth_smoke/")
        # Exclude share public endpoint (no auth + token parameter requires
        # existing share — stateful; covered by sessions unit tests)
        .exclude(path="/api/share/{token}")
        # Exclude invite endpoints (require existing invite token; covered
        # by workspace unit tests)
        .exclude(path_regex=r"^/api/invites/")
        # Exclude activity endpoint - requires workspace with real activity
        .exclude(path_regex=r"/activity$")
        # Exclude the POST drive-config/verify (makes real Drive API call)
        .exclude(path_regex=r"/drive-config/")
        # Exclude /api/health — it probes Redis + Postgres, returns 503 when
        # services are unavailable. Schemathesis treats 5xx as Server Error
        # even when declared in the schema. The endpoint itself is covered
        # by unit tests in apps/common/.
        .exclude(path="/api/health")
    )


schema = _build_schema()


# ---------------------------------------------------------------------------
# Main contract test
# ---------------------------------------------------------------------------


@pytest.mark.contract
@pytest.mark.django_db(transaction=True)
@schema.parametrize()
def test_api_conforms_to_schema(case, contract_auth_headers):
    """Fuzz every (path × method) combination in scope.

    Validates:
    - No 5xx server errors (not_a_server_error)
    - Response body matches the declared schema when a 2xx is returned
      (response_schema_conformance)

    Auth: Bearer token injected via contract_auth_headers fixture.
    """
    response = case.call_and_validate(
        headers=contract_auth_headers,
        # Explicit allowlist: skip checks that require a fully-annotated schema
        # (401/404/422 declarations missing from most endpoints — Phase 6 gap).
        checks=[not_a_server_error, response_schema_conformance],
    )
    # Optional: log for visibility when run with -v
    _ = response  # pytest -v shows the parametrize ID (method + path)
