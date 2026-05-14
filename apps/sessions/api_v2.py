"""Django Ninja v2 router for the sessions surface."""
from __future__ import annotations

from ninja import Router

from apps.api_v2.auth import session_auth

router = Router(auth=session_auth, tags=["sessions"])
