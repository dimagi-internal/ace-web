import pytest

from apps.workspaces.schemas import (
    WorkspaceCreateIn,
    WorkspaceMemberOut,
    WorkspaceOut,
    WorkspacePatchIn,
)


def test_workspace_out_round_trip():
    raw = {
        "slug": "dimagi-team",
        "name": "Dimagi Team",
        "drive_root_folder_id": "abc123",
        "role": "owner",
        "member_count": 4,
        "created_at": "2026-04-27T12:00:00Z",
        "updated_at": "2026-04-27T12:00:00Z",
    }
    parsed = WorkspaceOut.model_validate(raw)
    assert parsed.slug == "dimagi-team"
    assert parsed.role == "owner"


def test_workspace_member_round_trip():
    raw = {
        "id": 7,
        "user": {"id": 1, "email": "a@example.com", "display_name": "Alice"},
        "role": "editor",
        "joined_at": "2026-04-27T12:00:00Z",
    }
    parsed = WorkspaceMemberOut.model_validate(raw)
    assert parsed.role == "editor"


def test_workspace_create_validation():
    with pytest.raises(ValueError):
        WorkspaceCreateIn(slug="", name="X", drive_root_folder_id="f")
    with pytest.raises(ValueError):
        WorkspaceCreateIn(slug="ok", name="", drive_root_folder_id="f")
    obj = WorkspaceCreateIn(slug="ok", name="Name", drive_root_folder_id="folder-1")
    assert obj.slug == "ok"


def test_workspace_patch_partial():
    obj = WorkspacePatchIn(name="New name")
    dumped = obj.model_dump(exclude_unset=True)
    assert dumped == {"name": "New name"}
