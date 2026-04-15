"""ORM models for the opps Workbench.

Intentionally lightweight. Drive remains the source of truth for opp
*content* (idea.md, pdd.md, artifacts, state.yaml, run history). This
Postgres row is just the workspace wrapper — pins the display name, the
currently-attached working chat session, and created-by metadata.

See: docs/specs/2026-04-15-web-native-opp-lifecycle-design.md § 4.2.
"""
from django.conf import settings
from django.db import models


class OppWorkspace(models.Model):
    slug = models.CharField(max_length=64, primary_key=True)
    display_name = models.CharField(max_length=200)
    working_session = models.ForeignKey(
        "ace_sessions.Session",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="opp_working_for",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_opps",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "opp_workspaces"
        indexes = [
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"{self.slug}: {self.display_name}"
