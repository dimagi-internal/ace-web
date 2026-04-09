"""DRF permission that gates /api/opps/* views on having a valid Drive token.

Named `middleware.py` to match the project's existing convention (see
apps/auth/middleware.py) even though this is a permission class, not a
Django middleware. The distinction matters: Django middleware runs for every
request; a DRF permission runs only for the views that declare it. The
Workbench API is the only place we need this guard, and we want structured
401 responses with a reconnect URL rather than a redirect.
"""
from rest_framework.permissions import BasePermission


class RequireDriveToken(BasePermission):
    """Deny unless request.user is authenticated AND has a cached Drive token.

    On deny, views using this permission should include the output of
    `get_reconnect_payload()` in the error body so the frontend knows where
    to send the user for a fresh OAuth grant.
    """

    message = "Google Drive access is not connected for this user"

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        return bool(getattr(user, "drive_token_cache", ""))

    @staticmethod
    def get_reconnect_payload() -> dict:
        return {"reconnect_url": "/auth/drive/start"}
