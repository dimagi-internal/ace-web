"""The one place a sign-in becomes a session.

ace-web has three ways in — email + password, Google, Connect (CommCare) —
and they must not drift apart. Each method proves *who someone is* in its own
way; everything that follows is decided here, once:

1. **Admission** (`admit`): `login_gate.admission_rule`, applied identically.
2. **Linking** (`resolve_user`): the same person is the same `User`, matched by
   email case-insensitively, whichever method they used first.
3. **Session** (`start_session`): `django.contrib.auth.login` (which rotates
   the session key), then auto-join-by-domain.

A method's view calls these; it never reimplements them. Adding a fourth
method means writing its proof of identity and calling the same three.

Spec: docs/specs/2026-10-08-normal-login-design.md.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import login
from django.http import HttpRequest

from apps.auth.login_gate import admission_rule
from apps.auth.models import User

logger = logging.getLogger(__name__)

#: Backend recorded in the session. Every method uses the same one; the
#: password path authenticates through it too (case-insensitive email lookup
#: lives on `UserManager.get_by_natural_key`).
SESSION_BACKEND = "django.contrib.auth.backends.ModelBackend"

METHOD_PASSWORD = "password"
METHOD_GOOGLE = "google"
METHOD_CONNECT = "connect"
METHOD_INVITE_PASSWORD = "invite-password"


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def not_admitted_message() -> str:
    """The refusal shown for an un-invited outsider, identical for every method."""
    allowed = getattr(settings, "ACE_ALLOWED_EMAIL_DOMAINS", []) or []
    allowed_str = ", ".join(f"@{d}" for d in allowed)
    return (
        f"Access is restricted to {allowed_str} accounts. If you were invited, "
        "sign in with the email address the invite was sent to."
    )


def admit(email: str, *, method: str) -> bool:
    """True if `email` may sign in. Logs the refusal (and invite/membership admits)."""
    rule = admission_rule(normalize_email(email))
    if rule is None:
        logger.warning("Rejected %s login for non-admitted email: %r", method, email)
        return False
    if rule in ("invite", "membership"):
        logger.info("Admitted %s login for %r by %s", method, email, rule)
    return True


def find_user(email: str) -> User | None:
    """The existing user for `email`, case-insensitively; None if absent or ambiguous."""
    try:
        return User.objects.get_by_natural_key(normalize_email(email))
    except User.DoesNotExist:
        return None


class LinkError(Exception):
    """A Google identity cannot be attached to the account it matched."""


@dataclass
class Resolved:
    user: User
    created: bool


def resolve_user(
    email: str,
    *,
    display_name: str = "",
    google_sub: str | None = None,
    update_display_name: bool = False,
) -> Resolved:
    """Find the `User` for a proven identity, creating one if there is none.

    CALL `admit` FIRST — a rejected outsider must leave no row behind.

    Linking is by email, case-insensitive, so a person who first came in via
    Connect and later uses Google (or the reverse) is one account. Only a
    *verified* email may reach here for Google — the caller enforces that
    (`google_oauth.verify_id_token`) — because matching on an unverified email
    would hand the account to whoever typed it.

    Raises `LinkError` when the matched account already has a *different*
    Google identity: silently replacing it would let a second Google account
    take over the first one's sign-in.
    """
    email = normalize_email(email)
    user = None
    if google_sub:
        user = User.objects.filter(google_sub=google_sub).first()
    if user is None:
        user = find_user(email)

    if user is None:
        created_user = User.objects.create_user(
            email=email, display_name=display_name, google_sub=google_sub
        )
        return Resolved(created_user, True)

    changed: list[str] = []
    if google_sub and user.google_sub != google_sub:
        if user.google_sub:
            raise LinkError("A different Google account is already linked to this user.")
        user.google_sub = google_sub
        changed.append("google_sub")
    if display_name and (update_display_name or not user.display_name):
        if user.display_name != display_name:
            user.display_name = display_name
            changed.append("display_name")
    if changed:
        user.save(update_fields=[*changed, "updated_at"])
    return Resolved(user, False)


def start_session(request: HttpRequest, user: User, *, method: str) -> None:
    """Log `user` in: rotate the session, then auto-join workspaces by domain.

    `login()` cycles the session key (fixation defence) and, if the session
    already belonged to another user, flushes it. Refuses a deactivated user —
    `login()` itself does not check `is_active`.
    """
    if not user.is_active:
        raise PermissionError("inactive user")
    login(request, user, backend=SESSION_BACKEND)
    request.session["ace_login_method"] = method
    try:
        from apps.workspaces.auto_join import ensure_auto_join_memberships

        ensure_auto_join_memberships(user)
    except Exception as exc:  # noqa: BLE001 — never block login on auto-join
        logger.warning("auto_join failed for %s: %s", user.email, exc)
    logger.info("Signed in %s via %s", user.email, method)


def sign_in(
    request: HttpRequest,
    email: str,
    *,
    method: str,
    display_name: str = "",
    google_sub: str | None = None,
    update_display_name: bool = False,
) -> tuple[User | None, str | None]:
    """Admit → link → start the session, for a method that has proven `email`.

    Returns `(user, None)` on success or `(None, reason)` — `reason` is text
    safe to show the person. Used by Connect and Google; the password path
    arrives with a `User` already authenticated and calls `admit` +
    `start_session` itself (it cannot create one).
    """
    if not admit(email, method=method):
        return None, not_admitted_message()
    try:
        resolved = resolve_user(
            email,
            display_name=display_name,
            google_sub=google_sub,
            update_display_name=update_display_name,
        )
    except LinkError as exc:
        return None, str(exc)
    try:
        start_session(request, resolved.user, method=method)
    except PermissionError:
        return None, "This account is deactivated. Contact an administrator."
    return resolved.user, None
