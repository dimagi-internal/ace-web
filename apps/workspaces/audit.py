"""Recording who changed a workspace's membership — the one writer of
`MembershipChange`. Every invite, role change and removal goes through here,
in the same transaction as the change itself, so the activity feed cannot miss
one."""
from __future__ import annotations


def record_membership_change(workspace, action: str, *, email: str, actor,
                             before_role: str = "", after_role: str = "") -> None:
    from apps.workspaces.models import MembershipChange

    MembershipChange.objects.create(
        workspace=workspace,
        action=action,
        email=email,
        actor=actor if getattr(actor, "pk", None) else None,
        before_role=before_role or "",
        after_role=after_role or "",
    )
