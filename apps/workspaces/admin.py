from django.contrib import admin

from apps.workspaces.models import Workspace, WorkspaceInvite, WorkspaceMembership


class MembershipInline(admin.TabularInline):
    model = WorkspaceMembership
    extra = 0
    autocomplete_fields = ["user"]
    fields = ["user", "role", "invited_by", "joined_at"]
    readonly_fields = ["joined_at"]


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = [
        "slug", "display_name", "drive_root_folder_id", "created_by", "created_at",
    ]
    search_fields = ["slug", "display_name", "drive_root_folder_id"]
    autocomplete_fields = ["created_by"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = [MembershipInline]


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(admin.ModelAdmin):
    list_display = ["workspace", "user", "role", "joined_at"]
    list_filter = ["role"]
    search_fields = ["workspace__slug", "user__email"]
    autocomplete_fields = ["workspace", "user", "invited_by"]


@admin.register(WorkspaceInvite)
class WorkspaceInviteAdmin(admin.ModelAdmin):
    list_display = [
        "email", "workspace", "role", "created_at", "accepted_at", "revoked_at",
    ]
    list_filter = ["role"]
    search_fields = ["email", "workspace__slug"]
    autocomplete_fields = ["workspace", "invited_by"]
    readonly_fields = ["token", "created_at"]
