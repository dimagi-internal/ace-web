"""Ingest video snippets from a canopy snippet manifest into Postgres.

A *snippet manifest* (produced by canopy) describes N labeled ranges
into one master video clip. Each entry becomes a ``VideoSnippet`` row,
upserted idempotently by ``(workspace, snippet_key)`` so re-running the
command on the same manifest is a no-op (or picks up edits).

Usage::

    python manage.py videos_ingest_snippets --workspace <slug> <manifest.json>
    python manage.py videos_ingest_snippets --workspace <slug> --manifest <manifest.json>

Best-effort clip linking: if the manifest's top-level ``source_clip``
basename matches an existing ``VideoLibraryEntry.filename`` in the
workspace, the snippet's ``clip`` FK is wired to it. Otherwise the FK
is left null and the manifest's ``source_clip`` / ``source_clip_url``
are stored on the row (``source_clip_ref`` / ``source_clip_url``) so the
link can be made later once the master lands in the library.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.videos.snippets import ingest_manifest
from apps.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Ingest video snippets from a canopy snippet manifest."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True)
        parser.add_argument(
            "manifest",
            nargs="?",
            default=None,
            help="Path to the snippet manifest JSON.",
        )
        parser.add_argument(
            "--manifest",
            dest="manifest_opt",
            default=None,
            help="Path to the snippet manifest JSON (alternative to the positional arg).",
        )

    def handle(self, *args, workspace, manifest, manifest_opt, **kwargs):  # noqa: ARG002
        path = manifest or manifest_opt
        if not path:
            raise CommandError("Provide a manifest path (positional or --manifest).")

        try:
            ws = Workspace.objects.get(slug=workspace)
        except Workspace.DoesNotExist as e:
            raise CommandError(f"Unknown workspace: {workspace!r}") from e

        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            raise CommandError(f"Manifest not found: {path!r}") from e
        except json.JSONDecodeError as e:
            raise CommandError(f"Manifest is not valid JSON: {e}") from e

        self.stdout.write(self.style.NOTICE(f"Ingesting snippets into {ws.slug}…"))
        result = ingest_manifest(ws, raw)
        self.stdout.write(
            f"  created={result['created']} updated={result['updated']} "
            f"linked={result['linked']} unlinked={result['unlinked']}"
        )
        self.stdout.write(self.style.SUCCESS("Done."))
