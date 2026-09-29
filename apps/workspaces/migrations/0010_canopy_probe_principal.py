"""Create canopy's live-probe principal: a dedicated, low-privilege account.

canopy's live probe (canopy SDK 0.4.0, ``apps/canopy/probe.py``) asks
ace-web's probe endpoint for a real ID-JAG and makes one real MCP read with it,
on a schedule, so a broken host grant is found before a visitor finds it. The
ID-JAG is only ever for THIS principal:

* ``canopy-probe@probe.invalid`` — the reserved ``.invalid`` TLD, so no
  Connect OAuth identity can carry it (no sign-in path); unusable password;
  not staff, not superuser. Never a real person's account.
* a VIEWER of one workspace, ``canopy-probe``, which has no Drive root, so the
  probe's ``list_opps`` there succeeds (membership checked as for anyone) and
  returns nothing. It is a member of no real workspace.

Until this row exists the probe endpoint answers 404 and the metadata does not
name it. Idempotent; the reverse removes all three rows.

Like 0004-0006, it acts only on an EXISTING deployment (one with the seeded
`dimagi-team` workspace): a fresh install or a test database skips, so the
probe's rows never appear in a local dev DB (where test-login would otherwise
find a workspace and skip bootstrapping `dimagi-team`) or in every test's
counts. Anywhere else: `manage.py ensure_canopy_probe`.
"""
from django.db import migrations


def create(apps, schema_editor):
    from apps.canopy import probe

    Workspace = apps.get_model("ace_workspaces", "Workspace")
    if not Workspace.objects.filter(slug="dimagi-team").exists():
        return  # fresh install / test DB — see the docstring
    probe.ensure_principal(
        apps.get_model("ace_auth", "User"),
        apps.get_model("ace_workspaces", "Workspace"),
        apps.get_model("ace_workspaces", "WorkspaceMembership"),
    )


def remove(apps, schema_editor):
    from apps.canopy import probe

    probe.remove_principal(
        apps.get_model("ace_auth", "User"),
        apps.get_model("ace_workspaces", "Workspace"),
        apps.get_model("ace_workspaces", "WorkspaceMembership"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("ace_workspaces", "0009_run_release"),
        ("ace_auth", "0005_personal_token_expires_at"),
    ]

    operations = [
        migrations.RunPython(create, reverse_code=remove),
    ]
