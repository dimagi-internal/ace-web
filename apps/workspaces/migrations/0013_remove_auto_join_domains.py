"""Drop `Workspace.auto_join_domains`: join-by-email-domain is retired.

Workspace access now comes only from invites (emailed, resendable) and
explicit memberships. Existing memberships — including everyone auto-joined
before this — are untouched; only the domain lists go.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ace_workspaces", "0012_viewers_become_editors"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="workspace",
            name="auto_join_domains",
        ),
    ]
