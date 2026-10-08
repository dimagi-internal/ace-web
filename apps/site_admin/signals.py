"""Bootstrap: grant site admin on sign-in to the emails in ACE_SITE_ADMIN_EMAILS.

Lives here, not in `apps/auth`, and hangs off Django's `user_logged_in` so it
covers every sign-in method (Connect OAuth, password, Google) without any of
them knowing. It only ever GRANTS, to exactly the listed emails; removing an
email from the setting does not revoke (use the Site admin page).
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .services import record_staff_change


@receiver(user_logged_in)
def grant_bootstrap_admin(sender, request, user, **kwargs) -> None:
    emails = getattr(settings, "ACE_SITE_ADMIN_EMAILS", [])
    listed = {e.strip().lower() for e in emails if e.strip()}
    if not listed or user.is_staff or not user.is_active:
        return
    if (user.email or "").strip().lower() not in listed:
        return
    record_staff_change(actor=None, target=user, new_is_staff=True, source="bootstrap")
