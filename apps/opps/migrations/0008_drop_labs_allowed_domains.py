"""Drop `labs_allowed_domains` from every stored tenancy.

The per-opp Labs domain list was removed (Jonathan, 2026-10-08: "just delete
that setting, I don't think it clearly means anything"). `Tenancy` is a strict
model, so a stored key it no longer knows would fail validation on the next
read or PATCH — strip it from every opp's tenancy and every workspace default.
Irreversible by design: the values are not restored.
"""
from django.db import migrations

KEY = "labs_allowed_domains"


def strip(apps, schema_editor):
    OppWorkspace = apps.get_model("opps", "OppWorkspace")
    Workspace = apps.get_model("ace_workspaces", "Workspace")

    for opp in OppWorkspace.objects.all().only("id", "tenancy"):
        if KEY in (opp.tenancy or {}):
            opp.tenancy = {k: v for k, v in opp.tenancy.items() if k != KEY}
            opp.save(update_fields=["tenancy"])

    for ws in Workspace.objects.all():
        if KEY in (ws.default_tenancy or {}):
            ws.default_tenancy = {k: v for k, v in ws.default_tenancy.items() if k != KEY}
            ws.save(update_fields=["default_tenancy"])


class Migration(migrations.Migration):

    dependencies = [
        ("opps", "0007_backfill_connect_pm_org"),
        ("ace_workspaces", "0012_viewers_become_editors"),
    ]

    operations = [migrations.RunPython(strip, migrations.RunPython.noop)]
