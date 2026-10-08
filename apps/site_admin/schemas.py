"""Pydantic v2 schemas for /api/site-admin."""
from __future__ import annotations

import datetime as dt

from apps.common.schemas import StrictModel


class SiteAdminMembershipOut(StrictModel):
    workspace_slug: str
    workspace_name: str
    role: str


class SiteAdminUserOut(StrictModel):
    id: int
    email: str
    display_name: str
    is_staff: bool
    is_active: bool
    created_at: dt.datetime
    last_login: dt.datetime | None = None
    workspaces: list[SiteAdminMembershipOut]


class StaffChangeOut(StrictModel):
    id: int
    changed_by_email: str  # empty for the env bootstrap
    target_email: str
    old_is_staff: bool
    new_is_staff: bool
    source: str
    created_at: dt.datetime


class SiteAdminUsersOut(StrictModel):
    users: list[SiteAdminUserOut]
    recent_changes: list[StaffChangeOut]


class StaffPatchIn(StrictModel):
    is_staff: bool
