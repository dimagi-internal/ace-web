from django.contrib import admin

from .models import AccessLog, ImpersonationGrant, ServiceAccount


@admin.register(ServiceAccount)
class ServiceAccountAdmin(admin.ModelAdmin):
    list_display = ("name", "credential_type", "is_active", "created_at")
    list_filter = ("credential_type", "is_active")
    readonly_fields = ("created_at", "updated_at")
    exclude = ("credential_encrypted",)


@admin.register(ImpersonationGrant)
class ImpersonationGrantAdmin(admin.ModelAdmin):
    list_display = (
        "service_account", "subject_pattern", "scopes",
        "revoked_at", "expires_at", "created_at",
    )
    list_filter = ("service_account",)


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ("service_account", "action", "subject", "created_at")
    list_filter = ("service_account", "action")
    readonly_fields = [f.name for f in AccessLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
