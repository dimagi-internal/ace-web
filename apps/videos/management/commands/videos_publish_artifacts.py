"""Publish a run's render artifacts (output.mp4, explorer.tar.gz,
feedback.md) from local disk to Drive.

Invoked at the tail of the render shell chain in
``service.trigger_rerender`` so a successful render automatically lands
its artifacts in Drive. Also callable by hand for one-off republishes.

Usage::

    python manage.py videos_publish_artifacts \\
        --workspace dimagi-team --program chc --run run-001
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.videos import service
from apps.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Push a run's output.mp4 + explorer.tar.gz + feedback.md to Drive."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True)
        parser.add_argument("--program", required=True)
        parser.add_argument("--run", required=True)

    def handle(self, *args, workspace, program, run, **kwargs):  # noqa: ARG002
        try:
            ws = Workspace.objects.get(slug=workspace)
        except Workspace.DoesNotExist as e:
            raise CommandError(f"Unknown workspace: {workspace!r}") from e

        result = service.publish_render_artifacts(ws, program, run)
        parts: list[str] = []
        if result.output_mp4_id is not None:
            parts.append(f"output.mp4={result.output_mp4_id}")
        if result.explorer_archive_id is not None:
            parts.append(f"explorer.tar.gz={result.explorer_archive_id}")
        if result.feedback_id is not None:
            parts.append(f"feedback.md={result.feedback_id}")
        if not parts:
            self.stdout.write(self.style.WARNING(
                f"No local artifacts found for {program}/{run} — nothing uploaded."
            ))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Published {program}/{run}: {', '.join(parts)} "
            f"({result.bytes_uploaded} bytes total)"
        ))
