"""Create (or repair) canopy's live-probe principal: ``manage.py ensure_canopy_probe``.

Migration ``ace_workspaces.0010`` does this on the deployed ace-web; this is for
anywhere that migration skipped (a fresh install, a local DB you want to probe).
Idempotent, and it never widens: see ``apps/canopy/probe.py``.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.canopy import probe
from apps.workspaces.models import Workspace, WorkspaceMembership


class Command(BaseCommand):
    help = "Create or repair canopy's live-probe principal (no password, one empty workspace)."

    def handle(self, *args, **options):
        user, workspace = probe.ensure_principal(get_user_model(), Workspace, WorkspaceMembership)
        self.stdout.write(self.style.SUCCESS(
            f"probe principal {user.email} (id {user.pk}) is a {probe.PROBE_ROLE} of "
            f"{workspace.slug}; it still needs CANOPY_PROBE_ENABLED and the grant on."))
