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
    # Tenancy a new opp in this workspace starts with (copied at creation;
    # the opp's own `OppWorkspace.tenancy` is the truth after that). Shape:
    # apps.opps.tenancy.Tenancy.
    default_tenancy = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workspaces"
        indexes = [models.Index(fields=["-created_at"])]

    def __str__(self):
        return f"{self.display_name} ({self.slug})"


class WorkspaceMembership(models.Model):
    # The four roles, the same ladder canopy-web runs (owner decision,
    # 2026-10-07: "lets use the same acl as canopy, owner, admin, editor,
    # viewer"). ADMIN sits between editor and owner: it runs the workspace —
    # invites and manages members strictly below itself, reads the audit log,
    # gets the team view of a run summary — but holds none of the owner's
    # keys (workspace settings, Drive root, tenancy, clones). A VIEWER reads
    # and writes nothing.
    #
    # What each role may DO lives in `apps/workspaces/permissions.py`
    # (`MINIMUM_ROLE`); no code outside this app names a role
    # (`tests/test_roles_named_only_in_workspaces.py`).
    OWNER, ADMIN, EDITOR, VIEWER = "owner", "admin", "editor", "viewer"
    ROLE_CHOICES = [
        (OWNER, "Owner"),
        (ADMIN, "Admin"),
        (EDITOR, "Editor"),
        (VIEWER, "Viewer"),
    ]
    #: The single place role ORDERING lives. Higher outranks lower.
    ROLE_RANK = {VIEWER: 0, EDITOR: 1, ADMIN: 2, OWNER: 3}

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
        max_length=16, choices=WorkspaceMembership.ROLE_CHOICES,
        default=WorkspaceMembership.EDITOR,
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


class TenancyChange(models.Model):
    """Audit row for a tenancy change (apps.opps.tenancy). Tenancy decides
    where ACE may write, so every change records who made it and the values
    before and after. `opp_slug` is blank for the workspace default."""

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="tenancy_changes"
    )
    opp_slug = models.CharField(max_length=64, blank=True, default="")
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="+",
    )
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "workspace_tenancy_changes"
        indexes = [models.Index(fields=["workspace", "-created_at"])]


class RunClone(models.Model):
    """One run copied into another workspace (clone-to-new-workspace).

    The record lives here rather than in the source run's Drive files, so a
    clone leaves the source run untouched. `release` later reads it to decide
    whether the source's public summary link should forward to the clone.
    Spec: docs/specs/2026-09-28-clone-and-release-design.md § C.
    """

    STATUS_CHOICES = [("copying", "Copying"), ("done", "Done"), ("error", "Error")]

    source_workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="clones_out"
    )
    target_workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="clones_in"
    )
    opp_slug = models.CharField(max_length=64)
    run_id = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="copying")
    files_copied = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workspace_run_clones"
        indexes = [
            models.Index(fields=["source_workspace", "opp_slug", "run_id"]),
            models.Index(fields=["target_workspace", "opp_slug", "run_id"]),
        ]


class RunRelease(models.Model):
    """A run released to outside reviewers (`/ace:release`).

    One row per released run (workspace + opp + run), upserted as the release
    proceeds: reviewers are added as they are invited, and `forwards_from`
    names the clone whose SOURCE run's public summary link now 308-redirects
    here — so a link already sent to reviewers lands on their copy.
    Spec: docs/specs/2026-09-28-clone-and-release-design.md § E2.
    """

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="releases")
    opp_slug = models.CharField(max_length=64)
    run_id = models.CharField(max_length=64)
    reviewers = models.JSONField(default=list, blank=True)
    forwards_from = models.ForeignKey(
        RunClone, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workspace_run_releases"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "opp_slug", "run_id"], name="uniq_run_release"
            )
        ]
