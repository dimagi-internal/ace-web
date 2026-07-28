"""Per-user presence preference.

The brief's inline router snippet used `Router(tags=["presence"])` with no
`auth=`, which would ship these endpoints unauthenticated and fail
`test_requires_authentication` on its own account — ace-web's convention
(see apps/workspaces/api.py, apps/service_accounts/api.py) is to gate
every top-level router on session_auth explicitly.
"""
from __future__ import annotations

from ninja import Router, Schema

from apps.api.auth import session_auth

from .models import PresencePreference, show_presence_for

router = Router(auth=session_auth, tags=["presence"])


class PresencePreferenceOut(Schema):
    show_presence: bool


class PresencePreferenceIn(Schema):
    show_presence: bool


@router.get("/me/presence-preference", response=PresencePreferenceOut)
def get_presence_preference(request):
    return {"show_presence": show_presence_for(request.user)}


@router.patch("/me/presence-preference", response=PresencePreferenceOut)
def set_presence_preference(request, payload: PresencePreferenceIn):
    PresencePreference.objects.update_or_create(
        user=request.user, defaults={"show_presence": payload.show_presence}
    )
    return {"show_presence": payload.show_presence}
