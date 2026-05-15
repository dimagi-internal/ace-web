"""Write stub sidecars for video library files that don't have one.

The stub is intentionally minimal — name from the filename, empty tags
list. Curators are expected to fill it in via Drive UI afterwards. The
goal is to surface orphans in the library UI without losing them.
"""
from __future__ import annotations

import json
from pathlib import PurePosixPath

from django.core.management.base import BaseCommand, CommandError

from apps.videos import drive as drive_mod
from apps.workspaces.models import Workspace

_VIDEO_EXTS = {".mp4", ".mov", ".webm"}


class Command(BaseCommand):
    help = "Stub sidecars for orphan video files in library/video/<*>/."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, workspace, dry_run, **kwargs):  # noqa: ARG002
        try:
            ws = Workspace.objects.get(slug=workspace)
        except Workspace.DoesNotExist as e:
            raise CommandError(f"Unknown workspace: {workspace!r}") from e

        client = drive_mod.client_for_workspace(ws)
        layout = drive_mod.resolve_layout(ws, client)

        subs = drive_mod.list_library_subfolders(layout, client, drive_mod.LIBRARY_VIDEO)
        total = 0
        for sub in subs:
            files = drive_mod.list_library_files(
                layout, client, drive_mod.LIBRARY_VIDEO, sub.name,
            )
            by_stem: dict[str, dict[str, str]] = {}
            for f in files:
                ext = PurePosixPath(f.name).suffix.lower()
                stem = PurePosixPath(f.name).stem
                if ext in _VIDEO_EXTS:
                    by_stem.setdefault(stem, {})["video"] = f.name
                elif ext == ".json":
                    by_stem.setdefault(stem, {})["sidecar"] = f.name
            for stem, entry in by_stem.items():
                if "video" in entry and "sidecar" not in entry:
                    self.stdout.write(f"  + {sub.name}/{stem}.json")
                    if not dry_run:
                        drive_mod.upload_library_file(
                            layout, client, drive_mod.LIBRARY_VIDEO,
                            f"{stem}.json",
                            json.dumps({"name": stem, "tags": []}, indent=2).encode(),
                            "application/json",
                            subfolder=sub.name,
                        )
                    total += 1
        self.stdout.write(self.style.SUCCESS(f"Stubbed {total} sidecar(s)."))
