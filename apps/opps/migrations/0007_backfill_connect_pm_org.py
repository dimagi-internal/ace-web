"""Record the shared Connect program-manager org on every existing opp.

0006 left `connect_pm_org` unset because no run surface recorded it. It is now
verified from Connect itself (2026-09-28): the spark-facilitator/20260926-1413
program "Spark FCAP Community Meeting Facilitation — Malawi Pilot 2026" lives in
org `ace-pm-org`, and its opportunity is held by `ace-nm-org` — the pair ACE's
PM→NM flow uses (lib/connect-orgs.ts; ACE_CONNECT_PM_ORG / ACE_CONNECT_NM_ORG).

Same rules as 0006: every existing opp (the value is where its programs were
made), `dimagi-team`'s default, fill-empty-only so an owner's edit wins.
Some OLDER runs used the legacy PM org `ai-demo-space`; an opp whose runs did
should have its tenancy corrected by an owner — ACE's tenancy guard reports
such writes before it enforces them.
"""
from django.db import migrations

PM_ORG = "ace-pm-org"
DEFAULT_WORKSPACE_SLUG = "dimagi-team"


def backfill(apps, schema_editor):
    OppWorkspace = apps.get_model("opps", "OppWorkspace")
    Workspace = apps.get_model("ace_workspaces", "Workspace")

    for opp in OppWorkspace.objects.all().only("id", "tenancy"):
        tenancy = dict(opp.tenancy or {})
        if not tenancy.get("connect_pm_org"):
            tenancy["connect_pm_org"] = PM_ORG
            opp.tenancy = tenancy
            opp.save(update_fields=["tenancy"])

    ws = Workspace.objects.filter(slug=DEFAULT_WORKSPACE_SLUG).first()
    if ws is not None:
        tenancy = dict(ws.default_tenancy or {})
        if not tenancy.get("connect_pm_org"):
            tenancy["connect_pm_org"] = PM_ORG
            ws.default_tenancy = tenancy
            ws.save(update_fields=["default_tenancy"])


class Migration(migrations.Migration):

    dependencies = [
        ("opps", "0006_backfill_shared_tenancy"),
        ("ace_workspaces", "0009_run_release"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
