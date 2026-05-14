"""Round-trip tests for apps.auth.schemas."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.auth.schemas import (
    CliAuthUploadOut,
    DevLoginIn,
    E2ELoginIn,
    E2ELoginOut,
    MeOut,
    NovaAuthStatusOut,
)
from apps.common.schemas import WorkspaceRefOut


def test_me_out_no_workspaces():
    me = MeOut(id=1, email="alice@example.com", display_name="Alice")
    assert me.workspaces == []
    assert me.is_staff is False


def test_me_out_with_workspaces():
    ws = WorkspaceRefOut(slug="dimagi-team", name="Dimagi Team")
    me = MeOut(
        id=2,
        email="bob@dimagi.com",
        display_name="Bob",
        is_staff=True,
        workspaces=[ws],
    )
    d = me.model_dump()
    assert d["workspaces"][0]["slug"] == "dimagi-team"
    assert d["is_staff"] is True


def test_e2e_login_in_round_trip():
    body = E2ELoginIn(email="ace@dimagi-ai.com", token="secret-token-123")
    assert body.display_name == ""
    assert body.token == "secret-token-123"


def test_e2e_login_in_rejects_unknown_field():
    with pytest.raises(ValidationError):
        E2ELoginIn(email="x@y.com", token="t", extra_field="bad")  # type: ignore[call-arg]


def test_e2e_login_out():
    out = E2ELoginOut(user_id=7, email="ace@dimagi-ai.com")
    assert out.user_id == 7


def test_nova_auth_status_not_connected():
    status = NovaAuthStatusOut(connected=False, valid=False)
    assert status.expires_at is None
    assert status.can_manage is False


def test_cli_auth_upload_out():
    out = CliAuthUploadOut(
        stored=True,
        authenticated=True,
        token_prefix="sk-ant-oat01-abc",
        scope="user",
    )
    assert out.scope == "user"
    assert out.stored is True


def test_dev_login_in_defaults():
    body = DevLoginIn(email="dev@example.com")
    assert body.display_name == ""
