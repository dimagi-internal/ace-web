"""The public invite page: choose how to sign in — a password, Google or Connect.

`/invite/<token>` (the SPA route) sends anonymous visitors here, because the
invitee may have no CommCare account and the SPA shell is login-gated.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.generic import TemplateView

from apps.auth import google_oauth, identity
from apps.auth.forms import InvitePasswordForm, limited
from apps.auth.models import User
from apps.workspaces.invites import grant_invite
from apps.workspaces.models import WorkspaceInvite

logger = logging.getLogger(__name__)


def spa_invite_path(token: str) -> str:
    return f"{settings.FORCE_SCRIPT_NAME or ''}/invite/{token}"


def invite_entry(request: HttpRequest, token: str) -> HttpResponse:
    """`/invite/<token>`: signed in → the SPA accept page; anonymous → choose a method."""
    if request.user.is_authenticated:
        return TemplateView.as_view(template_name="index.html")(request)
    return redirect("auth:invite", token=token)


def _pending(token: str) -> WorkspaceInvite | None:
    invite = WorkspaceInvite.objects.select_related("workspace").filter(token=token).first()
    return invite if invite and invite.is_pending() else None


def invite_page(request: HttpRequest, token: str) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect(spa_invite_path(token))
    invite = _pending(token)
    if invite is None:
        return render(request, "auth/invite.html", {"invalid": True}, status=410)

    existing = identity.find_user(invite.email) is not None
    form = None
    status = 200
    if not existing:
        if request.method == "POST":
            form = InvitePasswordForm(request.POST, email=invite.email)
            if limited(request, "login", identity.normalize_email(invite.email)):
                form.add_error(None, "Too many attempts. Please wait a few minutes and try again.")
                status = 429
            elif form.is_valid():
                return _create_account(request, invite, form.cleaned_data["password1"])
        else:
            form = InvitePasswordForm(email=invite.email)

    nxt = spa_invite_path(token)
    return render(request, "auth/invite.html", {
        "invite": invite,
        "form": form,
        # An account with this email already exists: setting a password here
        # would let anyone holding the link take it over, so the existing
        # owner signs in (any method) and adds a password from their account.
        "existing_account": existing,
        "next": nxt,
        "google_enabled": google_oauth.is_configured(),
    }, status=status)


def _create_account(request: HttpRequest, invite: WorkspaceInvite, password: str) -> HttpResponse:
    if not identity.admit(invite.email, method=identity.METHOD_INVITE_PASSWORD):
        return render(request, "auth/invite.html", {"invalid": True}, status=403)
    try:
        with transaction.atomic():
            # Re-read under lock: two submits of one link must not both win.
            locked = WorkspaceInvite.objects.select_for_update().select_related(
                "workspace").get(pk=invite.pk)
            if not locked.is_pending():
                return render(request, "auth/invite.html", {"invalid": True}, status=410)
            user = User.objects.create_user(email=identity.normalize_email(locked.email))
            user.set_password(password)
            user.save(update_fields=["password", "updated_at"])
            grant_invite(locked, user)
    except IntegrityError:
        # An account for this email appeared meanwhile; the page now offers sign-in.
        return redirect("auth:invite", token=invite.token)
    invite = locked
    identity.start_session(request, user, method=identity.METHOD_INVITE_PASSWORD)
    logger.info("Created password account for %s from invite to %s",
                user.email, invite.workspace.slug)
    return redirect(f"{settings.FORCE_SCRIPT_NAME or ''}/w/{invite.workspace.slug}/opps")
