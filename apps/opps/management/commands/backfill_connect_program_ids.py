"""Fill opp tenancies' `connect_program_ids` from each opp.yaml (ace-web#914).

    python manage.py backfill_connect_program_ids                  # dry run, every workspace
    python manage.py backfill_connect_program_ids --workspace dimagi-team
    python manage.py backfill_connect_program_ids --apply --as you@dimagi.com

Fill-empty-only and audited; safe to re-run. See apps/opps/tenancy_backfill.py.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Fill each opp's tenancy connect_program_ids from its opp.yaml (dry run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", action="append", default=[],
                            help="Workspace slug (repeatable). Default: every workspace.")
        parser.add_argument("--apply", action="store_true", help="Write the changes.")
        parser.add_argument("--as", dest="as_email",
                            help="Email of the user the changes are attributed to (with --apply).")

    def handle(self, *args, **opts):
        from apps.auth.models import User
        from apps.opps.drive_client import get_drive_client
        from apps.opps.tenancy_backfill import backfill_workspace
        from apps.workspaces.models import Workspace

        user = None
        if opts["apply"]:
            if not opts["as_email"]:
                raise CommandError("--apply needs --as <email>: every tenancy change is audited.")
            user = User.objects.filter(email__iexact=opts["as_email"]).first()
            if user is None:
                raise CommandError(f"no ace-web user {opts['as_email']!r}")

        workspaces = Workspace.objects.order_by("slug")
        if opts["workspace"]:
            workspaces = workspaces.filter(slug__in=opts["workspace"])
            missing = set(opts["workspace"]) - set(workspaces.values_list("slug", flat=True))
            if missing:
                raise CommandError(f"unknown workspace(s): {', '.join(sorted(missing))}")

        totals: dict[str, int] = {}
        for ws in workspaces:
            if not ws.drive_root_folder_id:
                continue
            client = get_drive_client(workspace=ws)
            for r in backfill_workspace(ws, client, apply=opts["apply"], user=user):
                totals[r.action] = totals.get(r.action, 0) + 1
                ids = f" {r.program_ids}" if r.program_ids else ""
                detail = f" ({r.detail})" if r.detail else ""
                self.stdout.write(f"{ws.slug}/{r.slug}: {r.action}{ids}{detail}")
        mode = "applied" if opts["apply"] else "dry run (pass --apply --as <email> to write)"
        summary = ", ".join(f"{k}={v}" for k, v in sorted(totals.items())) or "nothing to do"
        self.stdout.write(f"{mode}: {summary}")
