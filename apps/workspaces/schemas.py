"""Pydantic v2 schemas for the /api/workspaces surface."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from apps.common.schemas import StrictModel, TimestampMixin, UserRefOut

WorkspaceRole = Literal["owner", "editor", "viewer"]


class WorkspaceOut(StrictModel, TimestampMixin):
    slug: str
    name: str
    drive_root_folder_id: str
    role: WorkspaceRole  # the requesting user's role in this workspace
    member_count: int = Field(ge=0)
    # Lowercased email domains (no leading "@") whose users are auto-added
    # as Editor on login. Editable by Owners via PATCH /workspaces/{slug}.
    auto_join_domains: list[str] = Field(default_factory=list)


class WorkspaceMemberOut(StrictModel):
    id: int
    user: UserRefOut
    role: WorkspaceRole
    joined_at: dt.datetime


class WorkspaceCreateIn(StrictModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=128)
    drive_root_folder_id: str = Field(min_length=1)


class WorkspacePatchIn(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    drive_root_folder_id: str | None = Field(default=None, min_length=1)
    auto_join_domains: list[str] | None = Field(default=None)


class WorkspaceInviteIn(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    role: WorkspaceRole


class WorkspaceInviteOut(StrictModel, TimestampMixin):
    token: str
    email: str
    role: WorkspaceRole
    accepted: bool
    accepted_at: dt.datetime | None = None


class InvitePreviewOut(StrictModel):
    """GET /api/invites/{token} — public invite preview (no auth required)."""

    workspace_slug: str
    workspace_display_name: str
    role: WorkspaceRole
    invited_by_email: str
    email: str
    expires_at: dt.datetime


class InviteAcceptOut(StrictModel):
    """POST /api/invites/{token}/accept — accept an invite."""

    workspace_slug: str
    role: WorkspaceRole
