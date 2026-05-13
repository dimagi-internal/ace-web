"""Django admin registrations for the mobile-runner surface.

Read-only by design — these rows are audit records written by the
controller, not editable artifacts. Operators read them to answer
"who hot-patched the launcher and when"; nobody should mutate them
by hand. Mirrors the read-only-audit shape of
``apps.service_accounts.admin.AccessLogAdmin``.
"""
from django.contrib import admin

from .models import MobileLaunchScriptPatch


@admin.register(MobileLaunchScriptPatch)
class MobileLaunchScriptPatchAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "user",
        "sha256_short",
        "bytes_written",
        "restart_requested",
        "instance_id",
        "ami_version",
    )
    list_filter = ("restart_requested", "ami_version", "instance_id")
    search_fields = ("user__email", "sha256", "instance_id", "ami_version")
    readonly_fields = [f.name for f in MobileLaunchScriptPatch._meta.fields]
    date_hierarchy = "created_at"

    @admin.display(description="sha256")
    def sha256_short(self, obj: MobileLaunchScriptPatch) -> str:
        """Display a truncated SHA for the table view — the full
        64-char hex is preserved on the detail page and in the
        ``sha256`` search field."""
        return obj.sha256[:12] + "…" if obj.sha256 else ""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
