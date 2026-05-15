"""Reconstruct audio sidecars for orphan <hash>.mp3 files in library/audio/.

Walks every program's run specs in the target workspace, recomputes the
ElevenLabs cacheKey for every (narration.by_beat[*], voice.voice_id,
voice.model) triple, and writes the matching sidecar if the orphan mp3
exists. Orphans not reconstructible from any spec stay sidecar-less.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import PurePosixPath

from django.core.management.base import BaseCommand, CommandError
from ruamel.yaml import YAML

from apps.videos import drive as drive_mod
from apps.workspaces.models import Workspace


def _cache_key(text: str, voice_id: str, model: str) -> str:
    return hashlib.sha256(
        f"{voice_id}::{model}::{text}".encode()
    ).hexdigest()[:16]


class Command(BaseCommand):
    help = "Reconstruct audio sidecars for orphan library/audio/<hash>.mp3 files."

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

        # Build a hash → (voice_id, model, text) map from specs.
        recovered: dict[str, dict] = {}
        for program_slug in drive_mod.list_program_slugs(layout, client):
            for run_id in drive_mod.list_run_ids(layout, client, program_slug):
                spec_bytes = drive_mod.read_spec(layout, client, program_slug, run_id)
                if spec_bytes is None:
                    continue
                try:
                    text = (
                        spec_bytes.decode()
                        if isinstance(spec_bytes, bytes)
                        else spec_bytes
                    )
                    parsed = YAML(typ="safe").load(text)
                except Exception:
                    continue
                if not isinstance(parsed, dict):
                    continue
                voice = parsed.get("voice") or {}
                voice_id = voice.get("voice_id")
                model = voice.get("model")
                if not voice_id or not model:
                    continue
                narration = (parsed.get("narration") or {}).get("by_beat") or {}
                for _beat_id, beat_text in narration.items():
                    if not isinstance(beat_text, str) or not beat_text.strip():
                        continue
                    key = _cache_key(beat_text, voice_id, model)
                    recovered.setdefault(key, {
                        "voice_id": voice_id,
                        "model": model,
                        "text": beat_text,
                        "duration_sec": None,
                        "generated_at": datetime.now(UTC).isoformat(),
                    })

        # Walk library/audio/ for orphans and patch.
        audio_files = drive_mod.list_audio_library_files(layout, client)
        existing_sidecars = {
            PurePosixPath(f.name).stem
            for f in audio_files
            if f.name.endswith(".json")
        }
        existing_mp3s = [
            f for f in audio_files
            if f.name.endswith(".mp3")
        ]

        wrote = 0
        unmatched = 0
        for mp3 in existing_mp3s:
            stem = PurePosixPath(mp3.name).stem
            if stem in existing_sidecars:
                continue
            data = recovered.get(stem)
            if data is None:
                unmatched += 1
                continue
            self.stdout.write(
                f"  + {stem}.json  (voice {data['voice_id']}, model {data['model']})"
            )
            if not dry_run:
                drive_mod.upload_library_file(
                    layout, client, drive_mod.LIBRARY_AUDIO,
                    f"{stem}.json",
                    json.dumps(data, indent=2).encode(),
                    "application/json",
                )
            wrote += 1

        self.stdout.write(self.style.SUCCESS(
            f"Backfilled {wrote} sidecar(s); {unmatched} orphan(s) had no matching spec."
        ))
