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
    env, staged_home, source = backend._stage_env_for(session)
    try:
        assert env["HOME"] == staged_home
        assert source == "user"
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
    env, staged_home, source = backend._stage_env_for(session)
    try:
        assert source == "global"
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
    env, staged_home, source = backend._stage_env_for(session)
    try:
        assert source is None
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
    env, staged_home, source = backend._stage_env_for(session)
    try:
        assert source == "env"
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
    _, home1, _ = backend._stage_env_for(session)
    _, home2, _ = backend._stage_env_for(session)
    try:
        assert home1 != home2
    finally:
        backend._teardown_staged_home(home1)
        backend._teardown_staged_home(home2)


@pytest.mark.django_db
def test_staged_home_dirs_are_owner_only_readable():
    """Per-session staged HOME and its .claude/ subdir must be 0o700.
    Without it, another local user on the same host could list directory
    contents (filenames, sizes). The credentials file itself is 0o600,
    so even with looser dirs the secret bytes were safe — but filename
    enumeration is still avoidable hygiene.
    """
    import os
    import stat

    user = get_user_model().objects.create_user(email="perms@dimagi.com")
    blob = {"claudeAiOauth": {"accessToken": REAL}}
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps(blob),
        token_prefix=REAL[:15],
    )
    session = Session.objects.create(owner=user, slug="perms", title="perms")

    backend = CLIBackend()
    _, home, _ = backend._stage_env_for(session)
    try:
        home_mode = stat.S_IMODE(os.stat(home).st_mode)
        claude_mode = stat.S_IMODE(os.stat(os.path.join(home, ".claude")).st_mode)
        assert home_mode == 0o700, f"staged HOME mode {oct(home_mode)} != 0o700"
        assert claude_mode == 0o700, (
            f"staged .claude/ mode {oct(claude_mode)} != 0o700"
        )
    finally:
        backend._teardown_staged_home(home)


# ── Refresh persistence tests ──────────────────────────────────────────────


@pytest.mark.django_db
def test_persist_refreshed_blob_updates_user_credential():
    """When the staged creds file is modified (simulating a CLI refresh),
    _persist_refreshed_blob writes the new blob back to UserCredential."""
    user = get_user_model().objects.create_user(email="refresh@dimagi.com")
    original_token = "sk-ant-oat01-" + "o" * 40
    original = {"claudeAiOauth": {"accessToken": original_token, "refreshToken": "r1"}}
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps(original),
        token_prefix=original_token[:15],
    )
    session = Session.objects.create(owner=user, slug="refresh-sess", title="t")

    backend = CLIBackend()
    env, staged_home, source = backend._stage_env_for(session)
    assert source == "user"
    try:
        # Simulate CLI refresh by rewriting the creds file
        new_token = "sk-ant-oat01-" + "n" * 40
        new_blob = {"claudeAiOauth": {"accessToken": new_token, "refreshToken": "r2"}}
        creds_path = Path(staged_home) / ".claude" / ".credentials.json"
        creds_path.write_text(json.dumps(new_blob))

        backend._persist_refreshed_blob(session, source, staged_home)

        cred = UserCredential.objects.get(user=user)
        stored = json.loads(cred.blob_encrypted)
        assert stored == new_blob
        assert cred.token_prefix == new_token[:15]
    finally:
        backend._teardown_staged_home(staged_home)


@pytest.mark.django_db
def test_persist_refreshed_blob_is_noop_when_file_missing():
    """If cleanup ran before persist (or subprocess never wrote), no crash."""
    user = get_user_model().objects.create_user(email="gone@dimagi.com")
    session = Session.objects.create(owner=user, slug="gone", title="t")
    backend = CLIBackend()
    # Don't stage — just try to persist a nonexistent dir
    backend._persist_refreshed_blob(session, "user", "/tmp/ace-cli-nonexistent-xyz")
    # No exception = pass


@pytest.mark.django_db
def test_persist_refreshed_blob_noop_on_unchanged_file():
    """If the subprocess didn't rewrite the file, persist writes back the same value."""
    user = get_user_model().objects.create_user(email="same@dimagi.com")
    token = "sk-ant-oat01-" + "s" * 40
    original = {"claudeAiOauth": {"accessToken": token, "refreshToken": "r"}}
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps(original),
        token_prefix=token[:15],
    )
    session = Session.objects.create(owner=user, slug="same-sess", title="t")
    backend = CLIBackend()
    env, staged_home, source = backend._stage_env_for(session)
    try:
        backend._persist_refreshed_blob(session, source, staged_home)
        cred = UserCredential.objects.get(user=user)
        stored = json.loads(cred.blob_encrypted)
        assert stored == original
    finally:
        backend._teardown_staged_home(staged_home)


@pytest.mark.django_db
def test_persist_refreshed_blob_updates_global_systemconfig():
    """Global-source refresh should write back to SystemConfig."""
    user = get_user_model().objects.create_user(email="g@dimagi.com")
    original_token = "sk-ant-oat01-" + "g" * 40
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": original_token}}),
    )
    session = Session.objects.create(owner=user, slug="g-sess", title="t")

    backend = CLIBackend()
    env, staged_home, source = backend._stage_env_for(session)
    assert source == "global"
    try:
        new_token = "sk-ant-oat01-" + "N" * 40
        new_blob = {"claudeAiOauth": {"accessToken": new_token, "refreshToken": "r2"}}
        creds_path = Path(staged_home) / ".claude" / ".credentials.json"
        creds_path.write_text(json.dumps(new_blob))

        backend._persist_refreshed_blob(session, source, staged_home)

        row = SystemConfig.objects.get(key="claude_credentials_blob")
        assert json.loads(row.value) == new_blob
    finally:
        backend._teardown_staged_home(staged_home)


@pytest.mark.django_db
def test_persist_refreshed_blob_env_source_does_not_persist():
    """Env-source refresh has no storage to write back to — should silently no-op."""
    user = get_user_model().objects.create_user(email="envsrc@dimagi.com")
    session = Session.objects.create(owner=user, slug="envsrc", title="t")
    backend = CLIBackend()
    # fabricate a staged home with a new blob in it
    import tempfile
    staged = Path(tempfile.mkdtemp(prefix="ace-cli-test-"))
    (staged / ".claude").mkdir()
    new_blob = {"claudeAiOauth": {"accessToken": "sk-ant-oat01-" + "e" * 40}}
    (staged / ".claude" / ".credentials.json").write_text(json.dumps(new_blob))
    try:
        backend._persist_refreshed_blob(session, "env", str(staged))
        # No exception, no DB rows created
        assert not UserCredential.objects.filter(user=user).exists()
        assert not SystemConfig.objects.filter(key="claude_credentials_blob").exists()
    finally:
        backend._teardown_staged_home(str(staged))


@pytest.mark.django_db
def test_persist_refreshed_blob_skips_malformed_blob():
    """If the refreshed file is structurally broken, don't persist garbage."""
    user = get_user_model().objects.create_user(email="broken@dimagi.com")
    token = "sk-ant-oat01-" + "o" * 40
    original = {"claudeAiOauth": {"accessToken": token}}
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps(original),
        token_prefix=token[:15],
    )
    session = Session.objects.create(owner=user, slug="broken-sess", title="t")
    backend = CLIBackend()
    env, staged_home, source = backend._stage_env_for(session)
    try:
        creds_path = Path(staged_home) / ".claude" / ".credentials.json"
        creds_path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "not-real"}}))
        backend._persist_refreshed_blob(session, source, staged_home)
        cred = UserCredential.objects.get(user=user)
        assert json.loads(cred.blob_encrypted) == original
    finally:
        backend._teardown_staged_home(staged_home)


@pytest.mark.django_db
def test_staged_env_symlinks_plugins_from_real_home(monkeypatch, tmp_path):
    """The staged HOME must symlink ~/.claude/plugins/ from the real HOME so
    claude -p can see installed plugins, slash commands, and MCP servers.
    Without this the assistant runs as a tool-less chatbot in the container.
    """
    fake_home = tmp_path / "real-home"
    real_claude = fake_home / ".claude"
    plugins_dir = real_claude / "plugins" / "cache" / "ace" / "ace" / "0.10.55"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "VERSION").write_text("0.10.55\n")
    (real_claude / "plugins" / "installed_plugins.json").write_text("{}")
    (real_claude / "settings.json").write_text("{\"theme\":\"dark\"}")

    monkeypatch.setenv("HOME", str(fake_home))

    user = get_user_model().objects.create_user(email="plug@dimagi.com")
    blob = {"claudeAiOauth": {"accessToken": REAL, "refreshToken": "r"}}
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps(blob),
        token_prefix=REAL[:15],
    )
    session = Session.objects.create(owner=user, slug="plug-sess", title="t")

    backend = CLIBackend()
    env, staged_home, _ = backend._stage_env_for(session)
    try:
        staged_claude = Path(staged_home) / ".claude"
        # The plugins dir + settings.json must be reachable from the staged HOME.
        assert (staged_claude / "plugins").exists()
        assert (staged_claude / "plugins" / "installed_plugins.json").exists()
        assert (staged_claude / "settings.json").exists()
        # And it really is the real plugin tree (not a fresh empty dir).
        assert (staged_claude / "plugins" / "cache" / "ace" / "ace" / "0.10.55"
                / "VERSION").read_text().strip() == "0.10.55"
        # But credentials.json was NOT symlinked from the real home — we wrote
        # our own session-isolated copy.
        creds_link = staged_claude / ".credentials.json"
        assert creds_link.is_file() and not creds_link.is_symlink()
    finally:
        backend._teardown_staged_home(staged_home)


@pytest.mark.django_db
def test_staged_env_symlink_works_when_real_home_has_no_claude_dir(
    monkeypatch, tmp_path
):
    """If the real HOME has no ~/.claude/ at all (e.g. dev laptop without claude
    installed), staging must still succeed — plugins just won't be available."""
    fake_home = tmp_path / "fresh-home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    user = get_user_model().objects.create_user(email="fresh@dimagi.com")
    blob = {"claudeAiOauth": {"accessToken": REAL, "refreshToken": "r"}}
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps(blob),
        token_prefix=REAL[:15],
    )
    session = Session.objects.create(owner=user, slug="fresh-sess", title="t")

    backend = CLIBackend()
    env, staged_home, _ = backend._stage_env_for(session)
    try:
        staged_claude = Path(staged_home) / ".claude"
        assert staged_claude.is_dir()
        assert (staged_claude / ".credentials.json").exists()
    finally:
        backend._teardown_staged_home(staged_home)
