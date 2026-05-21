"""Seed the dimagi-team workspace with auto-join domains.

Anyone signing in with a @dimagi.com or @dimagi-ai.com email will be
auto-added as an Editor on first (and any subsequent) login. Idempotent
— re-running overwrites the list to exactly [dimagi.com, dimagi-ai.com],
which is the intended behavior at this point in time.
"""
from django.db import migrations


AUTO_JOIN_DOMAINS = ["dimagi.com", "dimagi-ai.com"]


def seed_auto_join(apps, schema_editor):
    Workspace = apps.get_model("ace_workspaces", "Workspace")
    ws = Workspace.objects.filter(slug="dimagi-team").first()
    if ws is None:
        return
    ws.auto_join_domains = list(AUTO_JOIN_DOMAINS)
    ws.save(update_fields=["auto_join_domains", "updated_at"])


def clear_auto_join(apps, schema_editor):
    Workspace = apps.get_model("ace_workspaces", "Workspace")
    ws = Workspace.objects.filter(slug="dimagi-team").first()
    if ws is None:
        return
    ws.auto_join_domains = []
    ws.save(update_fields=["auto_join_domains", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("ace_workspaces", "0003_auto_join_domains"),
    ]

    operations = [
        migrations.RunPython(seed_auto_join, reverse_code=clear_auto_join),
    ]
