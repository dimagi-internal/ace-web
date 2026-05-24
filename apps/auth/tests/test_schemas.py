"""Round-trip tests for apps.auth.schemas."""
from __future__ import annotations

from apps.auth.schemas import (
    CliAuthUploadOut,
    DevLoginIn,
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
