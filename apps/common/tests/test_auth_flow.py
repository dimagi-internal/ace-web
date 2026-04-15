"""Tests for token persistence. The PTY `claude setup-token` flow was
removed — users now paste a pre-generated token into the UI."""
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

from apps.common import auth_flow


def test_store_and_load_token(tmp_path, monkeypatch):
    token_file = tmp_path / "oauth-token"
    monkeypatch.setattr(auth_flow, "TOKEN_FILE", str(token_file))
    monkeypatch.setattr(auth_flow, "TOKEN_SECRET_ID", None)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    auth_flow.store_token("sk-ant-oat01-test")
    assert token_file.read_text() == "sk-ant-oat01-test"
    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-test"
    assert oct(token_file.stat().st_mode)[-3:] == "600"

    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    loaded = auth_flow.load_stored_token()
    assert loaded == "sk-ant-oat01-test"
    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-test"


def test_store_token_strips_whitespace(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_flow, "TOKEN_FILE", str(tmp_path / "tok"))
    monkeypatch.setattr(auth_flow, "TOKEN_SECRET_ID", None)

    auth_flow.store_token("  sk-ant-oat01-padded  \n")
    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-padded"


def test_store_token_rejects_bad_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_flow, "TOKEN_FILE", str(tmp_path / "tok"))
    with pytest.raises(auth_flow.InvalidTokenError):
        auth_flow.store_token("not-a-token")
    with pytest.raises(auth_flow.InvalidTokenError):
        auth_flow.store_token("")


def test_get_stored_token_prefers_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fromenv")
    assert auth_flow.get_stored_token() == "sk-ant-oat01-fromenv"


def test_store_token_pushes_to_secrets_manager_when_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_flow, "TOKEN_FILE", str(tmp_path / "tok"))
    monkeypatch.setattr(auth_flow, "TOKEN_SECRET_ID", "my-secret")
    monkeypatch.setattr(auth_flow, "TOKEN_SECRET_REGION", "us-east-1")

    fake_client = MagicMock()
    fake_boto3 = types.ModuleType("boto3")
    fake_boto3.client = MagicMock(return_value=fake_client)
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    auth_flow.store_token("sk-ant-oat01-new")

    fake_boto3.client.assert_called_once_with("secretsmanager", region_name="us-east-1")
    fake_client.put_secret_value.assert_called_once_with(
        SecretId="my-secret", SecretString="sk-ant-oat01-new"
    )


def test_store_token_skips_secrets_manager_when_not_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_flow, "TOKEN_FILE", str(tmp_path / "tok"))
    monkeypatch.setattr(auth_flow, "TOKEN_SECRET_ID", None)

    fake_boto3 = types.ModuleType("boto3")
    fake_boto3.client = MagicMock(side_effect=AssertionError("should not be called"))
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    auth_flow.store_token("sk-ant-oat01-local")
    fake_boto3.client.assert_not_called()


def test_store_token_swallows_secrets_manager_errors(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(auth_flow, "TOKEN_FILE", str(tmp_path / "tok"))
    monkeypatch.setattr(auth_flow, "TOKEN_SECRET_ID", "my-secret")

    fake_boto3 = types.ModuleType("boto3")
    fake_boto3.client = MagicMock(side_effect=RuntimeError("no creds"))
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    token_file = tmp_path / "tok"
    auth_flow.store_token("sk-ant-oat01-raises")
    assert token_file.read_text() == "sk-ant-oat01-raises"
    assert "Failed to push token to Secrets Manager" in caplog.text


def test_token_loader_loads_at_boot(tmp_path, monkeypatch):
    from apps.common import token_loader
    token_file = tmp_path / "oauth-token"
    token_file.write_text("sk-ant-oat01-boot")
    monkeypatch.setattr(auth_flow, "TOKEN_FILE", str(token_file))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    token_loader.load_at_boot()
    assert os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") == "sk-ant-oat01-boot"
