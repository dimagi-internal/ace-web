"""ORM models for ACE Workspaces — the unit of multi-tenancy.

A Workspace owns a Google Drive folder (the `ace-drive` SA must be shared
on it as Editor) and a list of members with roles. All ACE opps live
under exactly one workspace.

See: docs/specs/2026-04-27-multi-tenant-workspaces-design.md
"""
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


def generate_invite_token() -> str:
    """48-char URL-safe random token."""
    return secrets.token_urlsafe(36)[:48]


class Workspace(models.Model):
    slug = models.CharField(primary_key=True, max_length=64)
    display_name = models.CharField(max_length=200)
    drive_root_folder_id = models.CharField(max_length=100, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workspaces_created",
    )
    settings = models.JSONField(default=dict, blank=True)
    # Email domains (lowercased, no leading "@") whose users are auto-added as
    # Editor on first login. Stored as JSON list for portability across the
    # Postgres prod DB and the in-memory SQLite test DB.
    auto_join_domains = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workspaces"
        indexes = [models.Index(fields=["-created_at"])]

    def __str__(self):
        return f"{self.display_name} ({self.slug})"


class WorkspaceMembership(models.Model):
    ROLE_CHOICES = [
        ("owner", "Owner"),
        ("editor", "Editor"),
        ("viewer", "Viewer"),
    ]

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="+",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "workspace_memberships"
        unique_together = [("workspace", "user")]
        indexes = [models.Index(fields=["user", "workspace"])]

    def __str__(self):
        return f"{self.user.email} = {self.role} on {self.workspace.slug}"


class WorkspaceInvite(models.Model):
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="invites"
    )
    email = models.CharField(max_length=200)
    role = models.CharField(
        max_length=16, choices=WorkspaceMembership.ROLE_CHOICES, default="editor"
    )
    token = models.CharField(max_length=64, unique=True, default=generate_invite_token)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="invites_sent",
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "workspace_invites"
        indexes = [
            models.Index(fields=["email", "-created_at"]),
            models.Index(fields=["workspace", "-created_at"]),
        ]

    def __str__(self):
        return f"Invite {self.email} to {self.workspace.slug} as {self.role}"

    def is_pending(self) -> bool:
        if self.accepted_at is not None or self.revoked_at is not None:
            return False
        return self.expires_at > timezone.now()
