"""Seed Drive template files from the repo's video-production template tree.

Uploads each template directory under
``video-production/connect-videos/templates/<id>/`` into the workspace's
Drive ``videos/_templates/<id>/`` folder. Idempotent, and per FILE rather
than per kit: a kit already in Drive but missing one of its three files
gets that file backfilled, and existing files are never overwritten. Run
it to repair a partially-seeded kit (see ace-web#679).

Usage::

    # Seed a single workspace:
    python manage.py videos_seed_templates --workspace dimagi-team

    # Seed ALL workspaces:
    python manage.py videos_seed_templates
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.videos import templates
from apps.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Seed/repair Drive template files from the repo template tree (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace",
            default=None,
            help="Workspace slug to seed (e.g. dimagi-team). Omit to seed ALL workspaces.",
        )

    def handle(self, *args, workspace, **kwargs):  # noqa: ARG002
        if workspace is not None:
            try:
                ws = Workspace.objects.get(slug=workspace)
            except Workspace.DoesNotExist as e:
                raise CommandError(f"Unknown workspace: {workspace!r}") from e
            workspaces = [ws]
        else:
            workspaces = list(Workspace.objects.all())
            if not workspaces:
                self.stdout.write(self.style.WARNING("No workspaces found."))
                return

        for ws in workspaces:
            count = templates.seed_templates(ws)
            if count:
                self.stdout.write(self.style.SUCCESS(
                    f"  {ws.slug}: seeded or repaired {count} template(s)."
                ))
            else:
                self.stdout.write(
                    f"  {ws.slug}: nothing to do (every kit complete in Drive)."
                )

        self.stdout.write(self.style.SUCCESS("Done."))
