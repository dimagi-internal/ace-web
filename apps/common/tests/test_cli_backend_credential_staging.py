"""Per-session credential staging tests.

Each CLIBackend.stream_completion() call must stage the session owner's
resolved credential blob into a fresh temp HOME directory so concurrent
chats from different users don't clobber each other's
``~/.claude/.credentials.json``.
"""
import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from apps.common.cli_backend import CLIBackend
from apps.common.models import SystemConfig, UserCredential
from apps.sessions.models import Session

REAL = "sk-ant-oat01-" + "x" * 40


@pytest.mark.django_db
def test_staged_env_uses_user_blob_when_present(tmp_path):
    user = get_user_model().objects.create_user(email="a@dimagi.com")
    blob = {"claudeAiOauth": {"accessToken": REAL, "refreshToken": "r"}}
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps(blob),
        token_prefix=REAL[:15],
    )
    session = Session.objects.create(owner=user, slug="abc", title="t")

    backend = CLIBackend()
    env, staged_home = backend._stage_env_for(session)
    try:
        assert env["HOME"] == staged_home
        creds_path = Path(staged_home) / ".claude" / ".credentials.json"
        assert creds_path.exists()
        stored = json.loads(creds_path.read_text())
        assert stored["claudeAiOauth"]["accessToken"] == REAL
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == REAL
        assert "ANTHROPIC_API_KEY" not in env
    finally:
        backend._teardown_staged_home(staged_home)
    assert not Path(staged_home).exists()


@pytest.mark.django_db
def test_staged_env_falls_back_to_global():
    user = get_user_model().objects.create_user(email="b@dimagi.com")
    global_token = "sk-ant-oat01-" + "g" * 40
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": global_token}}),
    )
    session = Session.objects.create(owner=user, slug="def", title="t2")

    backend = CLIBackend()
    env, staged_home = backend._stage_env_for(session)
    try:
        stored = json.loads((Path(staged_home) / ".claude" / ".credentials.json").read_text())
        assert stored["claudeAiOauth"]["accessToken"] == global_token
    finally:
        backend._teardown_staged_home(staged_home)


@pytest.mark.django_db
def test_staged_env_when_no_credentials_anywhere(monkeypatch):
    """Owner has no UserCredential, no global SystemConfig blob, no env var.
    Staging should not write a credentials file and should not set
    CLAUDE_CODE_OAUTH_TOKEN — the subprocess will fail naturally and surface
    a clear CLI error to the user."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    user = get_user_model().objects.create_user(email="empty@dimagi.com")
    session = Session.objects.create(owner=user, slug="emp", title="t")

    backend = CLIBackend()
    env, staged_home = backend._stage_env_for(session)
    try:
        creds_path = Path(staged_home) / ".claude" / ".credentials.json"
        assert not creds_path.exists()
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
        assert env["HOME"] == staged_home
    finally:
        backend._teardown_staged_home(staged_home)


@pytest.mark.django_db
def test_staged_env_reconstructs_blob_from_env_source(monkeypatch):
    """When the resolver returns source='env', _load_blob_for_token synthesizes
    a minimal {"claudeAiOauth": {"accessToken": ...}} blob so the CLI sees a
    well-formed credentials file."""
    env_token = "sk-ant-oat01-" + "e" * 40
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", env_token)
    user = get_user_model().objects.create_user(email="env@dimagi.com")
    session = Session.objects.create(owner=user, slug="env-src", title="t")

    backend = CLIBackend()
    env, staged_home = backend._stage_env_for(session)
    try:
        creds_path = Path(staged_home) / ".claude" / ".credentials.json"
        assert creds_path.exists()
        stored = json.loads(creds_path.read_text())
        assert stored == {"claudeAiOauth": {"accessToken": env_token}}
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == env_token
    finally:
        backend._teardown_staged_home(staged_home)


@pytest.mark.django_db
def test_staged_homes_are_isolated_per_invocation():
    user = get_user_model().objects.create_user(email="c@dimagi.com")
    blob = {"claudeAiOauth": {"accessToken": REAL}}
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps(blob),
        token_prefix=REAL[:15],
    )
    session = Session.objects.create(owner=user, slug="ghi", title="t3")

    backend = CLIBackend()
    _, home1 = backend._stage_env_for(session)
    _, home2 = backend._stage_env_for(session)
    try:
        assert home1 != home2
    finally:
        backend._teardown_staged_home(home1)
        backend._teardown_staged_home(home2)
