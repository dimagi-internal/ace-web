"""Push local program spec.yamls into Drive.

One-shot migration: walks `video-production/connect-videos/programs/`
locally and uploads each `<slug>/runs/<run-id>/spec.yaml` to the
workspace's Drive folder at
`videos/<slug>/runs/<run-id>/spec.yaml`.

The local files stay on disk — Drive is now the source of truth, the
local copies become render scratch (Django re-stages Drive → local
before each render).

Usage::

    python manage.py videos_migrate_to_drive --workspace dimagi-team
    python manage.py videos_migrate_to_drive --workspace dimagi-team --dry-run
    python manage.py videos_migrate_to_drive --workspace dimagi-team --only chc
"""
from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.videos import drive
from apps.workspaces.models import Workspace


_RUN_RE = re.compile(r"^run-(\d{3,})$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class Command(BaseCommand):
    help = "Push local program spec.yamls into the workspace's Drive folder."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace", required=True,
            help="Workspace slug to migrate into (e.g. dimagi-team)."
        )
        parser.add_argument(
            "--only", default=None,
            help="Migrate only the named program slug (skip the others).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Walk the tree and print what would be uploaded; touch nothing.",
        )

    def handle(self, *args, workspace, only, dry_run, **kwargs):  # noqa: ARG002
        try:
            ws = Workspace.objects.get(slug=workspace)
        except Workspace.DoesNotExist as e:
            raise CommandError(f"Unknown workspace: {workspace!r}") from e

        videos_root = Path(settings.ACE_VIDEOS_ROOT)
        programs_dir = videos_root / "programs"
        if not programs_dir.exists():
            raise CommandError(f"Programs dir not found: {programs_dir}")

        client = drive.client_for_workspace(ws)
        layout = drive.resolve_layout(ws, client)
        self.stdout.write(self.style.NOTICE(
            f"Workspace: {ws.slug}  ·  Drive videos/ folder id: {layout.videos_folder_id}"
        ))

        plan: list[tuple[str, str, Path]] = []  # (slug, run_id, spec_path)
        for entry in sorted(programs_dir.iterdir()):
            if not entry.is_dir() or not _SLUG_RE.match(entry.name):
                continue
            if only and entry.name != only:
                continue
            runs_dir = entry / "runs"
            if not runs_dir.exists():
                self.stdout.write(self.style.WARNING(
                    f"  {entry.name}: no runs/ dir — skipping"
                ))
                continue
            for run_dir in sorted(runs_dir.iterdir()):
                if not run_dir.is_dir() or not _RUN_RE.match(run_dir.name):
                    continue
                spec = run_dir / "spec.yaml"
                if not spec.exists():
                    self.stdout.write(self.style.WARNING(
                        f"  {entry.name}/{run_dir.name}: spec.yaml missing — skipping"
                    ))
                    continue
                plan.append((entry.name, run_dir.name, spec))

        if not plan:
            self.stdout.write(self.style.WARNING("No specs found to migrate."))
            return

        self.stdout.write(self.style.NOTICE(f"Will migrate {len(plan)} spec(s):"))
        for slug, run_id, spec in plan:
            self.stdout.write(f"  - {slug}/{run_id}  ({spec.stat().st_size} bytes)")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run — nothing uploaded."))
            return

        uploaded = 0
        for slug, run_id, spec in plan:
            content = spec.read_text(encoding="utf-8")
            file_id = drive.write_spec(layout, client, slug, run_id, content)
            self.stdout.write(self.style.SUCCESS(
                f"  ✓ uploaded {slug}/{run_id}/spec.yaml → {file_id}"
            ))
            uploaded += 1

        self.stdout.write(self.style.SUCCESS(
            f"Migration complete — {uploaded} spec(s) now in Drive."
        ))
