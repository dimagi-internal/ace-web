"""Backend selector must be user-aware.

The docstring on ``backend_selector`` promises the status banner and the
send path always agree. The banner calls ``validate_stored_token(user=...)``;
the send path must call ``get_chat_backend(user=...)`` with the same user
so a user with only a personal blob doesn't see "Active" while the send
path falls through to ApiBackend.
"""
import json

import pytest
from django.contrib.auth import get_user_model

from apps.common import auth_flow, backend_selector
from apps.common.models import UserCredential


@pytest.fixture(autouse=True)
def stub_live(monkeypatch):
    monkeypatch.setattr(
        auth_flow,
        "_check_token_via_cli",
        lambda blob_json=None, on_refresh=None: True,
    )
    auth_flow._invalidate_validation_cache()


@pytest.fixture(autouse=True)
def reset_cache():
    backend_selector.reset_instance_cache()
    yield
    backend_selector.reset_instance_cache()


@pytest.mark.django_db
def test_backend_picks_cli_when_user_has_blob(monkeypatch):
    """User-only blob + no global + no env → CLIBackend when called with user."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    user = get_user_model().objects.create_user(email="bs@dimagi.com")
    token = "sk-ant-oat01-" + "x" * 40
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps({"claudeAiOauth": {"accessToken": token}}),
        token_prefix=token[:15],
    )
    backend = backend_selector.get_chat_backend(user=user)
    from apps.common.cli_backend import CLIBackend
    assert isinstance(backend, CLIBackend)


@pytest.mark.django_db
def test_backend_without_user_falls_back_to_api_when_api_key_set(
    monkeypatch, settings
):
    """When called with user=None and no global blob, ApiBackend wins if API key set."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    settings.ANTHROPIC_API_KEY = "test-key"
    backend = backend_selector.get_chat_backend(user=None)
    from apps.common.api_backend import ApiBackend
    assert isinstance(backend, ApiBackend)


@pytest.mark.django_db
def test_backend_without_user_ignores_per_user_blobs(monkeypatch, settings):
    """user=None must NOT pick up somebody else's personal blob."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    settings.ANTHROPIC_API_KEY = "test-key"
    someone = get_user_model().objects.create_user(email="someone@dimagi.com")
    token = "sk-ant-oat01-" + "q" * 40
    UserCredential.objects.create(
        user=someone,
        blob_encrypted=json.dumps({"claudeAiOauth": {"accessToken": token}}),
        token_prefix=token[:15],
    )
    backend = backend_selector.get_chat_backend(user=None)
    from apps.common.api_backend import ApiBackend
    assert isinstance(backend, ApiBackend)
