"""One-shot Drive relocation: existing_content/ → library/audio/ + shared/.

Moves:
  videos/existing_content/audio/*   → videos/library/audio/*
  videos/existing_content/shared/*  → videos/shared/*

Then trashes the empty videos/existing_content/ folder. Per-folder Drive
moves are atomic; the management command runs them sequentially.

Idempotent: files already present at the target with the same byte size
are skipped. Safe to re-run after a partial move.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.videos import drive as drive_mod
from apps.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Move existing_content/{audio,shared} to library/audio + shared."

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

        moved_audio = self._move_audio(layout, client, dry_run)
        moved_shared = self._move_shared(layout, client, dry_run)

        self.stdout.write(self.style.SUCCESS(
            f"Moved {moved_audio} audio file(s) and {moved_shared} shared file(s)."
        ))
        if not dry_run:
            # If existing_content/ is empty, trash it (Drive's trash is 30-day recoverable).
            ec_root = drive_mod.existing_content_folder_id(layout, client)
            if ec_root is not None:
                remaining = [
                    f for f in client.list_folder(ec_root)
                    if not (
                        f.mime_type == "application/vnd.google-apps.folder"
                        and not client.list_folder(f.id)
                    )
                ]
                if not remaining:
                    client.trash_folder(ec_root)
                    self.stdout.write("Trashed empty existing_content/.")

    def _move_audio(self, layout, client, dry_run) -> int:
        legacy_files = drive_mod.list_existing_content(
            layout, client, drive_mod.EXISTING_CONTENT_AUDIO,
        )
        if not legacy_files:
            return 0
        target_id = drive_mod.library_folder_id(
            layout, client, drive_mod.LIBRARY_AUDIO, create=not dry_run,
        )
        if target_id is None and dry_run:
            return len(legacy_files)
        assert target_id is not None
        moved = 0
        for f in legacy_files:
            target_existing = drive_mod._find_child(client, target_id, f.name)
            if target_existing is not None and (target_existing.size_bytes or 0) == (f.size_bytes or 0):
                self.stdout.write(f"  = audio/{f.name} (already present)")
                continue
            self.stdout.write(f"  → audio/{f.name}")
            if not dry_run:
                client.move_file(f.id, target_id)
            moved += 1
        return moved

    def _move_shared(self, layout, client, dry_run) -> int:
        legacy_files = drive_mod.list_existing_content(
            layout, client, drive_mod.EXISTING_CONTENT_SHARED,
        )
        if not legacy_files:
            return 0
        target_id = drive_mod.shared_top_folder_id(
            layout, client, create=not dry_run,
        )
        if target_id is None and dry_run:
            return len(legacy_files)
        assert target_id is not None
        moved = 0
        for f in legacy_files:
            target_existing = drive_mod._find_child(client, target_id, f.name)
            if target_existing is not None and (target_existing.size_bytes or 0) == (f.size_bytes or 0):
                self.stdout.write(f"  = shared/{f.name} (already present)")
                continue
            self.stdout.write(f"  → shared/{f.name}")
            if not dry_run:
                client.move_file(f.id, target_id)
            moved += 1
        return moved
