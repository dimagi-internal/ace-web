from django.contrib import admin

from .models import SlackInstallation, SlackRunThread, SlackUserLink


@admin.register(SlackInstallation)
class SlackInstallationAdmin(admin.ModelAdmin):
    list_display = ("slack_team_name", "slack_team_id", "ace_workspace", "installed_at")
    readonly_fields = ("installed_at", "bot_token_encrypted")


@admin.register(SlackUserLink)
class SlackUserLinkAdmin(admin.ModelAdmin):
    list_display = ("slack_user_id", "ace_user", "installation", "linked_at", "unlinked_at")
    list_filter = ("installation",)


@admin.register(SlackRunThread)
class SlackRunThreadAdmin(admin.ModelAdmin):
    list_display = ("opp_slug", "run_id", "channel_id", "ace_user", "triggered_at", "broken_at")
    readonly_fields = ("triggered_at", "phase_messages", "parent_state_hash")
