"""Pydantic v2 schemas for the /api/v2/workspaces surface."""
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


class WorkspaceInviteIn(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    role: WorkspaceRole


class WorkspaceInviteOut(StrictModel, TimestampMixin):
    token: str
    email: str
    role: WorkspaceRole
    accepted: bool
    accepted_at: dt.datetime | None = None
