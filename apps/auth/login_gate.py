"""Who may sign in to ace-web.

Connect OAuth proves who someone is; this decides whether ace-web lets them
in. Workspace membership is the real access-control gate, so beyond the
`ACE_ALLOWED_EMAIL_DOMAINS` list we also admit anyone a workspace has
invited, and anyone who already belongs to a workspace. The membership rule
matters because accepting an invite uses it up — without it an invited
partner could sign in exactly once. Removing someone's last membership is
therefore how a partner is cut off.

Spec: docs/specs/2026-09-28-clone-and-release-design.md § A.
"""
from __future__ import annotations

from django.conf import settings
from django.db.models import Q
from django.utils import timezone


def admission_rule(email: str) -> str | None:
    """Return the rule that admits `email`, or None to reject it.

    Rules, checked in order: ``"open"`` (the domain list is empty),
    ``"domain"``, ``"invite"`` (a pending workspace invite), ``"membership"``.
    """
    from apps.workspaces.models import WorkspaceInvite, WorkspaceMembership

    email = (email or "").strip().lower()
    allowed_domains = getattr(settings, "ACE_ALLOWED_EMAIL_DOMAINS", []) or []
    if not allowed_domains:
        return "open"
    if not email:
        return None
    _, _, email_domain = email.rpartition("@")
    if email_domain in allowed_domains:
        return "domain"

    pending_invite = WorkspaceInvite.objects.filter(
        Q(email__iexact=email),
        accepted_at__isnull=True,
        revoked_at__isnull=True,
        expires_at__gt=timezone.now(),
    )
    if pending_invite.exists():
        return "invite"
    if WorkspaceMembership.objects.filter(user__email__iexact=email).exists():
        return "membership"
    return None


def is_internal(user) -> bool:
    """True for Dimagi staff: ``is_staff``, or an email on the domain list.

    Invite-only login (`admission_rule`'s "invite" / "membership" rules) lets
    outside reviewers sign in, so "signed in" no longer means "Dimagi". Any
    endpoint that was written assuming it did — plugin refresh, the system
    overview, workspace creation — checks this instead.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False):
        return True
    allowed_domains = getattr(settings, "ACE_ALLOWED_EMAIL_DOMAINS", []) or []
    if not allowed_domains:
        return True
    _, _, domain = (getattr(user, "email", "") or "").strip().lower().rpartition("@")
    return domain in allowed_domains
