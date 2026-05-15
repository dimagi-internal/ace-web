"""Sync the workspace's media library between Drive and Postgres.

Three directions:

- ``--direction=import`` (default): walk Drive, upsert DB rows, remove
  rows whose Drive files vanished.
- ``--direction=export``: write canonical sidecars from DB rows back to
  Drive (skips byte-identical writes).
- ``--direction=both``: import first, then export.

Run after the founding deploy to backfill the new tables, and any time
content lands directly in Drive (out-of-band uploads) without touching
the API.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.videos.library import sync as lib_sync
from apps.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Sync the workspace's media library between Drive and Postgres."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True)
        parser.add_argument(
            "--direction",
            choices=["import", "export", "both"],
            default="import",
            help="import = Drive→DB (default); export = DB→Drive; both = import then export.",
        )

    def handle(self, *args, workspace, direction, **kwargs):  # noqa: ARG002
        try:
            ws = Workspace.objects.get(slug=workspace)
        except Workspace.DoesNotExist as e:
            raise CommandError(f"Unknown workspace: {workspace!r}") from e

        if direction in ("import", "both"):
            self.stdout.write(self.style.NOTICE(f"Importing video library for {ws.slug}…"))
            counts = lib_sync.sync_import_video(ws)
            self.stdout.write(f"  video:  {self._fmt(counts)}")
            self.stdout.write(self.style.NOTICE(f"Importing audio library for {ws.slug}…"))
            counts = lib_sync.sync_import_audio(ws)
            self.stdout.write(f"  audio:  {self._fmt(counts)}")

        if direction in ("export", "both"):
            self.stdout.write(self.style.NOTICE(f"Exporting video library for {ws.slug}…"))
            counts = lib_sync.sync_export_video(ws)
            self.stdout.write(f"  video:  {self._fmt(counts)}")
            self.stdout.write(self.style.NOTICE(f"Exporting audio library for {ws.slug}…"))
            counts = lib_sync.sync_export_audio(ws)
            self.stdout.write(f"  audio:  {self._fmt(counts)}")

        self.stdout.write(self.style.SUCCESS("Done."))

    @staticmethod
    def _fmt(counts: dict[str, int]) -> str:
        return ", ".join(f"{k}={v}" for k, v in counts.items())
