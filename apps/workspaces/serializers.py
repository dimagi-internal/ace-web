"""DRF serializers for the workspaces API."""
from rest_framework import serializers

from apps.workspaces.models import Workspace, WorkspaceMembership


class WorkspaceSummarySerializer(serializers.ModelSerializer):
    """List view: minimal fields for the switcher dropdown."""

    role = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = ["slug", "display_name", "role", "created_at"]

    def get_role(self, obj):
        if hasattr(obj, "_my_role"):
            return obj._my_role
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            from apps.workspaces.permissions import role_for
            return role_for(request.user, obj)
        return None


class WorkspaceMemberSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_display_name = serializers.CharField(
        source="user.display_name", read_only=True
    )

    class Meta:
        model = WorkspaceMembership
        fields = ["user_id", "user_email", "user_display_name", "role", "joined_at"]


class WorkspaceDetailSerializer(serializers.ModelSerializer):
    members = WorkspaceMemberSerializer(source="memberships", many=True, read_only=True)
    my_role = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = [
            "slug", "display_name", "drive_root_folder_id",
            "created_at", "updated_at", "settings",
            "members", "my_role",
        ]

    def get_my_role(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            from apps.workspaces.permissions import role_for
            return role_for(request.user, obj)
        return None
