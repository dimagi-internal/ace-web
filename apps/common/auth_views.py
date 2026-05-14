"""CLI + Nova credential access helpers.

The DRF-decorated endpoint functions that previously lived here were removed
in the Phase 5 API modernisation.  All traffic now flows through the Ninja v2
router (``apps/auth/api_v2.py``).

This module retains ``_can_write_global`` because it is imported by
``apps/auth/api_v2.py`` for the promote / disconnect / nova-status endpoints.
"""
from __future__ import annotations

# Domain reserved for ACE automation identities (e.g. ace@dimagi-ai.com).
_AUTOMATION_EMAIL_DOMAIN = "@dimagi-ai.com"


def _can_write_global(user) -> bool:
    """Return True for staff users and automation accounts on @dimagi-ai.com."""
    if user.is_staff:
        return True
    email = (user.email or "").lower()
    return email.endswith(_AUTOMATION_EMAIL_DOMAIN)
