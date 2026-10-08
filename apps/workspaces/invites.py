"""Redeeming a workspace invite — shared by every way of accepting one."""
from __future__ import annotations

from django.utils import timezone


def grant_invite(invite, user):
    """Give `user` the membership `invite` offers and mark it accepted.

    The caller holds the transaction and has already checked the invite is
    pending and addressed to this user. Returns the membership.
    """
    from apps.workspaces import permissions as perms
    from apps.workspaces.models import WorkspaceMembership

    membership, created = WorkspaceMembership.objects.get_or_create(
        workspace=invite.workspace,
        user=user,
        defaults={"role": invite.role, "invited_by": invite.invited_by},
    )
    # UPGRADE-ONLY (canopy-web's rule): an existing member moves to the
    # HIGHER of their role and the invite's, never lower — a stray invite
    # must not strip access. Demotion is the explicit role-change PATCH.
    if not created:
        higher = perms.higher_role(membership.role, invite.role)
        if higher != membership.role:
            membership.role = higher
            membership.save(update_fields=["role"])
    invite.accepted_at = timezone.now()
    invite.save(update_fields=["accepted_at"])
    return membership
