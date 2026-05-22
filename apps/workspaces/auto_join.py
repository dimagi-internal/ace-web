"""Auto-join workspaces based on user email domain.

A Workspace can declare `auto_join_domains` — a list of lowercased email
domains whose users get an Editor membership added on login. Used by the
OAuth callback so e.g. anyone signing in with @dimagi.com lands inside
the dimagi-team workspace instead of an empty /welcome wizard.

The function is idempotent: it never downgrades an existing membership
role (so a Workspace Owner who happens to match the auto-join domain
keeps their owner role on subsequent logins).
"""
from __future__ import annotations

import logging

from apps.workspaces.models import Workspace

logger = logging.getLogger(__name__)


def _email_domain(email: str) -> str:
    _, _, domain = (email or "").lower().rpartition("@")
    return domain.strip()


def ensure_auto_join_memberships(user) -> list[Workspace]:
    """Add `user` as Editor to every Workspace whose auto_join_domains
    includes their email domain. Existing memberships are left untouched
    (no role downgrade). Returns the list of workspaces the user newly
    joined (empty if nothing changed)."""
    from apps.workspaces.models import WorkspaceMembership

    domain = _email_domain(getattr(user, "email", "") or "")
    if not domain:
        return []

    # Few workspaces; filter in Python to keep query portable across
    # Postgres and the in-memory SQLite test DB.
    matched = [
        ws
        for ws in Workspace.objects.all()
        if domain in {d.lower().lstrip("@").strip() for d in (ws.auto_join_domains or [])}
    ]
    if not matched:
        return []

    newly_joined: list[Workspace] = []
    for ws in matched:
        _, created = WorkspaceMembership.objects.get_or_create(
            workspace=ws,
            user=user,
            defaults={"role": "editor"},
        )
        if created:
            newly_joined.append(ws)
            logger.info(
                "auto_join: added %s to workspace %s as editor (domain=%s)",
                user.email,
                ws.slug,
                domain,
            )
    return newly_joined
