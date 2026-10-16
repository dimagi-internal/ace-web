"""Emailing a workspace invite's accept link to the person invited.

The invite row is the source of truth; the email is a courtesy on top. A send
that fails (mail not configured, SES refusing) never fails the invite — the
caller gets `False` and the settings page falls back to the copyable link.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMessage

logger = logging.getLogger(__name__)

_ROLE_WORDS = {
    "owner": "an owner",
    "admin": "an admin",
    "editor": "an editor",
    "viewer": "a viewer",
}


def accept_url(invite) -> str:
    """The public link that redeems `invite` (config/urls.py `spa_invite`)."""
    base = (settings.ACE_PUBLIC_BASE_URL or "").rstrip("/")
    return f"{base}/invite/{invite.token}/"


def send_invite_email(invite, inviter) -> bool:
    """Email `invite`'s accept link to its address. True when handed to the
    mail backend; False when email is off or the send raised."""
    if not settings.ACE_EMAIL_ENABLED:
        return False
    inviter_name = (getattr(inviter, "display_name", "") or inviter.email).strip()
    workspace_name = invite.workspace.display_name or invite.workspace.slug
    expires = f"{invite.expires_at.day} {invite.expires_at:%B %Y}"
    body = (
        f"{inviter_name} ({inviter.email}) invited you to join the "
        f"\"{workspace_name}\" workspace on ACE as "
        f"{_ROLE_WORDS.get(invite.role, invite.role)}.\n\n"
        f"Accept the invite here:\n{accept_url(invite)}\n\n"
        f"You can sign in with Google or CommCare, or set a password. "
        f"Use {invite.email} — the invite is for that address only. "
        f"The link works until {expires}.\n\n"
        f"Questions? Reply to this email to reach {inviter_name}.\n"
    )
    message = EmailMessage(
        subject=f"{inviter_name} invited you to {workspace_name} on ACE",
        body=body,
        to=[invite.email],
        reply_to=[inviter.email],
    )
    try:
        return message.send() == 1
    except Exception:
        logger.exception("invite email to %s failed", invite.email)
        return False
