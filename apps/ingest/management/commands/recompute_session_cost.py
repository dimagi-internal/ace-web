"""Deliberately re-derive a session's cost, overriding the refuse-smaller ratchet.

`recompute_cost_from_source` will not lower a stored cost, because a drop means
we read fewer bytes than last time. That rule is one-way, so a figure that was
ever too HIGH — a double-counted compose, a transcript shape we guessed wrong —
would otherwise be permanent. This is the escape hatch, and it is deliberately a
command rather than a code path: it prints the before and after for every row it
touches, so a reset is never silent.
"""

from django.core.management.base import BaseCommand, CommandError


def _totals(breakdown) -> dict:
    return (breakdown or {}).get("totals") or {}


class Command(BaseCommand):
    help = "Re-derive Session.cost_breakdown from the transcript source, before/after printed."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="", help="One session slug.")
        parser.add_argument("--all", action="store_true", help="Every canopy-dispatched session.")
        parser.add_argument(
            "--force", action="store_true",
            help="Also allow the new figure to be LOWER than the stored one.",
        )
        parser.add_argument(
            "--no-refresh", action="store_true",
            help="Use the cached transcript instead of refetching from canopy.",
        )
        parser.add_argument("--limit", type=int, default=200)

    def handle(self, *args, **options):
        from apps.ingest.live_ingest import recompute_cost_from_source
        from apps.sessions.models import Session

        if not options["slug"] and not options["all"]:
            raise CommandError("pass --slug <slug> or --all")

        if options["slug"]:
            qs = Session.objects.filter(slug=options["slug"])
            if not qs.exists():
                raise CommandError(f"no session with slug {options['slug']}")
        else:
            qs = Session.objects.exclude(canopy_session_id="").order_by("-updated_at")

        changed = 0
        for session in qs[: options["limit"]]:
            before = _totals(session.cost_breakdown)
            try:
                after = _totals(
                    recompute_cost_from_source(
                        session,
                        force_refresh=not options["no_refresh"],
                        force=options["force"],
                    )
                )
            except Exception as exc:  # noqa: BLE001 — one bad row must not stop the sweep
                self.stderr.write(f"{session.slug}: {exc}")
                continue
            if before != after:
                changed += 1
                self.stdout.write(f"{session.slug}: {before} -> {after}")
            else:
                self.stdout.write(f"{session.slug}: unchanged {before}")
        self.stdout.write(f"changed: {changed}")
