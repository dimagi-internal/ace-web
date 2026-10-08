"""Remove the retired `labs_allowed_domains` key from every stored tenancy.

Labs allowed domains was a tenancy field that widened who Labs opens
dashboards to. Jonathan (2026-10-08): "just delete that setting, I don't
think it clearly means anything." Labs keeps its own default (Dimagi
accounts only). Migration 0006 seeded the key on every opp and on
`dimagi-team`'s default, and `Tenancy` now forbids unknown keys, so a
stored one would fail validation on read — strip it from
`Workspace.default_tenancy` and every `OppWorkspace.tenancy`.

0006 stays as it was (it ran with the field); this one removes what it wrote.
Reverse is a no-op: the old values are not recoverable and not wanted.
"""
from django.db import migrations

KEY = "labs_allowed_domains"


def drop_key(apps, schema_editor):
    OppWorkspace = apps.get_model("opps", "OppWorkspace")
    Workspace = apps.get_model("ace_workspaces", "Workspace")

    for opp in OppWorkspace.objects.all().only("id", "tenancy"):
        if opp.tenancy and KEY in opp.tenancy:
            opp.tenancy = {k: v for k, v in opp.tenancy.items() if k != KEY}
            opp.save(update_fields=["tenancy"])

    for ws in Workspace.objects.all():
        if ws.default_tenancy and KEY in ws.default_tenancy:
            ws.default_tenancy = {k: v for k, v in ws.default_tenancy.items() if k != KEY}
            ws.save(update_fields=["default_tenancy"])


class Migration(migrations.Migration):

    dependencies = [
        ("opps", "0007_backfill_connect_pm_org"),
    ]

    operations = [migrations.RunPython(drop_key, migrations.RunPython.noop)]
