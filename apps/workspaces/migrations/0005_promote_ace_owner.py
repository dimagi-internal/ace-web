"""Promote the ACE automation bot (ace@dimagi-ai.com) to OWNER of dimagi-team.

ACE is a first-class ace-web principal, not something that acts on behalf of a
human. To grant review access repeatably (invite thread participants to the
workspace via the owner-gated POST /api/workspaces/<slug>/members/invite), the
bot must be an OWNER, not the Editor it was seeded as in 0002_seed_dimagi_team.

Idempotent: promotes an existing membership to owner, creates one as owner if
missing, and no-ops cleanly on a fresh/test DB where the workspace or the bot
user does not exist. Reverse restores Editor (the 0002 seed role).
"""
from django.db import migrations

BOT_EMAIL = "ace@dimagi-ai.com"
WORKSPACE_SLUG = "dimagi-team"


def promote_bot_to_owner(apps, schema_editor):
    Workspace = apps.get_model("ace_workspaces", "Workspace")
    Membership = apps.get_model("ace_workspaces", "WorkspaceMembership")
    User = apps.get_model("ace_auth", "User")

    ws = Workspace.objects.filter(slug=WORKSPACE_SLUG).first()
    bot = User.objects.filter(email__iexact=BOT_EMAIL).first()
    if ws is None or bot is None:
        # Fresh install / test DB — nothing seeded yet. No-op.
        return

    membership, created = Membership.objects.get_or_create(
        workspace=ws, user=bot, defaults={"role": "owner"},
    )
    if not created and membership.role != "owner":
        membership.role = "owner"
        membership.save(update_fields=["role"])


def demote_bot_to_editor(apps, schema_editor):
    Workspace = apps.get_model("ace_workspaces", "Workspace")
    Membership = apps.get_model("ace_workspaces", "WorkspaceMembership")
    User = apps.get_model("ace_auth", "User")

    ws = Workspace.objects.filter(slug=WORKSPACE_SLUG).first()
    bot = User.objects.filter(email__iexact=BOT_EMAIL).first()
    if ws is None or bot is None:
        return
    Membership.objects.filter(workspace=ws, user=bot).update(role="editor")


class Migration(migrations.Migration):

    dependencies = [
        ("ace_workspaces", "0004_seed_dimagi_team_auto_join"),
    ]

    operations = [
        migrations.RunPython(promote_bot_to_owner, reverse_code=demote_bot_to_editor),
    ]
