"""Give every existing opp the tenancy it was actually built in.

Until per-opp tenancy existed, every ACE run wrote into one set of shared
tenants, configured in ACE's `.env`. This records those values on each opp
so ACE can stop reading them from `.env`:

- HQ project space `connect-ace-prod` (1Password `ACE - CommCareHQ/domain`)
- OCS team `connect-ace` (1Password `ACE - Open Chat Studio/Teams/team_slug`)
- Connect holding (network-manager) org `ace-nm-org` (recorded on the
  spark-facilitator/20260926-1413 run)
- Labs synthetic opps limited to Dimagi domains

`connect_pm_org` is deliberately NOT set: the program-manager org is
per-machine `.env` config (`ACE_CONNECT_PM_ORG`) that no run surface
records, and a guessed slug here would be worse than a missing one — ACE's
preflight reports a missing field as a setup item. Set it with
`PATCH /api/w/{ws}/opps/{slug}/tenancy` / `PATCH /api/workspaces/{slug}`.

Every existing opp gets these values (whatever its workspace — they are where
its assets are). Only `dimagi-team` gets them as its DEFAULT for new opps.
Fill-empty-only: a field an owner already set is never overwritten.

Spec: docs/specs/2026-09-28-clone-and-release-design.md § B.
"""
from django.db import migrations

SHARED_TENANCY = {
    "hq_domain": "connect-ace-prod",
    "connect_holding_org": "ace-nm-org",
    "ocs_team": "connect-ace",
    "labs_allowed_domains": ["@dimagi.com", "@dimagi-ai.com"],
}
DEFAULT_WORKSPACE_SLUG = "dimagi-team"


def _fill_empty(current: dict | None) -> dict:
    out = dict(current or {})
    for key, value in SHARED_TENANCY.items():
        if not out.get(key):
            out[key] = value
    return out


def backfill(apps, schema_editor):
    OppWorkspace = apps.get_model("opps", "OppWorkspace")
    Workspace = apps.get_model("ace_workspaces", "Workspace")

    for opp in OppWorkspace.objects.all().only("id", "tenancy"):
        filled = _fill_empty(opp.tenancy)
        if filled != (opp.tenancy or {}):
            opp.tenancy = filled
            opp.save(update_fields=["tenancy"])

    ws = Workspace.objects.filter(slug=DEFAULT_WORKSPACE_SLUG).first()
    if ws is not None:
        filled = _fill_empty(ws.default_tenancy)
        if filled != (ws.default_tenancy or {}):
            ws.default_tenancy = filled
            ws.save(update_fields=["default_tenancy"])


class Migration(migrations.Migration):

    dependencies = [
        ("opps", "0005_oppworkspace_tenancy"),
        ("ace_workspaces", "0007_tenancy"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
