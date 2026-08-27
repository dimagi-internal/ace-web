"""Reconcile every canopy-dispatched run's state back onto its ace-web rows.

Run from the post-deploy hook alongside `resume-interrupted`, or from cron.
ace-web has no worker; this and the compute-on-read path in
`apps/sessions/api.py::session_execution` are the only two reconcilers.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Reconcile canopy-dispatched runs (turn status -> ace-web message status)."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", default="", help="Limit to one workspace slug.")
        parser.add_argument("--limit", type=int, default=200)

    def handle(self, *args, **options):
        from apps.canopy.run_state import reconcile_session
        from apps.sessions.models import Session

        qs = Session.objects.exclude(canopy_session_id="").order_by("-updated_at")
        if options["workspace"]:
            qs = qs.filter(workspace__slug=options["workspace"])
        counts: dict[str, int] = {}
        for session in qs[: options["limit"]]:
            try:
                state = reconcile_session(session)["state"]
            except Exception as exc:  # noqa: BLE001 — one bad run must not stop the sweep
                self.stderr.write(f"{session.slug}: {exc}")
                continue
            counts[state] = counts.get(state, 0) + 1
        for state, n in sorted(counts.items()):
            self.stdout.write(f"{state}: {n}")
