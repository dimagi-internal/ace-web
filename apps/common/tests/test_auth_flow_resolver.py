import json

import pytest
from django.contrib.auth import get_user_model

from apps.common import auth_flow
from apps.common.models import SystemConfig, UserCredential

REAL_TOKEN = "sk-ant-oat01-" + "x" * 40  # token_looks_real() needs len>=40 + prefix


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(email="resolver@dimagi.com")


@pytest.fixture
def clear_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)


@pytest.mark.django_db
def test_resolver_prefers_user_blob(user, clear_env):
    blob = {"claudeAiOauth": {"accessToken": REAL_TOKEN}}
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps(blob),
        token_prefix=REAL_TOKEN[:15],
    )
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-global" + "y" * 30}}),
    )
    result = auth_flow.get_stored_token(user=user)
    assert result is not None
    token, source = result
    assert token == REAL_TOKEN
    assert source == "user"


@pytest.mark.django_db
def test_resolver_falls_back_to_global(user, clear_env):
    global_token = "sk-ant-oat01-" + "g" * 40
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": global_token}}),
    )
    result = auth_flow.get_stored_token(user=user)
    assert result == (global_token, "global")


@pytest.mark.django_db
def test_resolver_env_is_last_resort(user, monkeypatch):
    env_token = "sk-ant-oat01-" + "e" * 40
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", env_token)
    result = auth_flow.get_stored_token(user=user)
    assert result == (env_token, "env")


@pytest.mark.django_db
def test_resolver_returns_none_when_empty(user, clear_env):
    assert auth_flow.get_stored_token(user=user) is None


@pytest.mark.django_db
def test_resolver_without_user_skips_user_table(clear_env):
    global_token = "sk-ant-oat01-" + "g" * 40
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": global_token}}),
    )
    result = auth_flow.get_stored_token(user=None)
    assert result == (global_token, "global")


@pytest.mark.django_db
def test_resolver_skips_user_blob_marked_invalid(user, clear_env):
    """Live-invalidated user blob should fall through to global."""
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps({"claudeAiOauth": {"accessToken": REAL_TOKEN}}),
        token_prefix=REAL_TOKEN[:15],
        last_validation_ok=False,  # marked bad at upload time
    )
    global_token = "sk-ant-oat01-" + "g" * 40
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": global_token}}),
    )
    assert auth_flow.get_stored_token(user=user) == (global_token, "global")


@pytest.mark.django_db
def test_resolver_skips_unreal_user_token(user, clear_env):
    """User blob with a too-short token should be ignored, fall through to global."""
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-short"}}),
        token_prefix="sk-ant-oat01-sh",
    )
    global_token = "sk-ant-oat01-" + "g" * 40
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": global_token}}),
    )
    result = auth_flow.get_stored_token(user=user)
    assert result == (global_token, "global")
