"""Root pytest configuration, shared across every test directory.

`tests/conftest.py` only scopes to the `tests/` directory. Fixtures that need
to apply to `apps/*/tests/` as well must live at the repo root.
"""
from pathlib import Path

import pytest
from django.core.cache import cache

# pyproject.toml sets `python_files = "test_*.py"`, which causes pytest to
# collect `apps/auth/test_login_views.py` as a test module. That file is the
# dev-only test-login VIEW (named "test login" as in "login for testing"),
# not a pytest module. Its `test_login` function is a Django view and has
# no pytest-compatible signature. Skip collection for it explicitly.
collect_ignore_glob = ["apps/auth/test_login_views.py"]


@pytest.fixture(autouse=True)
def _flush_default_cache():
    """Django's LocMem cache is process-wide and survives transaction
    rollback, so without this the apps/opps drive_cache TTL entries
    leak across tests — yielding stale Drive listings from a previous
    test fixture and unstable inner-call counts on cache assertions."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(scope="session", autouse=True)
def _ensure_frontend_index_placeholder():
    """Create a placeholder `frontend/dist/index.html` if missing.

    The SPA catch-all view in `config/urls.py` renders `index.html`, which is
    normally produced by `vite build` as a build artifact. A handful of tests
    (notably `apps/auth/tests/test_oauth_views.py::
    test_spa_catch_all_serves_index_when_logged_in`) exercise that view and
    fail with `TemplateDoesNotExist: index.html` when the frontend hasn't been
    built — which is the usual state in CI and in developer dev loops that
    only run pytest.

    Creating a minimal placeholder HTML file here keeps pytest green without
    requiring every pytest invocation to also run `npm run build` first. The
    placeholder is only written if `frontend/dist/index.html` doesn't already
    exist, so a real build (local or in a build-the-frontend-first CI job)
    takes precedence.
    """
    repo_root = Path(__file__).resolve().parent
    dist = repo_root / "frontend" / "dist"
    index = dist / "index.html"
    if not index.exists():
        dist.mkdir(parents=True, exist_ok=True)
        index.write_text(
            "<!doctype html><html><body>"
            "<div id=\"root\"></div>"
            "</body></html>\n"
        )
    yield
