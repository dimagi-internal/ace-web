"""Tests for the PTY auth flow driver. The PTY itself is mocked — these tests
exercise the public API and the regex helpers, not the actual claude binary.
"""
import os
from unittest.mock import patch

import pytest

from apps.common import auth_flow


def test_extract_url_strips_ansi_and_finds_oauth_url():
    raw = "\x1b[2mPaste code\x1b[0m: https://claude.com/cai/oauth/authorize?client_id=abc&state=xyzPasteCode"
    url = auth_flow._extract_url(raw)
    assert url == "https://claude.com/cai/oauth/authorize?client_id=abc&state=xyz"


def test_extract_token_finds_sk_ant_oat_token():
    raw = "Token created: sk-ant-oat01-AbCdEfGhIjKlMnOp123456 (saved)"
    token = auth_flow._extract_token(raw)
    assert token == "sk-ant-oat01-AbCdEfGhIjKlMnOp123456"


def test_extract_returns_none_when_absent():
    assert auth_flow._extract_url("nothing here") is None
    assert auth_flow._extract_token("nothing here") is None


def test_store_and_load_token(tmp_path, monkeypatch):
    token_file = tmp_path / "oauth-token"
    monkeypatch.setattr(auth_flow, "TOKEN_FILE", str(token_file))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    auth_flow.store_token("sk-ant-oat01-test")
    assert token_file.read_text() == "sk-ant-oat01-test"
    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-test"
    assert oct(token_file.stat().st_mode)[-3:] == "600"

    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    loaded = auth_flow.load_stored_token()
    assert loaded == "sk-ant-oat01-test"
    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-test"


def test_get_stored_token_prefers_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fromenv")
    assert auth_flow.get_stored_token() == "sk-ant-oat01-fromenv"


def test_poll_when_no_session_active():
    auth_flow.cancel()  # ensure no session
    result = auth_flow.poll()
    assert result["active"] is False


def test_start_then_cancel_cleans_up():
    """Smoke test the lifecycle without actually invoking claude."""
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value.poll.return_value = None
        with patch("pty.openpty", return_value=(0, 1)), \
             patch("os.close"), \
             patch("os.read", side_effect=[b"", OSError("EOF")]), \
             patch("threading.Thread"):
            try:
                # start() will time out (no URL appears) — that's fine,
                # we just want cancel() to clean up cleanly
                with pytest.raises(RuntimeError):
                    auth_flow.start()
            finally:
                auth_flow.cancel()


def test_token_loader_loads_at_boot(tmp_path, monkeypatch):
    from apps.common import token_loader
    token_file = tmp_path / "oauth-token"
    token_file.write_text("sk-ant-oat01-boot")
    monkeypatch.setattr(auth_flow, "TOKEN_FILE", str(token_file))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    token_loader.load_at_boot()
    assert os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") == "sk-ant-oat01-boot"
