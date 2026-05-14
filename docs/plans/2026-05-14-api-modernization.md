# API Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace DRF with Django Ninja, make Pydantic v2 the single source of truth for every API request/response shape, generate the frontend TypeScript client from the OpenAPI 3.1 schema, kill the `{data, error}` envelope in favor of RFC 7807 `application/problem+json`, add Schemathesis contract tests in CI, and expose the API as MCP tools via FastMCP. Keep Django (ORM, auth, Channels, middleware) untouched.

**Architecture:** Mount Django Ninja at `/api/v2/` alongside the existing DRF surface at `/api/`. Build a complete Pydantic schema library in `apps/<app>/schemas.py`. Port endpoints app-by-app under v2. Generate `frontend/src/api/generated.ts` from the live OpenAPI schema via `openapi-typescript`; replace the hand-maintained `frontend/src/api/types.ts` and rewrite each resource client to use `openapi-fetch` against v2. Once every frontend call moves to v2, delete DRF, delete `apps/common/envelope.py`, and remove `/api/`. Wire FastMCP as an additional surface that wraps the same Pydantic-typed handlers as MCP tools.

**Tech Stack:** Django 5 (kept), Django Ninja 1.x, Pydantic v2, Scalar (docs UI), `openapi-typescript` + `openapi-fetch` + TanStack Query (frontend), Schemathesis (contract tests in CI), FastMCP (MCP exposure). Orthogonal modernization: `uv` for dep management, `basedpyright` for stricter type checking, `Pydantic AI` for any LLM-touching code, Logfire for observability.

**Out of scope:** No changes to Django Channels (`SessionConsumer`, `OppConsumer`), Redis pub/sub, presence hash, CommCare Connect OAuth flow, Nova OAuth flow, custom User model, Workspace tenancy model, opp Workbench cache strategy, or any business logic. This is a transport-layer modernization; behavior is identical end-to-end.

---

## Phase 0: Foundation

Set up Django Ninja, Scalar, the shared problem+json error model, and the `/api/v2/` namespace. Zero behavior change to existing endpoints.

### Task 0.1: Add Ninja + Pydantic + Scalar dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add deps**

Edit `pyproject.toml` `[project] dependencies` to include:

```toml
"django-ninja>=1.3,<2.0",
"pydantic>=2.8,<3.0",
"orjson>=3.10",
```

- [ ] **Step 2: Install**

Run: `pip install -e .` (or `uv sync` once Task 8.1 lands — currently `pip` is fine)
Expected: clean install, no resolver conflicts.

- [ ] **Step 3: Verify imports**

Run: `python -c "import ninja, pydantic, orjson; print(ninja.__version__, pydantic.VERSION, orjson.__version__)"`
Expected: prints three version numbers without error.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat(api): add django-ninja + pydantic v2 + orjson dependencies"
```

### Task 0.2: Create the v2 NinjaAPI singleton with problem+json error model

**Files:**
- Create: `apps/api_v2/__init__.py`
- Create: `apps/api_v2/api.py`
- Create: `apps/api_v2/errors.py`
- Create: `apps/api_v2/renderers.py`

- [ ] **Step 1: Create the empty package**

```python
# apps/api_v2/__init__.py
"""Django Ninja v2 API. Pydantic-first replacement for the legacy DRF surface."""
```

- [ ] **Step 2: Create the problem+json error model**

```python
# apps/api_v2/errors.py
"""RFC 7807 problem+json error model + helpers."""
from __future__ import annotations

from typing import Any

from ninja.errors import HttpError
from pydantic import BaseModel, Field


class Problem(BaseModel):
    """RFC 7807 application/problem+json body.

    `type` is a stable URI identifying the error class.
    `title` is human-readable, stable per `type`.
    `status` mirrors the HTTP status.
    `detail` is the per-occurrence message.
    `instance` is the request path (optional).
    """

    type: str = Field(default="about:blank")
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    extras: dict[str, Any] | None = None


class ProblemError(HttpError):
    """Raise this anywhere in a v2 handler to short-circuit with a problem+json response."""

    def __init__(
        self,
        status: int,
        title: str,
        *,
        type_: str = "about:blank",
        detail: str | None = None,
        extras: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(status, title)
        self.problem_type = type_
        self.problem_title = title
        self.problem_detail = detail
        self.problem_extras = extras


# Common type URIs — extend as needed.
TYPE_VALIDATION = "https://ace-web.dimagi.com/problems/validation"
TYPE_AUTH = "https://ace-web.dimagi.com/problems/auth"
TYPE_FORBIDDEN = "https://ace-web.dimagi.com/problems/forbidden"
TYPE_NOT_FOUND = "https://ace-web.dimagi.com/problems/not-found"
TYPE_CONFLICT = "https://ace-web.dimagi.com/problems/conflict"
TYPE_RATE_LIMIT = "https://ace-web.dimagi.com/problems/rate-limit"
TYPE_UPSTREAM = "https://ace-web.dimagi.com/problems/upstream"
TYPE_INTERNAL = "https://ace-web.dimagi.com/problems/internal"
```

- [ ] **Step 3: Create the orjson renderer**

```python
# apps/api_v2/renderers.py
"""orjson-backed renderer + problem+json content-type override."""
from __future__ import annotations

import orjson
from ninja.renderers import BaseRenderer


class OrjsonRenderer(BaseRenderer):
    media_type = "application/json"

    def render(self, request, data, *, response_status):
        return orjson.dumps(data, option=orjson.OPT_NON_STR_KEYS | orjson.OPT_UTC_Z)


class ProblemJsonRenderer(OrjsonRenderer):
    """Used by the global error handler — sets `application/problem+json`."""

    media_type = "application/problem+json"
```

- [ ] **Step 4: Create the v2 NinjaAPI**

```python
# apps/api_v2/api.py
"""Single NinjaAPI instance for the /api/v2/ namespace.

All v2 routers register against this. Routers live in
`apps/<app>/api_v2.py` and are imported below.
"""
from __future__ import annotations

import logging

from django.http import HttpRequest, HttpResponse
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, ValidationError

from .errors import (
    TYPE_AUTH,
    TYPE_INTERNAL,
    TYPE_NOT_FOUND,
    TYPE_VALIDATION,
    Problem,
    ProblemError,
)
from .renderers import OrjsonRenderer

logger = logging.getLogger(__name__)


api = NinjaAPI(
    title="ace-web API",
    version="2.0.0",
    description=(
        "Modern Pydantic-typed API surface for ace-web. "
        "Replaces the legacy `/api/` DRF endpoints. "
        "Errors are RFC 7807 application/problem+json."
    ),
    urls_namespace="api_v2",
    renderer=OrjsonRenderer(),
    docs_url=None,  # we mount Scalar at /api/v2/docs/ separately in urls.py
    openapi_url="/openapi.json",
)


def _problem_response(request: HttpRequest, problem: Problem) -> HttpResponse:
    body = problem.model_dump(exclude_none=True)
    response = HttpResponse(
        content=OrjsonRenderer().render(request, body, response_status=problem.status),
        status=problem.status,
        content_type="application/problem+json",
    )
    return response


@api.exception_handler(ProblemError)
def _on_problem_error(request: HttpRequest, exc: ProblemError) -> HttpResponse:
    problem = Problem(
        type=exc.problem_type,
        title=exc.problem_title,
        status=exc.status_code,
        detail=exc.problem_detail,
        instance=request.path,
        extras=exc.problem_extras,
    )
    return _problem_response(request, problem)


@api.exception_handler(ValidationError)
def _on_validation_error(request: HttpRequest, exc: ValidationError) -> HttpResponse:
    problem = Problem(
        type=TYPE_VALIDATION,
        title="Request validation failed",
        status=422,
        detail="One or more fields failed validation.",
        instance=request.path,
        extras={"errors": exc.errors},
    )
    return _problem_response(request, problem)


@api.exception_handler(AuthenticationError)
def _on_auth_error(request: HttpRequest, exc: AuthenticationError) -> HttpResponse:
    problem = Problem(
        type=TYPE_AUTH,
        title="Authentication required",
        status=401,
        detail="This endpoint requires an authenticated session.",
        instance=request.path,
    )
    return _problem_response(request, problem)


@api.exception_handler(Exception)
def _on_unhandled(request: HttpRequest, exc: Exception) -> HttpResponse:
    logger.exception("Unhandled exception in v2 handler")
    problem = Problem(
        type=TYPE_INTERNAL,
        title="Internal server error",
        status=500,
        detail="An unexpected error occurred. The team has been notified.",
        instance=request.path,
    )
    return _problem_response(request, problem)
```

- [ ] **Step 5: Commit**

```bash
git add apps/api_v2/
git commit -m "feat(api): add ninja v2 namespace + RFC 7807 problem+json error model"
```

### Task 0.3: Mount /api/v2/ in URL conf

**Files:**
- Modify: `config/urls.py`

- [ ] **Step 1: Read current URL conf**

Open `config/urls.py`. Find the `urlpatterns` list. Locate the existing `path("api/", include(...))` entry.

- [ ] **Step 2: Add v2 mount**

Add (just below the existing `api/` include):

```python
from apps.api_v2.api import api as api_v2

urlpatterns = [
    ...,
    path("api/v2/", api_v2.urls),
    ...
]
```

- [ ] **Step 3: Verify it starts**

Run: `python manage.py runserver 0.0.0.0:8000` (or via docker compose)
Open: `http://localhost:8000/api/v2/openapi.json`
Expected: returns a valid OpenAPI 3.1 JSON document with `info.title == "ace-web API"` and zero paths (no routers registered yet).

- [ ] **Step 4: Write a smoke test**

Create `apps/api_v2/tests/__init__.py` (empty) and `apps/api_v2/tests/test_api_smoke.py`:

```python
import json

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
```

- [ ] **Step 5: Run smoke tests**

Run: `pytest apps/api_v2/tests/test_api_smoke.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add config/urls.py apps/api_v2/tests/
git commit -m "feat(api): mount Django Ninja v2 at /api/v2/ with smoke tests"
```

### Task 0.4: Wire Scalar docs UI

**Files:**
- Modify: `apps/api_v2/api.py`
- Create: `apps/api_v2/views.py`
- Modify: `config/urls.py`

- [ ] **Step 1: Add Scalar HTML view**

Scalar is a static HTML page that fetches `/api/v2/openapi.json` and renders it. No Python dep needed.

```python
# apps/api_v2/views.py
"""Static docs UI views — Scalar (primary) and Redoc (reference)."""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse

_SCALAR_HTML = """<!doctype html>
<html>
<head>
  <title>ace-web API — Scalar</title>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
</head>
<body>
  <script id="api-reference" data-url="/api/v2/openapi.json"></script>
  <script>
    var configuration = {
      theme: "default",
      layout: "modern",
      hideDownloadButton: false,
      searchHotKey: "k",
    };
    document.getElementById("api-reference").dataset.configuration =
      JSON.stringify(configuration);
  </script>
  <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
</body>
</html>
"""

_REDOC_HTML = """<!doctype html>
<html>
<head>
  <title>ace-web API — Redoc</title>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>body { margin: 0; padding: 0; }</style>
</head>
<body>
  <redoc spec-url="/api/v2/openapi.json"></redoc>
  <script src="https://cdn.jsdelivr.net/npm/redoc/bundles/redoc.standalone.js"></script>
</body>
</html>
"""


def scalar_docs(request: HttpRequest) -> HttpResponse:
    return HttpResponse(_SCALAR_HTML, content_type="text/html; charset=utf-8")


def redoc_docs(request: HttpRequest) -> HttpResponse:
    return HttpResponse(_REDOC_HTML, content_type="text/html; charset=utf-8")
```

- [ ] **Step 2: Mount docs routes**

Edit `config/urls.py`:

```python
from apps.api_v2.views import redoc_docs, scalar_docs

urlpatterns = [
    ...,
    path("api/v2/", api_v2.urls),
    path("api/docs/", scalar_docs, name="api_docs_scalar"),
    path("api/redoc/", redoc_docs, name="api_docs_redoc"),
    ...
]
```

- [ ] **Step 3: Smoke test the docs pages**

Add to `apps/api_v2/tests/test_api_smoke.py`:

```python
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
```

- [ ] **Step 4: Run and verify in browser**

Run: `pytest apps/api_v2/tests/test_api_smoke.py -v`
Expected: 4 passed.

Open `http://localhost:8000/api/docs/` — Scalar should render (empty endpoints list at this stage). Open `http://localhost:8000/api/redoc/` — Redoc should render.

- [ ] **Step 5: Commit**

```bash
git add apps/api_v2/views.py config/urls.py apps/api_v2/tests/test_api_smoke.py
git commit -m "feat(api): mount Scalar + Redoc docs UI for v2 OpenAPI schema"
```

### Task 0.5: Auth integration — Django session auth for Ninja

**Files:**
- Create: `apps/api_v2/auth.py`
- Modify: `apps/api_v2/tests/test_api_smoke.py`

- [ ] **Step 1: Write the failing test**

Add to `apps/api_v2/tests/test_api_smoke.py`:

```python
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
def test_session_auth_rejects_anonymous(client):
    response = client.get("/api/v2/_auth_smoke/")
    assert response.status_code == 401
    body = response.json()
    assert body["status"] == 401
    assert body["type"].endswith("/auth")


@pytest.mark.django_db
def test_session_auth_accepts_logged_in_user(client):
    user = User.objects.create_user(email="alice@example.com", password="pw")
    client.force_login(user)
    response = client.get("/api/v2/_auth_smoke/")
    assert response.status_code == 200
    assert response.json() == {"email": "alice@example.com"}
```

- [ ] **Step 2: Run — expect failure**

Run: `pytest apps/api_v2/tests/test_api_smoke.py::test_session_auth_rejects_anonymous -v`
Expected: FAIL — route doesn't exist yet.

- [ ] **Step 3: Create the auth class**

```python
# apps/api_v2/auth.py
"""Session-cookie auth for Django Ninja routes.

Matches DRF's SessionAuthentication: trust `request.user` from Django's
auth middleware. Raises `ProblemError(401, "Authentication required")`
when no user is attached.

CSRF: Ninja enforces CSRF on unsafe methods by default when using
session auth. The v2 NinjaAPI is constructed with `csrf=True` in
api.py once this auth class is wired in.
"""
from __future__ import annotations

from django.http import HttpRequest
from ninja.security import SessionAuth

from .errors import TYPE_AUTH, ProblemError


class DjangoSessionAuth(SessionAuth):
    """Session auth that raises problem+json instead of returning None."""

    def authenticate(self, request: HttpRequest, key: str | None) -> object | None:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise ProblemError(
                401,
                "Authentication required",
                type_=TYPE_AUTH,
                detail="This endpoint requires an authenticated session.",
            )
        return user


session_auth = DjangoSessionAuth()
```

- [ ] **Step 4: Add the smoke route + enable CSRF**

Edit `apps/api_v2/api.py`. Change the `NinjaAPI(...)` constructor call to add `csrf=True`. Then below the exception handlers, add:

```python
from .auth import session_auth


@api.get("/_auth_smoke/", auth=session_auth, response={200: dict})
def _auth_smoke(request: HttpRequest) -> dict:
    """Internal smoke route — verifies session auth works."""
    return {"email": request.user.email}
```

- [ ] **Step 5: Run tests**

Run: `pytest apps/api_v2/tests/test_api_smoke.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/api_v2/auth.py apps/api_v2/api.py apps/api_v2/tests/test_api_smoke.py
git commit -m "feat(api): wire Django session auth + CSRF into v2 with problem+json 401"
```

### Task 0.6: Workspace-membership dependency

**Files:**
- Create: `apps/api_v2/deps.py`
- Create: `apps/api_v2/tests/test_deps.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/api_v2/tests/test_deps.py
import pytest
from django.contrib.auth import get_user_model

from apps.workspaces.models import Workspace, WorkspaceMember

User = get_user_model()


@pytest.fixture
def workspace_and_member(db):
    workspace = Workspace.objects.create(slug="ws1", name="WS1", drive_root_folder_id="folder-1")
    user = User.objects.create_user(email="a@example.com", password="pw")
    WorkspaceMember.objects.create(workspace=workspace, user=user, role="editor")
    return workspace, user


@pytest.mark.django_db
def test_resolve_workspace_returns_workspace_for_member(workspace_and_member, rf):
    from apps.api_v2.deps import resolve_workspace_for_member

    workspace, user = workspace_and_member
    request = rf.get("/api/v2/w/ws1/")
    request.user = user
    result = resolve_workspace_for_member(request, "ws1")
    assert result.pk == workspace.pk


@pytest.mark.django_db
def test_resolve_workspace_404s_for_non_member(workspace_and_member, rf):
    from apps.api_v2.deps import resolve_workspace_for_member
    from apps.api_v2.errors import ProblemError

    workspace, _ = workspace_and_member
    outsider = User.objects.create_user(email="b@example.com", password="pw")
    request = rf.get("/api/v2/w/ws1/")
    request.user = outsider
    with pytest.raises(ProblemError) as exc_info:
        resolve_workspace_for_member(request, "ws1")
    assert exc_info.value.status_code == 404
```

- [ ] **Step 2: Run — expect import error**

Run: `pytest apps/api_v2/tests/test_deps.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

```python
# apps/api_v2/deps.py
"""Shared route dependencies.

These functions are called from inside Ninja handlers (not as
`Depends()` — Ninja uses path/query params directly). They raise
`ProblemError` on failure so the v2 error handler renders
problem+json.

Workspace existence is never leaked: non-members get 404, not 403.
This matches the policy enforced in `apps/common/access.py`.
"""
from __future__ import annotations

from django.http import HttpRequest

from apps.workspaces.models import Workspace, WorkspaceMember

from .errors import TYPE_NOT_FOUND, ProblemError


def resolve_workspace_for_member(request: HttpRequest, slug: str) -> Workspace:
    """Resolve `slug` to a Workspace iff request.user is a member.

    Raises ProblemError(404) for anyone else (including authenticated
    users who aren't in this workspace — workspace existence is hidden).
    """
    workspace = Workspace.objects.filter(slug=slug).first()
    if workspace is None:
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
    is_member = WorkspaceMember.objects.filter(
        workspace=workspace, user=request.user
    ).exists()
    if not is_member:
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
    return workspace
```

- [ ] **Step 4: Run tests**

Run: `pytest apps/api_v2/tests/test_deps.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/api_v2/deps.py apps/api_v2/tests/test_deps.py
git commit -m "feat(api): add workspace-membership dependency with 404-not-403 leak prevention"
```

### Task 0.7: Pagination + ETag helpers

**Files:**
- Create: `apps/api_v2/pagination.py`
- Create: `apps/api_v2/etag.py`
- Create: `apps/api_v2/tests/test_pagination.py`
- Create: `apps/api_v2/tests/test_etag.py`

- [ ] **Step 1: Write the pagination test**

```python
# apps/api_v2/tests/test_pagination.py
from apps.api_v2.pagination import Page, paginate


def test_paginate_returns_page_with_metadata():
    items = list(range(95))
    page = paginate(items, offset=20, limit=25)
    assert isinstance(page, Page)
    assert page.items == list(range(20, 45))
    assert page.total == 95
    assert page.offset == 20
    assert page.limit == 25


def test_paginate_handles_overflow_gracefully():
    items = list(range(10))
    page = paginate(items, offset=50, limit=25)
    assert page.items == []
    assert page.total == 10


def test_paginate_defaults():
    items = list(range(5))
    page = paginate(items, offset=0, limit=100)
    assert page.items == items
    assert page.total == 5
```

- [ ] **Step 2: Implement Pagination**

```python
# apps/api_v2/pagination.py
"""Offset/limit pagination shared across v2 list endpoints.

Pydantic generic — every list endpoint declares its response as
`Page[ItemSchema]` so the OpenAPI schema knows the item type.
"""
from __future__ import annotations

from typing import Generic, Sequence, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)


def paginate(items: Sequence[T], *, offset: int, limit: int) -> Page[T]:
    total = len(items)
    sliced = list(items[offset : offset + limit])
    return Page(items=sliced, total=total, offset=offset, limit=limit)
```

- [ ] **Step 3: Write the ETag test**

```python
# apps/api_v2/tests/test_etag.py
import pytest
from django.http import HttpResponseNotModified

from apps.api_v2.etag import compute_etag, maybe_not_modified


def test_compute_etag_stable_for_same_payload():
    e1 = compute_etag({"a": 1, "b": [2, 3]})
    e2 = compute_etag({"b": [2, 3], "a": 1})  # key order shouldn't matter
    assert e1 == e2


def test_compute_etag_changes_for_different_payload():
    e1 = compute_etag({"a": 1})
    e2 = compute_etag({"a": 2})
    assert e1 != e2


def test_maybe_not_modified_returns_304_on_match(rf):
    etag = compute_etag({"a": 1})
    request = rf.get("/x", HTTP_IF_NONE_MATCH=etag)
    response = maybe_not_modified(request, etag)
    assert isinstance(response, HttpResponseNotModified)


def test_maybe_not_modified_returns_none_on_miss(rf):
    request = rf.get("/x", HTTP_IF_NONE_MATCH='"different"')
    response = maybe_not_modified(request, compute_etag({"a": 1}))
    assert response is None


def test_maybe_not_modified_returns_none_without_header(rf):
    request = rf.get("/x")
    response = maybe_not_modified(request, compute_etag({"a": 1}))
    assert response is None
```

- [ ] **Step 4: Implement ETag**

```python
# apps/api_v2/etag.py
"""ETag round-trip for v2 endpoints.

Mirrors the policy from the existing opp Workbench cache
(`docs/learnings/opp-cache-architecture.md`): ETag is sha256 of
the serialized response body with stable key ordering. Returning
`HttpResponseNotModified` short-circuits the response writer and
avoids re-serializing the body.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from django.http import HttpRequest, HttpResponseNotModified


def compute_etag(payload: Any) -> str:
    """sha256 of the canonically-serialized payload, wrapped in W/"..."."""
    serialized = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    digest = hashlib.sha256(serialized).hexdigest()
    return f'W/"{digest}"'


def maybe_not_modified(request: HttpRequest, etag: str) -> HttpResponseNotModified | None:
    """Return 304 if the request's If-None-Match matches `etag`, else None."""
    inm = request.headers.get("If-None-Match")
    if inm and inm == etag:
        response = HttpResponseNotModified()
        response["ETag"] = etag
        return response
    return None
```

- [ ] **Step 5: Run tests**

Run: `pytest apps/api_v2/tests/ -v`
Expected: all pass (8+ tests).

- [ ] **Step 6: Commit**

```bash
git add apps/api_v2/pagination.py apps/api_v2/etag.py apps/api_v2/tests/test_pagination.py apps/api_v2/tests/test_etag.py
git commit -m "feat(api): add Page[T] pagination + ETag helpers for v2"
```

---

## Phase 1: Pydantic schema library

Define request/response shapes for every resource as Pydantic models. No views are migrated yet — just shapes. This phase locks naming, optionality, and nullability decisions before any endpoint is touched.

Convention: schemas live in `apps/<app>/schemas.py`. Read-only output schemas are suffixed `Out`; input schemas are suffixed `In`; "patch" schemas use `Patch`. Resources expose a single canonical schema unless write shape is meaningfully different from read shape. Reuse from `apps/common/schemas.py` for cross-cutting types.

### Task 1.1: Cross-cutting schemas

**Files:**
- Create: `apps/common/schemas.py`
- Create: `apps/common/tests/test_schemas.py`

- [ ] **Step 1: Write the round-trip test**

```python
# apps/common/tests/test_schemas.py
import datetime as dt

from apps.common.schemas import TimestampMixin, UserRefOut


def test_user_ref_round_trip():
    raw = {"id": 42, "email": "alice@example.com", "display_name": "Alice"}
    parsed = UserRefOut.model_validate(raw)
    assert parsed.email == "alice@example.com"
    dumped = parsed.model_dump()
    assert dumped == raw


def test_timestamp_mixin_iso8601():
    when = dt.datetime(2026, 5, 14, 12, 0, tzinfo=dt.UTC)

    class _S(TimestampMixin):
        pass

    s = _S(created_at=when, updated_at=when)
    dumped = s.model_dump(mode="json")
    assert dumped["created_at"].endswith("Z") or "+00:00" in dumped["created_at"]
```

- [ ] **Step 2: Implement**

```python
# apps/common/schemas.py
"""Cross-cutting Pydantic schemas reused across apps.

Conventions:
- Output schemas end in `Out`, input in `In`, patches in `Patch`.
- IDs that are slugs use `str`; numeric PKs use `int`.
- All datetimes are timezone-aware ISO-8601 (Pydantic v2 default).
- Optional fields use `T | None = None`; required fields have no default.
"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, EmailStr


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",  # request bodies reject unknown fields
        from_attributes=True,  # allow ORM-instance hydration
        str_strip_whitespace=True,
    )


class TimestampMixin(BaseModel):
    created_at: dt.datetime
    updated_at: dt.datetime


class UserRefOut(StrictModel):
    """Minimal user reference for embedding in other responses."""

    id: int
    email: EmailStr
    display_name: str | None = None


class WorkspaceRefOut(StrictModel):
    """Minimal workspace reference for embedding."""

    slug: str
    name: str
```

- [ ] **Step 3: Run tests**

Run: `pytest apps/common/tests/test_schemas.py -v`
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add apps/common/schemas.py apps/common/tests/test_schemas.py
git commit -m "feat(api): add cross-cutting Pydantic schemas (UserRef, WorkspaceRef, TimestampMixin)"
```

### Task 1.2: Workspaces schemas

**Files:**
- Create: `apps/workspaces/schemas.py`
- Create: `apps/workspaces/tests/test_schemas.py`

- [ ] **Step 1: Inspect current DRF response shape**

Read the existing workspaces view module (find via `grep -nR "def workspace" apps/workspaces/views.py`). Note the exact field names, types, and optionality of the JSON the frontend currently consumes (look at `frontend/src/api/workspaces.ts` and `frontend/src/api/types.ts` for the consumer side).

- [ ] **Step 2: Write the round-trip test**

```python
# apps/workspaces/tests/test_schemas.py
import datetime as dt

import pytest

from apps.workspaces.schemas import (
    WorkspaceCreateIn,
    WorkspaceMemberOut,
    WorkspaceOut,
    WorkspacePatchIn,
)


def test_workspace_out_round_trip():
    raw = {
        "slug": "dimagi-team",
        "name": "Dimagi Team",
        "drive_root_folder_id": "abc123",
        "role": "owner",
        "member_count": 4,
        "created_at": "2026-04-27T12:00:00Z",
        "updated_at": "2026-04-27T12:00:00Z",
    }
    parsed = WorkspaceOut.model_validate(raw)
    assert parsed.slug == "dimagi-team"
    assert parsed.role == "owner"


def test_workspace_member_round_trip():
    raw = {
        "id": 7,
        "user": {"id": 1, "email": "a@example.com", "display_name": "Alice"},
        "role": "editor",
        "joined_at": "2026-04-27T12:00:00Z",
    }
    parsed = WorkspaceMemberOut.model_validate(raw)
    assert parsed.role == "editor"


def test_workspace_create_validation():
    with pytest.raises(ValueError):
        WorkspaceCreateIn(slug="", name="X", drive_root_folder_id="f")
    with pytest.raises(ValueError):
        WorkspaceCreateIn(slug="ok", name="", drive_root_folder_id="f")
    obj = WorkspaceCreateIn(slug="ok", name="Name", drive_root_folder_id="folder-1")
    assert obj.slug == "ok"


def test_workspace_patch_partial():
    obj = WorkspacePatchIn(name="New name")
    dumped = obj.model_dump(exclude_unset=True)
    assert dumped == {"name": "New name"}
```

- [ ] **Step 3: Implement schemas**

```python
# apps/workspaces/schemas.py
"""Pydantic v2 schemas for the /api/v2/workspaces surface."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from apps.common.schemas import StrictModel, TimestampMixin, UserRefOut

WorkspaceRole = Literal["owner", "editor", "viewer"]


class WorkspaceOut(StrictModel, TimestampMixin):
    slug: str
    name: str
    drive_root_folder_id: str
    role: WorkspaceRole  # the requesting user's role in this workspace
    member_count: int = Field(ge=0)


class WorkspaceMemberOut(StrictModel):
    id: int
    user: UserRefOut
    role: WorkspaceRole
    joined_at: dt.datetime


class WorkspaceCreateIn(StrictModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=128)
    drive_root_folder_id: str = Field(min_length=1)


class WorkspacePatchIn(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    drive_root_folder_id: str | None = Field(default=None, min_length=1)


class WorkspaceInviteIn(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    role: WorkspaceRole


class WorkspaceInviteOut(StrictModel, TimestampMixin):
    token: str
    email: str
    role: WorkspaceRole
    accepted: bool
    accepted_at: dt.datetime | None = None
```

- [ ] **Step 4: Run tests**

Run: `pytest apps/workspaces/tests/test_schemas.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/workspaces/schemas.py apps/workspaces/tests/test_schemas.py
git commit -m "feat(api): add Pydantic schemas for workspaces"
```

### Task 1.3: Opps schemas

**Files:**
- Create: `apps/opps/schemas.py`
- Create: `apps/opps/tests/test_schemas.py`

- [ ] **Step 1: Inventory the current Workbench payload shape**

Examine the existing payload by reading `apps/opps/sync.py` (the Drive-to-payload reader) and `frontend/src/api/types.ts` (the consumer side). Note every field on `OppCardOut`, `OppSnapshotOut`, `OppRunOut`, `StepSnapshotOut`, `ArtifactOut`, `VerdictOut`, `GateOut`, `ScorecardOut`, `ForkProgress`, `OppForkIn`, `OppForkOut`.

- [ ] **Step 2: Write the round-trip test (covering all opp shapes)**

```python
# apps/opps/tests/test_schemas.py
import pytest

from apps.opps.schemas import (
    ArtifactOut,
    ForkProgress,
    GateOut,
    OppCardOut,
    OppForkIn,
    OppForkOut,
    OppRunOut,
    OppSnapshotOut,
    ScorecardOut,
    StepSnapshotOut,
    VerdictOut,
)


def test_opp_card_round_trip():
    raw = {
        "slug": "lit-onboard-20260514",
        "title": "Literacy Onboarding",
        "current_phase": "scenarios-and-acceptance",
        "current_skill": "scenarios-and-acceptance",
        "run_count": 3,
        "last_run_id": "run-003",
        "updated_at": "2026-05-13T09:00:00Z",
    }
    parsed = OppCardOut.model_validate(raw)
    assert parsed.run_count == 3


def test_fork_in_validation():
    with pytest.raises(ValueError):
        OppForkIn(fork_at_phase="")
    obj = OppForkIn(fork_at_phase="ocs-setup", source_run_id="run-002")
    assert obj.source_run_id == "run-002"


def test_fork_progress_status_union():
    for status in ["unknown", "counting", "copying", "finalizing", "done", "error"]:
        ForkProgress.model_validate({"status": status, "progress": 0.0})


def test_verdict_and_gate_minimum_fields():
    VerdictOut.model_validate(
        {
            "skill": "ocs-setup",
            "phase": "ocs-setup",
            "kind": "quick",
            "score": 87,
            "verdict": "pass",
            "rationale": "Smoke tests passed.",
            "decided_at": "2026-05-12T10:00:00Z",
        }
    )
    GateOut.model_validate(
        {
            "skill": "ocs-setup",
            "decision": "approved",
            "decided_by": "alice@example.com",
            "decided_at": "2026-05-12T10:00:00Z",
            "note": None,
        }
    )
```

- [ ] **Step 3: Implement schemas**

```python
# apps/opps/schemas.py
"""Pydantic schemas for the /api/v2/opps surface.

Mirrors the existing payload shape produced by `apps/opps/sync.py`
and consumed by `frontend/src/api/opps.ts` + `types.ts`. Field names
match what the frontend expects so the schema can be introduced
without a frontend rewrite in this phase.
"""
from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import Field

from apps.common.schemas import StrictModel

# --- Identifiers -------------------------------------------------------

PhaseId = str  # e.g. "idea-to-design", "scenarios-and-acceptance"
SkillId = str  # plugin-declared skill slug
RunId = str  # e.g. "run-001"

# --- Cards / snapshots -------------------------------------------------


class OppCardOut(StrictModel):
    slug: str
    title: str
    current_phase: PhaseId | None = None
    current_skill: SkillId | None = None
    run_count: int = Field(ge=0)
    last_run_id: RunId | None = None
    updated_at: dt.datetime


class ArtifactOut(StrictModel):
    id: str  # Drive file_id
    name: str
    mime_type: str
    size_bytes: int | None = None
    url: str | None = None  # web view link, may be null for unshared files
    is_text: bool
    preview: str | None = None


class VerdictOut(StrictModel):
    skill: SkillId
    phase: PhaseId
    kind: Literal["quick", "deep", "monitor"]
    score: int = Field(ge=0, le=100)
    verdict: Literal["pass", "warn", "fail"]
    rationale: str
    decided_at: dt.datetime


class GateOut(StrictModel):
    skill: SkillId
    decision: Literal["approved", "rejected", "pending"]
    decided_by: str | None = None
    decided_at: dt.datetime | None = None
    note: str | None = None


class StepSnapshotOut(StrictModel):
    skill: SkillId
    phase: PhaseId
    status: Literal["pending", "in_progress", "complete", "skipped", "failed"]
    artifact_count: int = Field(ge=0)
    artifacts: list[ArtifactOut]
    verdicts: list[VerdictOut]
    gate: GateOut | None = None
    preview: str | None = None


class ScorecardOut(StrictModel):
    score: int = Field(ge=0, le=100)
    verdict: Literal["pass", "warn", "fail"]
    rationale: str
    trend: list[int]  # historical scores by run
    decided_at: dt.datetime


class OppRunOut(StrictModel):
    run_id: RunId
    label: str
    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    is_active: bool
    scorecard: ScorecardOut | None = None


class OppSnapshotOut(StrictModel):
    slug: str
    title: str
    runs: list[OppRunOut]
    active_run_id: RunId | None = None
    steps: list[StepSnapshotOut]
    pending_gates: list[SkillId]
    scorecard: ScorecardOut | None = None
    updated_at: dt.datetime

# --- Fork --------------------------------------------------------------


class OppForkIn(StrictModel):
    fork_at_phase: str = Field(min_length=1)
    source_run_id: RunId | None = None


class OppForkOut(StrictModel):
    slug: str
    run_id: RunId
    working_session_slug: str


ForkStatus = Literal["unknown", "counting", "copying", "finalizing", "done", "error"]


class ForkProgress(StrictModel):
    status: ForkStatus
    progress: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    files_total: int | None = None
    files_copied: int | None = None
    error: str | None = None
    new_slug: str | None = None
    new_run_id: RunId | None = None
```

- [ ] **Step 4: Run tests**

Run: `pytest apps/opps/tests/test_schemas.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/schemas.py apps/opps/tests/test_schemas.py
git commit -m "feat(api): add Pydantic schemas for opps (cards, snapshots, runs, fork)"
```

### Task 1.4: Sessions schemas

**Files:**
- Create: `apps/sessions/schemas.py`
- Create: `apps/sessions/tests/test_schemas.py`

- [ ] **Step 1: Inventory current payload shape**

Read `apps/sessions/views.py` and `frontend/src/api/sessions.ts` + `frontend/src/api/messages.ts` + `frontend/src/api/types.ts`. Note: `SessionOut`, `SessionCreateIn`, `SessionPatchIn`, `MessageOut`, `ParticipantOut`, `TurnStateOut`, `CostBreakdownOut`, `StructureNodeOut`, `ShareTokenOut`.

- [ ] **Step 2: Write the round-trip tests**

Write at least one round-trip test per schema. Each test loads a realistic dict (taken from a current API response — capture one with `curl` against a dev server while iterating) and asserts `model_validate(...)` succeeds and `model_dump()` round-trips.

- [ ] **Step 3: Implement**

Create `apps/sessions/schemas.py` with `SessionOut`, `SessionCreateIn`, `SessionPatchIn`, `MessageOut`, `ParticipantOut`, `TurnStateOut`, `CostBreakdownOut`, `StructureNodeOut` (recursive), `ShareTokenOut`. Use the same `StrictModel` base; use `Literal[...]` for enums; use `dt.datetime` for timestamps. Recursive types via `from __future__ import annotations` + forward refs.

- [ ] **Step 4: Run tests**

Run: `pytest apps/sessions/tests/test_schemas.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/sessions/schemas.py apps/sessions/tests/test_schemas.py
git commit -m "feat(api): add Pydantic schemas for sessions (session, message, participant, turn-state, structure)"
```

### Task 1.5: Ingest, activity, system, service_accounts, mobile, auth schemas

For each app, repeat the pattern of Task 1.4: read current view + frontend consumer, write round-trip tests, implement schemas, run tests, commit. Each app is a separate commit.

- [ ] **Step 1: `apps/ingest/schemas.py`** — `IngestUploadIn` (multipart, declared as form fields in the route, not the schema), `IngestUploadOut` (`session_slug`, `messages_imported`, `cost_breakdown` ref).

- [ ] **Step 2: `apps/activity/schemas.py`** — `ActivityFeedOut`, `ActivityEntryOut` (kind union, actor ref, timestamp, payload dict).

- [ ] **Step 3: `apps/system/schemas.py`** — `SystemOverviewOut`, `SkillSummaryOut`, `AgentSummaryOut`, `VersionOut`, `CliDiagOut`. Reuse from `apps/system/reader.py` field names.

- [ ] **Step 4: `apps/service_accounts/schemas.py`** — `PersonalTokenOut`, `PersonalTokenCreateIn`, `PersonalTokenCreatedOut` (only-time the raw token leaks), `ShareTokenOut`, `ShareTokenCreateIn`.

- [ ] **Step 5: `apps/mobile/schemas.py`** — `MobileStatusOut`, `RunRecipeIn`, `RunRecipeOut`, `JobOut`, `JobStatus`, `DiagnoseOut`, `StateSnapshotOut`, `LaunchScriptPatchIn`.

- [ ] **Step 6: `apps/auth/schemas.py`** — `LoginIn`, `LoginOut`, `MeOut`, `NovaAuthStatusOut`, `E2ELoginIn`, `TestLoginIn`. (Most auth routes redirect; the schema set is small.)

- [ ] **Step 7: Run the full schema test suite**

Run: `pytest -k "test_schemas" -v`
Expected: every per-app schema test passes.

- [ ] **Step 8: Commit (one commit per app)**

Each app gets its own commit: `feat(api): add Pydantic schemas for <app>`.

---

## Phase 2: Endpoint migration

Port endpoints app-by-app under `/api/v2/`. The full pattern is worked out for the `opps` app in Task 2.1 (the most complex surface). Subsequent apps follow the same pattern — fewer code samples, more checklist.

**Per-endpoint pattern** (canonical, established in Task 2.1.2 below):

1. Write a contract test in `apps/<app>/tests/test_api_v2.py` that hits the v2 URL and asserts:
   - HTTP status
   - Response body validates against the response Pydantic schema
   - Auth + workspace-membership gating behave correctly
   - On error: response is `application/problem+json` matching `Problem` shape
2. Write the Ninja handler in `apps/<app>/api_v2.py`. Handler is thin: parse params → call existing service function → return Pydantic model.
3. Run the contract test — expect it to pass.
4. Run the existing DRF test for the same endpoint — it should still pass against `/api/`.
5. Commit.

### Task 2.1: Opps app migration

**Files:**
- Create: `apps/opps/api_v2.py`
- Create: `apps/opps/tests/test_api_v2.py`
- Modify: `apps/api_v2/api.py` (register router)

The opps surface has 19 endpoints. The first endpoint (`GET /api/v2/opps`) is worked through fully below; subsequent endpoints follow the same shape and are listed as a checklist.

#### Task 2.1.1: Register the opps router

- [ ] **Step 1: Create the empty router module**

```python
# apps/opps/api_v2.py
"""Django Ninja v2 router for the opps Workbench surface."""
from __future__ import annotations

from ninja import Router

from apps.api_v2.auth import session_auth

router = Router(auth=session_auth, tags=["opps"])
```

- [ ] **Step 2: Register on the main NinjaAPI**

Edit `apps/api_v2/api.py`. Below the smoke route, add:

```python
from apps.opps.api_v2 import router as opps_router

api.add_router("/w/{workspace_slug}/opps", opps_router)
```

- [ ] **Step 3: Verify schema lists the tag**

Run: `curl -sS http://localhost:8000/api/v2/openapi.json | python -m json.tool | grep -A1 '"tags"' | head`
Expected: `"opps"` appears.

- [ ] **Step 4: Commit**

```bash
git add apps/opps/api_v2.py apps/api_v2/api.py
git commit -m "feat(api): register opps router under /api/v2/w/{workspace_slug}/opps"
```

#### Task 2.1.2: Worked example — `GET /api/v2/w/{workspace_slug}/opps` (list opps)

This is the canonical per-endpoint task. All other endpoint tasks reference it.

- [ ] **Step 1: Write the contract test**

```python
# apps/opps/tests/test_api_v2.py
import pytest
from django.contrib.auth import get_user_model

from apps.opps.schemas import OppCardOut
from apps.workspaces.models import Workspace, WorkspaceMember

User = get_user_model()


@pytest.fixture
def member_client(db, client):
    workspace = Workspace.objects.create(slug="ws1", name="WS1", drive_root_folder_id="folder-1")
    user = User.objects.create_user(email="a@example.com", password="pw")
    WorkspaceMember.objects.create(workspace=workspace, user=user, role="editor")
    client.force_login(user)
    return client, workspace, user


@pytest.fixture
def non_member_client(db, client):
    workspace = Workspace.objects.create(slug="ws1", name="WS1", drive_root_folder_id="folder-1")
    user = User.objects.create_user(email="b@example.com", password="pw")
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
    Workspace.objects.create(slug="ws2", name="WS2", drive_root_folder_id="folder-2")
    response = client.get("/api/v2/w/ws2/opps")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 404
    assert body["type"].endswith("/not-found")


@pytest.mark.django_db
def test_list_opps_401_anonymous(db, client):
    Workspace.objects.create(slug="ws1", name="WS1", drive_root_folder_id="folder-1")
    response = client.get("/api/v2/w/ws1/opps")
    assert response.status_code == 401
    assert response["Content-Type"].startswith("application/problem+json")
```

- [ ] **Step 2: Run — expect failure**

Run: `pytest apps/opps/tests/test_api_v2.py -v`
Expected: tests FAIL — route doesn't exist; `404` on the path.

- [ ] **Step 3: Implement the handler**

Edit `apps/opps/api_v2.py`:

```python
from __future__ import annotations

from django.http import HttpRequest
from ninja import Router

from apps.api_v2.auth import session_auth
from apps.api_v2.deps import resolve_workspace_for_member
from apps.api_v2.pagination import Page, paginate

from .schemas import OppCardOut
from .sync import list_opp_cards  # existing read-through helper

router = Router(auth=session_auth, tags=["opps"])


@router.get("", response=Page[OppCardOut], summary="List opps in workspace")
def list_opps(
    request: HttpRequest,
    workspace_slug: str,
    offset: int = 0,
    limit: int = 100,
) -> Page[OppCardOut]:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    cards = list_opp_cards(workspace)
    return paginate([OppCardOut.model_validate(c) for c in cards], offset=offset, limit=limit)
```

If `list_opp_cards` doesn't exist with that name, find the equivalent function in `apps/opps/sync.py` (likely `_opp_list_impl` or similar). Extract it to a clean public name if necessary (small refactor — keep behavior identical).

- [ ] **Step 4: Run tests**

Run: `pytest apps/opps/tests/test_api_v2.py -v`
Expected: 3 passed.

- [ ] **Step 5: Verify the legacy DRF endpoint still works**

Run: `pytest apps/opps/tests/ -v -k "not test_api_v2"`
Expected: all existing opps tests still pass — we have not touched DRF.

- [ ] **Step 6: Verify the OpenAPI schema is well-formed**

Run: `curl -sS http://localhost:8000/api/v2/openapi.json | python -c "import json, sys, jsonschema; data = json.load(sys.stdin); print('paths:', list(data['paths'].keys()))"`
Expected: includes `/w/{workspace_slug}/opps`.

Open `http://localhost:8000/api/docs/` and verify the endpoint appears in Scalar with the correct response schema.

- [ ] **Step 7: Commit**

```bash
git add apps/opps/api_v2.py apps/opps/tests/test_api_v2.py
git commit -m "feat(api): port GET /opps (list) to v2 with contract tests"
```

#### Task 2.1.3 through 2.1.20: Remaining opps endpoints

For each endpoint below, follow the pattern from Task 2.1.2 exactly: write the contract test, run-fail, implement the handler, run-pass, verify DRF still works, commit. One commit per endpoint.

- [ ] **2.1.3** `GET /w/{workspace_slug}/opps/{slug}` — opp Workbench snapshot (with ETag round-trip from `apps/api_v2/etag.py`).
- [ ] **2.1.4** `POST /w/{workspace_slug}/opps` — create opp (delegates to existing creator helper).
- [ ] **2.1.5** `PATCH /w/{workspace_slug}/opps/{slug}` — update opp.
- [ ] **2.1.6** `DELETE /w/{workspace_slug}/opps/{slug}` — delete opp.
- [ ] **2.1.7** `GET /w/{workspace_slug}/opps/{slug}/runs` — list runs for an opp.
- [ ] **2.1.8** `GET /w/{workspace_slug}/opps/{slug}/runs/{run_id}` — run detail.
- [ ] **2.1.9** `DELETE /w/{workspace_slug}/opps/{slug}/runs/{run_id}` — delete run.
- [ ] **2.1.10** `GET /w/{workspace_slug}/opps/{slug}/steps/{skill}` — step detail.
- [ ] **2.1.11** `GET /w/{workspace_slug}/opps/{slug}/artifacts/{artifact_id}` — artifact read (proxied through Drive).
- [ ] **2.1.12** `GET /w/{workspace_slug}/opps/{slug}/artifacts/{artifact_id}/download` — artifact binary download.
- [ ] **2.1.13** `POST /w/{workspace_slug}/opps/{slug}/fork` — fork opp (delegate to `opp_forker.fork_opp`; map `ProblemError` for 400/404/409 paths).
- [ ] **2.1.14** `GET /w/{workspace_slug}/opps/{slug}/fork/status` — fork polling status.
- [ ] **2.1.15** `GET /w/{workspace_slug}/opps/{slug}/scorecard` — run-level scorecard.
- [ ] **2.1.16** `POST /w/{workspace_slug}/opps/{slug}/gates/{skill}` — record gate decision.
- [ ] **2.1.17** `GET /w/{workspace_slug}/opps/{slug}/compare` — multi-run comparison view.
- [ ] **2.1.18** `POST /w/{workspace_slug}/opps/{slug}/actions/seed-chat` — "Discuss in chat" seed (delegates to `apps/opps/seed.py`).
- [ ] **2.1.19** `GET /w/{workspace_slug}/opps/{slug}/health` — opp Drive health probe.
- [ ] **2.1.20** `POST /w/{workspace_slug}/opps/{slug}/snapshot/invalidate` — admin cache bust.

For each, the test fixtures should include a "member happy path", a "non-member 404", an "anonymous 401", and at least one error-path test (e.g., for `fork`: 409 when source run doesn't exist).

- [ ] **Final step: Full opps regression**

Run: `pytest apps/opps/ -v`
Expected: every existing test still passes, plus the new contract tests.

- [ ] **Commit each endpoint individually with `feat(api): port <METHOD> <path> to v2 with contract tests`.**

### Task 2.2: Sessions app migration

**Files:**
- Create: `apps/sessions/api_v2.py`
- Create: `apps/sessions/tests/test_api_v2.py`
- Modify: `apps/api_v2/api.py` (register router under `/sessions`)

Apply the Task 2.1.2 pattern per endpoint. 9 HTTP endpoints + 0 WebSocket changes (Channels routing is untouched).

- [ ] **2.2.1** Register router: `api.add_router("/w/{workspace_slug}/sessions", sessions_router)`.
- [ ] **2.2.2** `GET /sessions` — list sessions (paginated).
- [ ] **2.2.3** `POST /sessions` — create session.
- [ ] **2.2.4** `GET /sessions/{slug}` — session detail.
- [ ] **2.2.5** `PATCH /sessions/{slug}` — update session (title, archived flag).
- [ ] **2.2.6** `DELETE /sessions/{slug}` — delete session.
- [ ] **2.2.7** `GET /sessions/{slug}/messages` — message history.
- [ ] **2.2.8** `GET /sessions/{slug}/participants` — participant list.
- [ ] **2.2.9** `GET /sessions/{slug}/turn-state` — current turn state (cheap polling endpoint).
- [ ] **2.2.10** `GET /sessions/{slug}/cost` — `Session.cost_breakdown` rollup.
- [ ] **2.2.11** `GET /sessions/{slug}/structure` — session structure tree (delegate to `structure_aggregator`).
- [ ] **2.2.12** `GET /sessions/{slug}/share` — share-token info.
- [ ] **2.2.13** Final regression: `pytest apps/sessions/ -v`.
- [ ] **2.2.14** Commit each endpoint individually.

### Task 2.3: Workspaces app migration

8 endpoints. Mount router at `/api/v2/workspaces` (not under `/w/<slug>/` — these are the workspace-management endpoints themselves).

- [ ] **2.3.1** Register router.
- [ ] **2.3.2** `GET /workspaces` — list workspaces I'm in.
- [ ] **2.3.3** `POST /workspaces` — create workspace.
- [ ] **2.3.4** `GET /workspaces/{slug}` — workspace detail.
- [ ] **2.3.5** `PATCH /workspaces/{slug}` — update workspace (owner only).
- [ ] **2.3.6** `POST /workspaces/{slug}/members/invite` — send invite.
- [ ] **2.3.7** `DELETE /workspaces/{slug}/members/{user_id}` — remove member.
- [ ] **2.3.8** `POST /workspaces/{slug}/leave` — leave workspace.
- [ ] **2.3.9** `GET /workspaces/{slug}/activity` — workspace audit log.
- [ ] **2.3.10** `POST /workspaces/{slug}/drive-config/verify` — verify Drive access.
- [ ] **2.3.11** Final regression + commit each.

### Task 2.4: Ingest app migration

1 endpoint, multipart upload. Ninja supports multipart natively via `File` + form fields.

- [ ] **2.4.1** Register router at `/api/v2/ingest`.
- [ ] **2.4.2** `POST /ingest/upload` — JSONL upload with optional opp/run/skill linkage. Form fields: `file: UploadedFile`, optional `opp_slug: str`, `opp_run_id: str`, `opp_step_skill: str`, `workspace_slug: str` (header `X-Workspace-Slug` if not in form). Returns `IngestUploadOut`.
- [ ] **2.4.3** Final regression + commit.

### Task 2.5: Mobile app migration

16 endpoints. Most are admin-only (gated on `_can_write_global`). Treat the `_can_write_global` gate as a route dependency that raises `ProblemError(403, ...)`.

- [ ] **2.5.1** Create `apps/api_v2/deps.py::require_write_global` mirroring the existing gate.
- [ ] **2.5.2** Register router at `/api/v2/mobile`.
- [ ] **2.5.3** Port endpoints (status, ensure-running, run-recipe, diagnose, states, snapshots, APK ops, job poll, admin patch-launch-script) per the Task 2.1.2 pattern.
- [ ] **2.5.4** Final regression + commit each.

### Task 2.6: System app migration

5 endpoints. Read-only, no workspace scoping (system info is global).

- [ ] **2.6.1** Register router at `/api/v2/system`.
- [ ] **2.6.2** Port `overview`, `skills`, `agents`, `version`, `cli-diag`.
- [ ] **2.6.3** Final regression + commit each.

### Task 2.7: Activity app migration

1 endpoint: workspace timeline feed.

- [ ] **2.7.1** Register router at `/api/v2/w/{workspace_slug}/activity`.
- [ ] **2.7.2** `GET /` — paginated activity feed.
- [ ] **2.7.3** Final regression + commit.

### Task 2.8: Service accounts app migration

Personal tokens + share tokens.

- [ ] **2.8.1** Register router at `/api/v2/tokens`.
- [ ] **2.8.2** `GET /tokens` — list my tokens.
- [ ] **2.8.3** `POST /tokens` — create token (response includes the raw token once).
- [ ] **2.8.4** `DELETE /tokens/{id}` — revoke token.
- [ ] **2.8.5** Share token endpoints (read-only public share resolution stays at the existing `/share/<token>` path; only the management endpoints move).
- [ ] **2.8.6** Final regression + commit each.

### Task 2.9: Auth app migration

12 endpoints, most are browser-redirect OAuth dances (not REST). Only port the JSON endpoints.

- [ ] **2.9.1** Determine which auth endpoints are JSON (likely: `GET /me`, `POST /e2e-login`, `GET /nova-auth-status`, `POST /logout`). The OAuth `/callback` redirects, CLI auth PTY, and Nova OAuth callbacks stay on the existing Django views — they're not REST API.
- [ ] **2.9.2** Register router at `/api/v2/auth`.
- [ ] **2.9.3** Port the JSON endpoints. The OAuth callback views stay as-is.
- [ ] **2.9.4** Final regression + commit.

### Task 2.10: Common app migration

7 endpoints: health, CLI auth status, Nova auth.

- [ ] **2.10.1** Register router at `/api/v2/`.
- [ ] **2.10.2** Port `GET /health` (public, no auth — explicitly `auth=None`).
- [ ] **2.10.3** Port CLI auth status + Nova auth endpoints.
- [ ] **2.10.4** Final regression + commit.

### Task 2.11: Backend-side cutover gate

- [ ] **Step 1: Full backend test sweep**

Run: `pytest -v`
Expected: every existing test passes; every new `test_api_v2.py` test passes.

- [ ] **Step 2: Manual smoke**

Open `http://localhost:8000/api/docs/`. Every endpoint listed should be tagged correctly (one tag per app). Click into 3-4 endpoints, use "Try it" to exercise them, verify responses match Pydantic schemas.

- [ ] **Step 3: Commit a tag**

```bash
git tag api-v2-backend-complete
git commit --allow-empty -m "milestone: v2 backend complete, 95 endpoints ported"
```

---

## Phase 3: Frontend type generation

Replace the hand-maintained `frontend/src/api/types.ts` with types generated from the live v2 OpenAPI schema. Add a typed thin HTTP client (`openapi-fetch`) on top. Frontend still calls `/api/` (DRF) at this phase — type generation only.

### Task 3.1: Install generators

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Add devDeps**

```bash
cd frontend && bun add -d openapi-typescript openapi-fetch
```

- [ ] **Step 2: Add generation script**

Edit `frontend/package.json` `scripts`:

```json
{
  "scripts": {
    ...,
    "gen:api": "openapi-typescript http://localhost:8000/api/v2/openapi.json --output src/api/generated.ts --immutable"
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/bun.lockb
git commit -m "feat(frontend): add openapi-typescript + openapi-fetch dependencies"
```

### Task 3.2: Generate the types

**Files:**
- Create: `frontend/src/api/generated.ts` (autogenerated)
- Create: `frontend/src/api/client.v2.ts`

- [ ] **Step 1: Generate against a live backend**

```bash
docker compose up -d  # ensure backend is running with all v2 routes
cd frontend && bun run gen:api
```

Expected: `frontend/src/api/generated.ts` is created. Inspect it — it should contain `paths` and `components.schemas` matching the OpenAPI doc.

- [ ] **Step 2: Create the v2 client**

```typescript
// frontend/src/api/client.v2.ts
import createClient from "openapi-fetch";
import type { paths } from "./generated";

const baseUrl = import.meta.env.BASE_URL || "/";
export const apiV2 = createClient<paths>({
  baseUrl: `${baseUrl.replace(/\/$/, "")}/api/v2`,
  credentials: "include",
  headers: {
    "X-Requested-With": "XMLHttpRequest",
  },
});
```

- [ ] **Step 3: Add a sanity test**

```typescript
// frontend/src/api/__tests__/client.v2.test.ts
import { describe, expect, it } from "vitest";
import { apiV2 } from "../client.v2";
import type { components } from "../generated";

describe("apiV2 typed client", () => {
  it("compiles with typed paths", () => {
    type OppCardOut = components["schemas"]["OppCardOut"];
    const sample: OppCardOut = {
      slug: "x",
      title: "x",
      run_count: 0,
      updated_at: "2026-05-14T00:00:00Z",
    };
    expect(sample.slug).toBe("x");
  });
});
```

- [ ] **Step 4: Run tests**

```bash
cd frontend && bun run test
```

Expected: existing tests + new sanity test pass.

- [ ] **Step 5: Add a CI script to refresh generated types**

Create `.github/workflows/regen-openapi.yml`:

```yaml
name: Regenerate OpenAPI types

on:
  pull_request:
    paths:
      - "apps/**/api_v2.py"
      - "apps/**/schemas.py"
      - "apps/api_v2/**"

jobs:
  regen:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.ref }}
          token: ${{ secrets.GITHUB_TOKEN }}
      - uses: oven-sh/setup-bun@v1
      - name: Boot Django for schema dump
        run: |
          pip install -e .
          python -c "
          import django, json, os
          os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.test'
          django.setup()
          from apps.api_v2.api import api
          with open('frontend/openapi.json', 'w') as f:
            json.dump(api.get_openapi_schema(), f, indent=2)
          "
      - name: Regenerate types
        run: |
          cd frontend
          bun install
          bunx openapi-typescript openapi.json --output src/api/generated.ts --immutable
      - name: Commit if changed
        run: |
          git config user.name "github-actions"
          git config user.email "github-actions@github.com"
          if ! git diff --quiet frontend/src/api/generated.ts; then
            git add frontend/src/api/generated.ts
            git commit -m "chore(api): regenerate OpenAPI types"
            git push
          fi
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/generated.ts frontend/src/api/client.v2.ts frontend/src/api/__tests__/client.v2.test.ts .github/workflows/regen-openapi.yml
git commit -m "feat(frontend): generate types from v2 OpenAPI + typed openapi-fetch client + regen CI"
```

---

## Phase 4: Frontend cutover

Migrate each resource client in `frontend/src/api/*.ts` from the hand-written DRF caller to the typed v2 client. Frontend pages don't need changes (they call the api/*.ts wrapper functions). Once every resource is on v2, delete `frontend/src/api/types.ts`.

**Per-resource pattern:**

1. Pick one file in `frontend/src/api/` (start with `workspaces.ts` — smallest surface).
2. Replace each function body to use `apiV2` from `client.v2.ts`. Function signatures stay identical (callers don't change).
3. Replace the hand-written input/output types with the imported `components["schemas"]["XOut"]` types.
4. Run the vitest suite + manually exercise the affected pages in the browser.
5. Commit.

### Task 4.1: Workspaces client

**Files:**
- Modify: `frontend/src/api/workspaces.ts`

- [ ] **Step 1: Rewrite using v2 client**

For every function in `workspaces.ts`, replace the fetch call with `apiV2.GET/POST/PATCH/DELETE("/workspaces/...", ...)`. The response data is already typed; remove all manual unwrapping of `{data, error}` (v2 returns the payload directly).

- [ ] **Step 2: Update callers' imports**

If callers imported types from `types.ts` like `import type { Workspace } from "./types"`, replace with `import type { components } from "./generated"` and use `components["schemas"]["WorkspaceOut"]`.

- [ ] **Step 3: Run tests**

```bash
cd frontend && bun run test
```

Expected: all pass.

- [ ] **Step 4: Manual UI test**

Open `http://localhost:8000/welcome` (workspace onboarding) and `http://localhost:8000/w/<slug>/workspace-settings`. Create a workspace, invite a member, change a role, leave a workspace. All flows should work.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/workspaces.ts
git commit -m "feat(frontend): migrate workspaces client to v2 typed openapi-fetch"
```

### Tasks 4.2 – 4.17: Migrate remaining resource clients

Repeat the Task 4.1 pattern, one file per task, one commit per task. Order:

- [ ] **4.2** `auth.ts`
- [ ] **4.3** `system.ts`
- [ ] **4.4** `activity.ts`
- [ ] **4.5** `tokens.ts`
- [ ] **4.6** `share.ts`
- [ ] **4.7** `ingest.ts`
- [ ] **4.8** `costs.ts`
- [ ] **4.9** `structure.ts`
- [ ] **4.10** `participants.ts`
- [ ] **4.11** `messages.ts`
- [ ] **4.12** `sessions.ts`
- [ ] **4.13** `opps.ts` (largest — leave for last)
- [ ] **4.14** `oppSummary.ts`
- [ ] **4.15** `oppCache.ts`
- [ ] **4.16** (Mobile UI — if any frontend file consumes mobile API, otherwise skip.)

After 4.16, every resource client targets `/api/v2/`.

### Task 4.17: Delete types.ts

**Files:**
- Delete: `frontend/src/api/types.ts`
- Modify: any file still importing from it (should be zero by now)

- [ ] **Step 1: Verify no imports remain**

```bash
cd frontend && rg "from .*api/types" src/
```

Expected: zero results.

- [ ] **Step 2: Delete**

```bash
rm frontend/src/api/types.ts
```

- [ ] **Step 3: Build + test**

```bash
bunx tsc -b && bun run test
```

Expected: clean build, all tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/types.ts
git commit -m "chore(frontend): delete types.ts — types now generated from OpenAPI"
```

### Task 4.18: Frontend cutover gate

- [ ] **Step 1: Full frontend regression**

```bash
cd frontend && bunx tsc -b && bun run build && bun run test
```

Expected: clean.

- [ ] **Step 2: Manual end-to-end smoke**

Walk through every primary surface:
- Login → workspace picker → workspace home
- Sessions list → open session → chat (WebSocket — should still work since Channels is untouched)
- Opps list → open opp → run selector → fork → step detail → discuss in chat
- Workspace settings → members → activity log
- System tab → skills + agents + version

Each page should load and function identically to before.

- [ ] **Step 3: Commit milestone tag**

```bash
git tag api-v2-frontend-complete
git commit --allow-empty -m "milestone: v2 frontend cutover complete"
```

---

## Phase 5: DRF removal + envelope cleanup

Frontend no longer calls `/api/`. We can now delete DRF, the envelope module, the legacy URL conf entries, and the `djangorestframework` dependency.

### Task 5.1: Delete DRF view modules

**Files:**
- Delete: All `views.py` / `views_read.py` / `views_write.py` / `views_session.py` / `views_summary.py` files in `apps/*/` that contained DRF `@api_view` handlers
- Modify: `apps/*/urls.py` to remove DRF route patterns

- [ ] **Step 1: Inventory which files to delete**

```bash
rg -l "@api_view" apps/
```

Expected: a list of files. For each, confirm there's a `apps/<app>/api_v2.py` covering all the endpoints from that file (cross-check against `apps/api_v2/api.py` router registrations).

- [ ] **Step 2: Delete one app at a time**

Per app (start with the simplest, e.g. `activity`):
- Delete the DRF view module(s).
- Edit `apps/<app>/urls.py` — remove the deleted routes. If the urls.py becomes empty, delete it and remove the include from `config/urls.py`.
- Run `pytest apps/<app>/ -v` — only v2 tests should remain (existing DRF tests are deleted alongside the views).
- Commit: `chore(api): remove legacy DRF surface from <app>`

- [ ] **Step 3: Repeat for every app**

Order (smallest first): activity, ingest, system, common, service_accounts, mobile, auth, workspaces, sessions, opps.

### Task 5.2: Delete envelope module

**Files:**
- Delete: `apps/common/envelope.py`
- Modify: any remaining imports

- [ ] **Step 1: Verify no callers remain**

```bash
rg "from apps.common.envelope|success_response|error_response" apps/
```

Expected: zero results (Ninja handlers don't use the envelope).

- [ ] **Step 2: Delete**

```bash
rm apps/common/envelope.py
```

- [ ] **Step 3: Run all tests**

Run: `pytest -v`
Expected: every test passes.

- [ ] **Step 4: Commit**

```bash
git add apps/common/envelope.py
git commit -m "chore(api): delete envelope module — replaced by problem+json + bare 2xx responses"
```

### Task 5.3: Remove DRF dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `config/settings/base.py` (remove DRF from `INSTALLED_APPS` and any DRF-specific settings)

- [ ] **Step 1: Remove `djangorestframework` from `pyproject.toml`**

```toml
# Remove this line:
"djangorestframework>=3.15",
```

- [ ] **Step 2: Remove `rest_framework` from `INSTALLED_APPS`**

Edit `config/settings/base.py` and any other settings module. Remove `"rest_framework"` from `INSTALLED_APPS`. Remove any `REST_FRAMEWORK = {...}` dict.

- [ ] **Step 3: Reinstall**

Run: `pip install -e .`
Expected: clean install with DRF removed.

- [ ] **Step 4: Run all tests**

Run: `pytest -v`
Expected: every test passes.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml config/settings/
git commit -m "chore(api): remove djangorestframework dependency"
```

### Task 5.4: Rename /api/v2/ → /api/

Now that the legacy `/api/` is gone, drop the version prefix.

**Files:**
- Modify: `config/urls.py`
- Modify: `apps/api_v2/api.py` (rename module is optional; the route prefix is what matters)
- Modify: `frontend/src/api/client.v2.ts` baseUrl
- Modify: `.github/workflows/regen-openapi.yml`

- [ ] **Step 1: Change the mount**

Edit `config/urls.py`:

```python
# Before:
path("api/v2/", api_v2.urls),

# After:
path("api/", api_v2.urls),
```

- [ ] **Step 2: Update frontend baseUrl**

Edit `frontend/src/api/client.v2.ts` — change `${baseUrl}/api/v2` to `${baseUrl}/api`.

(Optional: rename `client.v2.ts` → `client.ts`, but that's churn — defer.)

- [ ] **Step 3: Update docs URL**

Edit `apps/api_v2/views.py` — the Scalar HTML still references `/api/v2/openapi.json`. Change to `/api/openapi.json`.

- [ ] **Step 4: Regenerate types**

```bash
docker compose up -d
cd frontend && bun run gen:api
```

(Edit the `gen:api` script too — `http://localhost:8000/api/openapi.json`.)

- [ ] **Step 5: Run full test sweep**

```bash
pytest -v && cd frontend && bunx tsc -b && bun run test
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore(api): rename /api/v2/ to /api/ now that legacy DRF surface is gone"
```

---

## Phase 6: Schemathesis CI contract tests

Wire Schemathesis to fuzz the OpenAPI spec against a running app, and add the job to CI.

### Task 6.1: Install + write a baseline run

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/contract/test_schemathesis.py`

- [ ] **Step 1: Add dep**

Edit `pyproject.toml` `[project.optional-dependencies] dev`:

```toml
"schemathesis>=3.30",
```

Run: `pip install -e ".[dev]"`

- [ ] **Step 2: Write the runner**

```python
# tests/contract/test_schemathesis.py
"""Property-based contract tests: fuzz the OpenAPI spec against the running app.

Auto-generates a request for every (path × method) combination, hits the
endpoint, and asserts:
- response status matches one declared in the spec
- response body matches the declared response schema
- response content-type matches the spec

Auth-protected routes are skipped unless `SCHEMATHESIS_AUTH_COOKIE` is set
(populate via the test-login flow before running).
"""
from __future__ import annotations

import os

import pytest
import schemathesis

SCHEMA_URL = os.environ.get(
    "SCHEMATHESIS_SCHEMA_URL", "http://localhost:8000/api/openapi.json"
)
AUTH_COOKIE = os.environ.get("SCHEMATHESIS_AUTH_COOKIE")

schema = schemathesis.from_uri(SCHEMA_URL)


@schema.parametrize()
def test_api_conforms_to_schema(case):
    headers = {}
    cookies = {}
    if AUTH_COOKIE:
        cookies["sessionid_ace"] = AUTH_COOKIE
    response = case.call(headers=headers, cookies=cookies)
    case.validate_response(response)
```

- [ ] **Step 3: Run locally with auth disabled**

For the first run, you can either (a) run schemathesis against only the public endpoints (`/api/health`), or (b) populate a session cookie via the test-login flow. For local iteration, (a):

```bash
docker compose up -d
pytest tests/contract/test_schemathesis.py -v -k "health"
```

Expected: every health endpoint passes the spec conformance check.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml tests/contract/test_schemathesis.py
git commit -m "feat(api): add schemathesis contract tests baseline"
```

### Task 6.2: Wire CI job with auth bootstrapping

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add a new job**

Add to `.github/workflows/ci.yml`:

```yaml
  contract-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: postgres
        ports: ["5432:5432"]
        options: --health-cmd pg_isready --health-interval 10s
      redis:
        image: redis:7
        ports: ["6379:6379"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -e ".[dev]"
      - name: Apply migrations
        run: python manage.py migrate
        env:
          DJANGO_SETTINGS_MODULE: config.settings.test
      - name: Start backend
        run: |
          python manage.py runserver 0.0.0.0:8000 &
          sleep 5
        env:
          DJANGO_SETTINGS_MODULE: config.settings.test
          ACE_E2E_AUTH_TOKEN: ci-fake-token
      - name: Bootstrap test session
        run: |
          curl -c cookies.txt -X POST http://localhost:8000/auth/e2e-login/ \
            -H "Content-Type: application/json" \
            -d '{"email": "ace@dimagi-ai.com", "token": "ci-fake-token"}'
          echo "SCHEMATHESIS_AUTH_COOKIE=$(grep sessionid_ace cookies.txt | awk '{print $7}')" >> $GITHUB_ENV
      - name: Run schemathesis
        run: pytest tests/contract/test_schemathesis.py -v
```

- [ ] **Step 2: Commit + push to a PR + verify the job passes**

```bash
git add .github/workflows/ci.yml
git commit -m "feat(ci): add schemathesis contract test job"
```

Push and create a PR. Watch the `contract-tests` job. Fix any schema/reality divergence Schemathesis flags by either correcting the handler or the schema (whichever is wrong).

### Task 6.3: Iterate to green

- [ ] **Step 1: Read every schemathesis failure**

For each failure, classify:
- "Handler returns a field not in the schema" → add the field to the schema OR remove it from the handler.
- "Handler returns a wrong type" → fix the handler.
- "Endpoint returns a status not declared" → add the status to the handler's `response={...}` dict.

- [ ] **Step 2: Loop until green**

Run locally:

```bash
docker compose up -d
SCHEMATHESIS_AUTH_COOKIE=<value> pytest tests/contract/test_schemathesis.py -v
```

Fix, commit, repeat. Each fix is its own commit: `fix(api): align <endpoint> with declared schema`.

- [ ] **Step 3: Once green, push, verify CI passes**

---

## Phase 7: FastMCP layer

Expose the v2 API as MCP tools. AI agents (Claude Code, future LLM consumers) can call ace-web routes as native tools.

### Task 7.1: Install FastMCP + wire a minimal server

**Files:**
- Modify: `pyproject.toml`
- Create: `apps/api_v2/mcp_server.py`
- Modify: `config/urls.py`

- [ ] **Step 1: Add dep**

```toml
"fastmcp>=0.4",
```

Run: `pip install -e .`

- [ ] **Step 2: Create the MCP server module**

```python
# apps/api_v2/mcp_server.py
"""FastMCP server exposing v2 routes as MCP tools.

Strategy: rather than re-declaring tools, we walk the live OpenAPI
schema and register one MCP tool per (path, method) that's marked
`x-mcp-expose: true` in its OpenAPI extension. Authoring an endpoint
opts it into MCP by adding `openapi_extra={"x-mcp-expose": True}` to
the Ninja route decorator.

Each tool calls the same Django view function via an internal request
(no HTTP loopback), so auth + tenancy gating are enforced identically.
"""
from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest
from django.test import RequestFactory
from fastmcp import FastMCP

from .api import api as ninja_api

mcp = FastMCP("ace-web")


def _build_tool(path: str, method: str, op: dict[str, Any], operation_id: str):
    @mcp.tool(name=operation_id, description=op.get("summary", ""))
    async def _tool(**kwargs: Any) -> str:
        # Build a synthetic request and route through Ninja.
        rf = RequestFactory()
        url = path
        for key, value in kwargs.items():
            url = url.replace("{" + key + "}", str(value))
        request = rf.generic(method.upper(), url, json.dumps(kwargs).encode("utf-8"))
        # ... attach the bot-identity user ...
        # Actual routing through ninja_api happens via the Django URL conf.
        # Implementation detail: this is a sketch; the real version
        # walks ninja_api._routers and invokes the handler directly.
        raise NotImplementedError("See Task 7.2 for the real implementation.")

    return _tool


def register_tools() -> None:
    """Walk the OpenAPI schema and register tools for opted-in endpoints."""
    schema = ninja_api.get_openapi_schema()
    for path, methods in schema["paths"].items():
        for method, op in methods.items():
            if method not in {"get", "post", "patch", "delete"}:
                continue
            if not op.get("x-mcp-expose"):
                continue
            operation_id = op.get("operationId") or f"{method}_{path}"
            _build_tool(path, method, op, operation_id)


register_tools()
```

- [ ] **Step 3: Mount the MCP endpoint**

Edit `config/urls.py`:

```python
from apps.api_v2.mcp_server import mcp

urlpatterns = [
    ...,
    path("api/mcp/", mcp.asgi_app()),  # FastMCP's ASGI mount
    ...
]
```

- [ ] **Step 4: Smoke test**

```bash
curl http://localhost:8000/api/mcp/  # should return MCP handshake
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml apps/api_v2/mcp_server.py config/urls.py
git commit -m "feat(api): add FastMCP server skeleton mounted at /api/mcp/"
```

### Task 7.2: Real tool-invocation bridge

Replace the `NotImplementedError` stub with a working bridge that invokes the Ninja handler in-process and returns the result.

- [ ] **Step 1: Implement the bridge**

The cleanest path: have each MCP tool call `requests.<method>(...)` against `http://localhost:<port>/api/<path>` with the bot identity's session cookie. This adds a network hop but reuses all middleware (auth, CSRF, throttling). Document the cookie source as `ACE_E2E_AUTH_TOKEN` for the bot identity (matches the e2e-login flow).

Alternative: invoke the handler function directly with a synthetic `HttpRequest`. Faster but bypasses middleware — riskier for auth correctness. Choose the network-hop version for safety.

- [ ] **Step 2: Add per-tool auth**

For routes that require workspace membership, the MCP tool needs to know which workspace it's acting on. Accept a `workspace_slug` argument and pass it through.

- [ ] **Step 3: Mark a handful of endpoints as MCP-exposed**

Start with read-only opp endpoints:

```python
# in apps/opps/api_v2.py:
@router.get("", response=Page[OppCardOut], openapi_extra={"x-mcp-expose": True})
def list_opps(...): ...
```

Opt in: `list_opps`, `get_opp`, `list_runs`, `get_run`, `get_step`, `list_artifacts`, `get_scorecard`. Write actions (fork, gates) stay manual for now.

- [ ] **Step 4: Test via Claude Code**

Connect Claude Code to the MCP server (add to `~/.claude/mcp.json`):

```json
{
  "ace-web": {
    "url": "http://localhost:8000/api/mcp/",
    "headers": { "Cookie": "sessionid_ace=<bot-cookie>" }
  }
}
```

Verify Claude can list opps via the MCP tool.

- [ ] **Step 5: Commit**

```bash
git add apps/api_v2/mcp_server.py apps/opps/api_v2.py
git commit -m "feat(api): wire FastMCP tool bridge + expose read-only opp endpoints"
```

### Task 7.3: Document the MCP surface

**Files:**
- Create: `docs/architecture/mcp-surface.md`

- [ ] **Step 1: Write the doc**

Cover:
- How an endpoint opts into MCP exposure (`x-mcp-expose: True`)
- The auth model (bot-identity session cookie)
- Which endpoints are exposed today
- How to connect Claude Code to the local MCP server
- Production exposure: MCP is auth-gated by the same session cookie machinery as REST

- [ ] **Step 2: Commit**

```bash
git add docs/architecture/mcp-surface.md
git commit -m "docs(api): document the MCP surface and how to expose endpoints"
```

---

## Phase 8: Orthogonal tooling modernization

Optional but in scope per "I want it all perfect." Each task is independent — skip any that don't appeal.

### Task 8.1: Migrate to uv for Python deps

**Files:**
- Create: `uv.lock`
- Modify: `pyproject.toml` (add `[tool.uv]` block if needed)
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `.github/workflows/*.yml`

- [ ] **Step 1: Install uv locally**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

- [ ] **Step 2: Generate lockfile**

```bash
uv lock
```

Inspect `uv.lock`. Commit it.

- [ ] **Step 3: Update Dockerfile**

Replace `RUN pip install -e .` blocks with `uv sync --frozen`. Install uv in the build stage.

- [ ] **Step 4: Update CI workflows**

Replace `pip install` with `uv sync`. CI is ~5× faster.

- [ ] **Step 5: Verify Docker build + CI**

```bash
docker build -t ace-web-test .
```

Expected: clean build.

- [ ] **Step 6: Commit**

```bash
git add uv.lock pyproject.toml Dockerfile .github/workflows/
git commit -m "chore: migrate Python deps from pip to uv"
```

### Task 8.2: Add basedpyright type checking

**Files:**
- Modify: `pyproject.toml`
- Create: `.github/workflows/typecheck.yml`

- [ ] **Step 1: Add config**

Edit `pyproject.toml`:

```toml
[tool.basedpyright]
include = ["apps", "config"]
exclude = ["**/migrations", "**/__pycache__"]
pythonVersion = "3.11"
typeCheckingMode = "standard"  # or "strict" if you're brave
```

- [ ] **Step 2: Run locally**

```bash
pip install basedpyright
basedpyright apps/ config/
```

Triage initial errors. Fix the easy ones inline. Use `# pyright: ignore` for the genuinely-tricky ones (Django dynamic attrs).

- [ ] **Step 3: Wire CI**

Add a `typecheck` job in `.github/workflows/typecheck.yml`:

```yaml
name: Type check

on: [push, pull_request]

jobs:
  basedpyright:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -e ".[dev]" basedpyright
      - run: basedpyright apps/ config/
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml .github/workflows/typecheck.yml
git commit -m "chore: add basedpyright type checking + CI gate"
```

### Task 8.3: Replace ad-hoc Anthropic SDK calls with Pydantic AI

**Files:**
- Modify: any module that imports `anthropic` directly

- [ ] **Step 1: Inventory current usages**

```bash
rg "from anthropic|import anthropic" apps/
```

Note each call site.

- [ ] **Step 2: Add dep**

```toml
"pydantic-ai>=0.0.20",
```

- [ ] **Step 3: Migrate one call site at a time**

For each call site, replace the hand-rolled `client.messages.create(...)` with a typed `Agent` from Pydantic AI:

```python
from pydantic import BaseModel
from pydantic_ai import Agent


class JudgeOutput(BaseModel):
    verdict: Literal["pass", "warn", "fail"]
    rationale: str


judge_agent = Agent("claude-opus-4-7", result_type=JudgeOutput)
result = await judge_agent.run(prompt)
verdict: JudgeOutput = result.data
```

Each migration is its own commit.

- [ ] **Step 4: Drop the `anthropic` dependency once it's unused**

```bash
rg "from anthropic|import anthropic" apps/
```

If empty: remove from `pyproject.toml`.

- [ ] **Step 5: Commit**

### Task 8.4: Add Logfire observability

**Files:**
- Modify: `pyproject.toml`
- Modify: `config/settings/production.py`

- [ ] **Step 1: Add dep**

```toml
"logfire[django]>=0.50",
```

- [ ] **Step 2: Configure**

Edit `config/settings/production.py`:

```python
import logfire

logfire.configure(
    token=env("LOGFIRE_TOKEN", default=None),
    service_name="ace-web",
    service_version=env("VERSION", default="dev"),
)
logfire.instrument_django()
logfire.instrument_httpx()
logfire.instrument_pydantic()
```

- [ ] **Step 3: Add `LOGFIRE_TOKEN` to AWS Secrets Manager + ECS task-def**

- [ ] **Step 4: Verify in Logfire dashboard**

Deploy. Open https://logfire.pydantic.dev. Verify traces are arriving with request/response data, Pydantic model validation events, and httpx spans for outbound calls (Drive, Connect OAuth, Nova OAuth).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml config/settings/production.py deploy/aws/task-definition.json
git commit -m "feat(observability): wire Logfire for request tracing + Pydantic + httpx spans"
```

---

## Final regression + deploy

### Task F.1: Full repository test sweep

- [ ] **Step 1: Backend**

```bash
pytest -v
```

Expected: every test passes.

- [ ] **Step 2: Frontend**

```bash
cd frontend && bunx tsc -b && bun run test && bun run build
```

Expected: clean.

- [ ] **Step 3: Schemathesis**

```bash
docker compose up -d
SCHEMATHESIS_AUTH_COOKIE=<value> pytest tests/contract/ -v
```

Expected: every endpoint conforms to its schema.

- [ ] **Step 4: Manual smoke**

Walk through every primary surface in a real browser. Verify:
- Scalar docs at `/api/docs/` — every endpoint listed, "Try it" works
- Redoc at `/api/redoc/` — clean rendering
- Login → workspace → opps → sessions → fork → discuss in chat
- Mobile orchestration (if relevant in this env)
- System tab

### Task F.2: Deploy to labs

- [ ] **Step 1: Open PR**

```bash
gh pr create --title "API modernization: DRF → Django Ninja + Pydantic + OpenAPI + FastMCP" --body "..."
```

- [ ] **Step 2: Merge after review**

- [ ] **Step 3: Deploy**

```bash
gh workflow run deploy-ace-web-labs.yml --ref main -f run_migrations=true
```

- [ ] **Step 4: Verify in prod**

Open `https://labs.connect.dimagi.com/ace/api/docs/` — Scalar should render the full schema. Spot-check 3-4 endpoints via "Try it". Run schemathesis against prod (read-only endpoints only).

### Task F.3: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add to "Key architectural decisions"**

```markdown
- **API is Pydantic-first via Django Ninja**: every request/response is a Pydantic v2 model declared in `apps/<app>/schemas.py`. Routes live in `apps/<app>/api_v2.py`, registered on the single `NinjaAPI` instance in `apps/api_v2/api.py`. Errors are RFC 7807 `application/problem+json`. Schema doc UI at `/api/docs/` (Scalar) + `/api/redoc/`. Frontend types are generated from the OpenAPI 3.1 schema by `openapi-typescript` into `frontend/src/api/generated.ts` and consumed via `openapi-fetch`. Contract tests run in CI via Schemathesis. DRF is no longer in the codebase as of 2026-XX-XX.
- **MCP surface**: `/api/mcp/` exposes a curated set of read-only endpoints as MCP tools via FastMCP. Endpoints opt in via `openapi_extra={"x-mcp-expose": True}` on their Ninja route decorator. See `docs/architecture/mcp-surface.md`.
```

- [ ] **Step 2: Add to "Stack"**

Update the Backend line to reflect Ninja + Pydantic (drop DRF).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md to reflect Ninja + Pydantic + OpenAPI architecture"
```

---

## Acceptance criteria

This plan is complete when:

1. [ ] `/api/docs/` (Scalar) renders the full schema for every endpoint.
2. [ ] `frontend/src/api/types.ts` no longer exists; every frontend client uses `openapi-fetch` typed against `generated.ts`.
3. [ ] `apps/common/envelope.py` no longer exists.
4. [ ] `djangorestframework` is not in `pyproject.toml` or `INSTALLED_APPS`.
5. [ ] Every endpoint has a Pydantic schema and a contract test.
6. [ ] Schemathesis CI job is green.
7. [ ] `/api/mcp/` exposes at least the read-only opp endpoints; Claude Code can call them.
8. [ ] CLAUDE.md reflects the new architecture.
9. [ ] Labs deploy is live and Scalar docs are accessible at `https://labs.connect.dimagi.com/ace/api/docs/`.
10. [ ] An external caller can read `/api/docs/`, generate a client in any language from the same OpenAPI 3.1 schema, and call ace-web — and CI proves the schema matches reality.
