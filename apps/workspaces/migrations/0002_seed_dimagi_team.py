"""Seed the dimagi-team workspace and backfill FKs on existing rows.

Idempotent: re-running the migration after the workspace already exists
is a no-op. The founding owner is jjackson@dimagi.com (per the spec —
the only user who has touched the web product to date). The
ace@dimagi-ai.com automation bot is added as Editor if it exists.

After this lands on prod, ACE_DRIVE_ROOT_FOLDER_ID is no longer read at
runtime — it's a migration-only seed value. Future deployments don't
need it set.
"""
from django.conf import settings
from django.db import migrations


FOUNDING_OWNER_EMAIL = "jjackson@dimagi.com"
BOT_EMAIL = "ace@dimagi-ai.com"


def seed_and_backfill(apps, schema_editor):
    Workspace = apps.get_model("ace_workspaces", "Workspace")
    Membership = apps.get_model("ace_workspaces", "WorkspaceMembership")
    User = apps.get_model("ace_auth", "User")
    OppWorkspace = apps.get_model("opps", "OppWorkspace")
    Session = apps.get_model("ace_sessions", "Session")
    ShareToken = apps.get_model("ace_sessions", "ShareToken")
    IngestUpload = apps.get_model("ace_sessions", "IngestUpload")

    folder_id = getattr(settings, "ACE_DRIVE_ROOT_FOLDER_ID", "")
    if not folder_id:
        # No drive root configured — fresh installs / test envs skip seed.
        return

    owner = User.objects.filter(email__iexact=FOUNDING_OWNER_EMAIL).first()
    if owner is None:
        # Fall back to the oldest user. Pure fresh DB? skip everything.
        owner = User.objects.order_by("created_at", "id").first()
    if owner is None:
        return

    ws, _ = Workspace.objects.get_or_create(
        slug="dimagi-team",
        defaults={
            "display_name": "Dimagi Team",
            "drive_root_folder_id": folder_id,
            "created_by": owner,
        },
    )

    # Owner membership for the founder
    Membership.objects.get_or_create(
        workspace=ws, user=owner, defaults={"role": "owner"},
    )

    # Bot as Editor if present
    bot = User.objects.filter(email__iexact=BOT_EMAIL).first()
    if bot is not None:
        Membership.objects.get_or_create(
            workspace=ws, user=bot, defaults={"role": "editor"},
        )

    # Backfill OppWorkspace.workspace
    OppWorkspace.objects.filter(workspace__isnull=True).update(workspace=ws)

    # Backfill Session.workspace for opp-tied sessions (opp_slug match)
    opp_slugs = set(
        OppWorkspace.objects.filter(workspace=ws).values_list("slug", flat=True)
    )
    if opp_slugs:
        Session.objects.filter(
            workspace__isnull=True, opp_slug__in=opp_slugs
        ).update(workspace=ws)

    # Backfill ShareToken.workspace via the related session
    for tok in (
        ShareToken.objects.filter(workspace__isnull=True).select_related("session")
    ):
        if tok.session.workspace_id is not None:
            tok.workspace_id = tok.session.workspace_id
            tok.save(update_fields=["workspace"])

    # Backfill IngestUpload.workspace via the related session
    for up in (
        IngestUpload.objects.filter(workspace__isnull=True).select_related("session")
    ):
        if up.session.workspace_id is not None:
            up.workspace_id = up.session.workspace_id
            up.save(update_fields=["workspace"])


def reverse_seed(apps, schema_editor):
    Workspace = apps.get_model("ace_workspaces", "Workspace")
    Workspace.objects.filter(slug="dimagi-team").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("ace_workspaces", "0001_initial"),
        ("opps", "0003_oppworkspace_workspace"),
        ("ace_sessions", "0004_ingestupload_workspace_session_workspace_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_and_backfill, reverse_code=reverse_seed),
    ]
