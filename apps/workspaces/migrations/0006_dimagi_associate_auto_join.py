"""Add dimagi-associate.com to the dimagi-team auto-join domains.

Dimagi associates (contractors on @dimagi-associate.com) are being added to
`ACE_ALLOWED_EMAIL_DOMAINS` so they can sign in at all. Sign-in alone only
lands them on the empty `/welcome` wizard, though — auto-join is what actually
puts them inside the workspace where the ACE runs live, without requiring a
manual invite.

Unlike 0004 (which OVERWRITES the list to a fixed set), this migration APPENDS
only. Since 0004 shipped, Owners can edit `auto_join_domains` from the
Workspace Settings page and via `PATCH /api/workspaces/{slug}`, so a wholesale
overwrite would silently clobber operator edits. Append + de-dupe is idempotent
and preserves whatever else is on the list.

Blast radius: any @dimagi-associate.com account that completes Connect OAuth
gets a `dimagi-team` WorkspaceMembership at role `editor` — the same role
@dimagi.com / @dimagi-ai.com sign-ins already get (the role is hard-coded in
`apps/workspaces/auto_join.py`, it is not per-domain). `ensure_auto_join_
memberships` never downgrades an existing membership, so an Owner can demote a
specific associate to `viewer` afterwards and it sticks across future logins.
"""
from django.db import migrations


NEW_DOMAIN = "dimagi-associate.com"
WORKSPACE_SLUG = "dimagi-team"


def _normalized(domain: str) -> str:
    return (domain or "").strip().lower().lstrip("@")


def add_associate_domain(apps, schema_editor):
    Workspace = apps.get_model("ace_workspaces", "Workspace")
    ws = Workspace.objects.filter(slug=WORKSPACE_SLUG).first()
    if ws is None:
        # Fresh install / test DB — nothing seeded yet. No-op.
        return
    domains = list(ws.auto_join_domains or [])
    if any(_normalized(d) == NEW_DOMAIN for d in domains):
        return
    domains.append(NEW_DOMAIN)
    ws.auto_join_domains = domains
    ws.save(update_fields=["auto_join_domains", "updated_at"])


def remove_associate_domain(apps, schema_editor):
    Workspace = apps.get_model("ace_workspaces", "Workspace")
    ws = Workspace.objects.filter(slug=WORKSPACE_SLUG).first()
    if ws is None:
        return
    domains = [d for d in (ws.auto_join_domains or []) if _normalized(d) != NEW_DOMAIN]
    ws.auto_join_domains = domains
    ws.save(update_fields=["auto_join_domains", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("ace_workspaces", "0005_promote_ace_owner"),
    ]

    operations = [
        migrations.RunPython(add_associate_domain, reverse_code=remove_associate_domain),
    ]
