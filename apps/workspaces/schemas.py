"""Pydantic v2 schemas for the /api/workspaces surface."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from apps.common.schemas import StrictModel, TimestampMixin, UserRefOut

# The four workspace roles, highest first (`models.WorkspaceMembership`).
WorkspaceRole = Literal["owner", "admin", "editor", "viewer"]


class WorkspaceOut(StrictModel, TimestampMixin):
    slug: str
    name: str
    drive_root_folder_id: str
    role: WorkspaceRole  # the requesting user's role in this workspace
    member_count: int = Field(ge=0)
    # Tenancy a new opp starts with (apps.opps.tenancy.Tenancy). Owner-editable
    # via PATCH; never rewrites existing opps.
    default_tenancy: dict = Field(default_factory=dict)


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
    # Merged into the default (null clears a key); validated as
    # apps.opps.tenancy.Tenancy.
    default_tenancy: dict | None = Field(default=None)


class WorkspaceInviteIn(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    role: WorkspaceRole


class WorkspaceInviteOut(StrictModel, TimestampMixin):
    token: str
    email: str
    role: WorkspaceRole
    accepted: bool
    accepted_at: dt.datetime | None = None
    expires_at: dt.datetime | None = None
    # True when the accept link was emailed to `email`. False when outbound
    # email is off or the send failed — share the link by hand then.
    email_sent: bool = False


class WorkspacePendingInviteOut(StrictModel):
    """GET /api/workspaces/{slug}/invites — one invite nobody has acted on."""

    id: int
    email: str
    role: WorkspaceRole
    invited_by_email: str
    created_at: dt.datetime
    expires_at: dt.datetime


class InvitePreviewOut(StrictModel):
    """GET /api/invites/{token} — public invite preview (no auth required)."""

    workspace_slug: str
    workspace_display_name: str
    role: WorkspaceRole
    invited_by_email: str
    email: str
    expires_at: dt.datetime


class MyPendingInviteOut(StrictModel):
    """GET /api/invites/mine — one pending invite addressed to the signed-in user.

    Only ever the caller's own invites (matched on their email), so it reveals
    nothing about workspaces they were not invited to."""

    workspace_slug: str
    workspace_display_name: str
    role: WorkspaceRole
    invited_by_email: str
    expires_at: dt.datetime
    # SPA path that redeems the invite (the same `/invite/<token>` the invite
    # email links to), relative to the app's base path.
    accept_url: str


class InviteAcceptOut(StrictModel):
    """POST /api/invites/{token}/accept — accept an invite."""

    workspace_slug: str
    role: WorkspaceRole
