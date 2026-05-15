"""Push shared binary assets (audio cache + music bed) into Drive.

One-shot migration: walks the local connect-videos tree and uploads
every file under ``assets/audio/`` and ``assets/shared/`` into the
workspace's Drive at ``videos/existing_content/audio/<name>`` and
``videos/existing_content/shared/<name>`` respectively.

Idempotent: skips files already in Drive with a matching byte size.

The local files stay on disk — they're cache scratch the Node toolchain
reads from. Once Drive is seeded, ``stage_existing_content_locally``
pulls them down at render time on any host that doesn't have them.

Usage::

    python manage.py videos_migrate_existing_content --workspace dimagi-team
    python manage.py videos_migrate_existing_content --workspace dimagi-team --dry-run
    python manage.py videos_migrate_existing_content --workspace dimagi-team --only audio
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.videos import drive, service
from apps.workspaces.models import Workspace


_MIME_BY_EXT: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".mp4": "video/mp4",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
}


def _guess_mime(path: Path) -> str:
    explicit = _MIME_BY_EXT.get(path.suffix.lower())
    if explicit:
        return explicit
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


class Command(BaseCommand):
    help = "Push local shared assets (audio cache + music bed) into Drive."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace", required=True,
            help="Workspace slug to migrate into (e.g. dimagi-team).",
        )
        parser.add_argument(
            "--only", default=None,
            choices=drive.EXISTING_CONTENT_SUBDIRS,
            help="Migrate only one subdir (audio|shared); default = both.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Print what would be uploaded; touch nothing.",
        )

    def handle(self, *args, workspace, only, dry_run, **kwargs):  # noqa: ARG002
        try:
            ws = Workspace.objects.get(slug=workspace)
        except Workspace.DoesNotExist as e:
            raise CommandError(f"Unknown workspace: {workspace!r}") from e

        videos_root = Path(settings.ACE_VIDEOS_ROOT)
        if not videos_root.exists():
            raise CommandError(f"Videos root not found: {videos_root}")

        subdirs = (only,) if only else drive.EXISTING_CONTENT_SUBDIRS

        client = drive.client_for_workspace(ws)
        layout = drive.resolve_layout(ws, client)
        self.stdout.write(self.style.NOTICE(
            f"Workspace: {ws.slug}  ·  Drive videos/ folder id: {layout.videos_folder_id}"
        ))

        total_uploaded = 0
        total_skipped = 0
        for subdir in subdirs:
            local_dir = videos_root / "assets" / subdir
            if not local_dir.exists():
                self.stdout.write(self.style.WARNING(
                    f"  {subdir}/: local dir missing — skipping ({local_dir})"
                ))
                continue

            # Index Drive contents once per subdir so we can skip-on-match
            # without a per-file Drive call.
            remote_by_name: dict[str, service.ExistingContentItem] = {
                item.filename: item
                for item in service.list_existing_content(ws, subdir)
            }

            local_files = sorted(
                p for p in local_dir.iterdir()
                if p.is_file() and not p.name.startswith(".")
            )
            self.stdout.write(self.style.NOTICE(
                f"  {subdir}/: {len(local_files)} local file(s), "
                f"{len(remote_by_name)} already in Drive"
            ))

            for path in local_files:
                size = path.stat().st_size
                remote = remote_by_name.get(path.name)
                if remote is not None and remote.size_bytes == size:
                    self.stdout.write(
                        f"  - {subdir}/{path.name}  · same size in Drive — skip"
                    )
                    total_skipped += 1
                    continue
                action = "would upload" if dry_run else "uploading"
                self.stdout.write(
                    f"  - {subdir}/{path.name}  · {size} bytes · {action}"
                )
                if dry_run:
                    continue
                content = path.read_bytes()
                mime = _guess_mime(path)
                service.upload_existing_content(ws, subdir, path.name, content, mime)
                total_uploaded += 1

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"Dry run — would upload {len(subdirs)} subdir(s)"
            ))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Migration complete — uploaded {total_uploaded}, skipped {total_skipped}."
        ))
