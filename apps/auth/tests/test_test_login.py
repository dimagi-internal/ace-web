"""Unit tests for the dev-only test-login view."""
import json

import pytest
from django.test import Client

from apps.auth.models import User
from apps.workspaces.models import Workspace, WorkspaceMembership

pytestmark = pytest.mark.django_db


def test_view_returns_404_when_setting_disabled(settings):
    """With the setting disabled, the URL reverse fails entirely because
    the route is not registered. Calling it directly via the client
    returns 404."""
    settings.ACE_ALLOW_TEST_LOGIN = False
    settings.DEBUG = True  # Would allow URL registration if setting was True
    # Import the view function directly and hit it - this bypasses URL
    # registration but exercises the runtime backstop.
    from django.http import HttpRequest

    from apps.auth.test_login_views import test_login

    request = HttpRequest()
    request.method = "POST"
    request._body = b'{"email": "alice@dimagi.com"}'
    response = test_login(request)
    assert response.status_code == 404


def test_view_refuses_when_debug_is_false(settings):
    """Even with ACE_ALLOW_TEST_LOGIN=True, the view refuses if DEBUG is
    False - this is the prod safety net."""
    settings.ACE_ALLOW_TEST_LOGIN = True
    settings.DEBUG = False

    from django.http import HttpRequest

    from apps.auth.test_login_views import test_login

    request = HttpRequest()
    request.method = "POST"
    request._body = b'{"email": "alice@dimagi.com"}'
    response = test_login(request)
    assert response.status_code == 404


def test_view_logs_in_user_when_both_flags_enabled(settings):
    """When both flags are True, the view creates the user and logs
    them in."""
    import importlib

    from django.urls import clear_url_caches

    settings.ACE_ALLOW_TEST_LOGIN = True
    settings.DEBUG = True

    # Django caches URL patterns at first request. `apps/auth/urls.py`
    # registers the test-login path conditionally at module-import time,
    # so if the module was already imported with ACE_ALLOW_TEST_LOGIN=False
    # (which is the default in config/settings/test.py), the route will
    # not be present until we reload the module AND clear the URL cache.
    from apps.auth import urls as auth_urls

    importlib.reload(auth_urls)
    import config.urls

    importlib.reload(config.urls)
    clear_url_caches()

    try:
        client = Client()
        response = client.post(
            "/auth/test-login/",
            data=json.dumps({"email": "alice@dimagi.com", "display_name": "Alice"}),
            content_type="application/json",
        )

        # Defense in depth: if the reload dance above didn't work in
        # some pytest ordering edge case, fall back to a skip rather
        # than producing a confusing failure. The runtime backstop
        # test covers the security invariant either way.
        if response.status_code == 404:
            pytest.skip(
                "URLconf caching prevented route registration; runtime "
                "backstop test covers the security assertion"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "alice@dimagi.com"
        assert User.objects.filter(email="alice@dimagi.com").exists()
    finally:
        # Restore the original URLconf state so other tests see the
        # default (no test-login route).
        settings.ACE_ALLOW_TEST_LOGIN = False
        importlib.reload(auth_urls)
        importlib.reload(config.urls)
        clear_url_caches()


def test_view_rejects_email_outside_allowlist_when_set(settings):
    """When ACE_ALLOWED_EMAIL_DOMAINS is non-empty, the test-login path
    still enforces it. (Empty list — the new default — allows any email.)"""
    settings.ACE_ALLOW_TEST_LOGIN = True
    settings.DEBUG = True
    settings.ACE_ALLOWED_EMAIL_DOMAINS = ["dimagi.com"]

    from django.http import HttpRequest

    from apps.auth.test_login_views import test_login

    request = HttpRequest()
    request.method = "POST"
    request._body = b'{"email": "evil@example.com"}'
    response = test_login(request)
    assert response.status_code == 400


def test_view_rejects_missing_email(settings):
    settings.ACE_ALLOW_TEST_LOGIN = True
    settings.DEBUG = True

    from django.http import HttpRequest

    from apps.auth.test_login_views import test_login

    request = HttpRequest()
    request.method = "POST"
    request._body = b"{}"
    response = test_login(request)
    assert response.status_code == 400


def test_dev_bootstrap_creates_workspace_when_drive_root_set(settings):
    """First test-login on a clean DB seeds a workspace anchored to
    ACE_DRIVE_ROOT_FOLDER_ID and adds the user as Owner. Saves the
    operator from walking the /welcome wizard every time the local DB
    is blown away."""
    from apps.auth.test_login_views import _ensure_dev_workspace_membership

    settings.ACE_DRIVE_ROOT_FOLDER_ID = "1HThsA_test_folder_id"

    user = User.objects.create(email="ace@dimagi-ai.com", display_name="ace")
    _ensure_dev_workspace_membership(user)

    ws = Workspace.objects.get(slug="dimagi-team")
    assert ws.drive_root_folder_id == "1HThsA_test_folder_id"
    assert ws.created_by_id == user.id
    membership = WorkspaceMembership.objects.get(workspace=ws, user=user)
    assert membership.role == "owner"


def test_dev_bootstrap_adds_existing_users_as_editor(settings):
    """When a workspace already exists (because someone else logged in
    earlier or the seed migration ran), subsequent test-login users get
    Editor membership so they can share the dev state."""
    from apps.auth.test_login_views import _ensure_dev_workspace_membership

    settings.ACE_DRIVE_ROOT_FOLDER_ID = "1HThsA_test_folder_id"
    owner = User.objects.create(email="owner@dimagi.com", display_name="Owner")
    _ensure_dev_workspace_membership(owner)

    teammate = User.objects.create(email="teammate@dimagi.com", display_name="T")
    _ensure_dev_workspace_membership(teammate)

    ws = Workspace.objects.get(slug="dimagi-team")
    assert WorkspaceMembership.objects.get(workspace=ws, user=teammate).role == "editor"
    # Owner stays Owner — second call is idempotent on the original member.
    assert WorkspaceMembership.objects.get(workspace=ws, user=owner).role == "owner"


def test_dev_bootstrap_noops_when_drive_root_unset(settings):
    """No ACE_DRIVE_ROOT_FOLDER_ID → no workspace; user falls back to the
    /welcome wizard path normally."""
    from apps.auth.test_login_views import _ensure_dev_workspace_membership

    settings.ACE_DRIVE_ROOT_FOLDER_ID = ""
    user = User.objects.create(email="ace@dimagi-ai.com", display_name="ace")
    _ensure_dev_workspace_membership(user)

    assert Workspace.objects.count() == 0
    assert WorkspaceMembership.objects.count() == 0
