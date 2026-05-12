"""Persistent state for the mobile-runner surface.

Almost everything mobile-related is stateless from ace-web's perspective:
the EC2 instance, the AVD, the per-recipe artifacts, all live in AWS and
are read through-cache by the controller. The one exception is the audit
log of every successful in-VM hot-patch of ``ace-emulator-launch`` —
that's privileged enough to want a Django-side row so we know who
changed what and when, independent of the EC2 instance (which can be
torn down + rebuilt).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class MobileLaunchScriptPatch(models.Model):
    """Audit row for one successful ``POST /api/mobile/admin/patch-launch-script``.

    Written only after the controller confirms the in-VM SHA256 matches
    what we sent (so failed / corrupted patches don't pollute the log).
    The row outlives the EC2 instance — useful for "what did this
    patch do to the AMI behavior" investigations after a rebake.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="mobile_launch_patches",
        help_text="The authenticated user (PAT or session) who issued the patch.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    sha256 = models.CharField(
        max_length=64,
        help_text="SHA256 of the script body the EC2 instance reported on-disk.",
    )
    bytes_written = models.PositiveIntegerField()
    restart_requested = models.BooleanField(
        help_text="Whether the request asked the controller to restart the runner unit.",
    )
    instance_id = models.CharField(
        max_length=32,
        help_text="EC2 instance the patch targeted at the time of the call.",
    )
    ami_version = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="ACE_MOBILE_AMI_VERSION at the time of the call (best-effort).",
    )

    class Meta:
        db_table = "mobile_launch_script_patch"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.created_at:%Y-%m-%d %H:%M} sha={self.sha256[:8]}"
