"""canopy's LIVE PROBE at ace-web: one dedicated principal, one read.

The host grant (``apps/canopy/grant.py``) is only exercised when a real visitor
asks canopy's agent for something on the opp Workbench — so a broken chain
(key, metadata, token endpoint, DPoP gate, tool scope, delegated auth) used to
surface as an agent that silently could not read. The canopy SDK's probe
(``canopy_sdk.host.ProbeHandler``, SDK 0.4.0) lets canopy walk that chain on a
schedule with nobody at a keyboard: our probe endpoint
(``/api/canopy/oauth/probe``) signs a real ID-JAG for ONE fixed principal —
never anyone the request names — canopy redeems it through the normal
jwt-bearer path and calls ``PROBE_TOOL`` with the DPoP-bound token.

The principal is created by migration ``ace_workspaces.0010`` (deploy with
``run_migrations: true``), and is deliberately the least it can be while the
call still means something:

* ``PROBE_EMAIL`` is on the reserved ``.invalid`` TLD (RFC 2606), so no Connect
  OAuth identity can ever carry it — there is no sign-in path — and it has an
  unusable password. ``is_staff`` is false.
* It is a VIEWER of exactly one workspace, ``PROBE_WORKSPACE_SLUG``, which has
  no Drive root: ``list_opps`` there runs the full delegated path (the visitor's
  own membership check included — a non-member gets 404, which the probe would
  report as a failure) and returns an empty list without touching Drive. It can
  read no real workspace, so even whoever holds canopy's client key learns
  nothing through the probe.

``subject()`` is the SDK's ``SUBJECT_RESOLVER``: it answers ``""`` until that
user exists, which keeps the probe endpoint 404 and out of the metadata. The
subject is the lower-cased EMAIL, not the primary key, because that is
ace-web's ``sub`` for everyone (``grant.subject_for``; ``SUBJECT_ACTIVE`` and
the delegated auth in ``apps/api/auth.py`` both look people up by email).
"""
from __future__ import annotations

import asyncio

#: The probe principal. `.invalid` can never be a real mailbox or a Connect login.
PROBE_EMAIL = "canopy-probe@probe.invalid"
PROBE_DISPLAY_NAME = "canopy live probe (not a person)"
#: The one workspace it is a viewer of. No Drive root: it holds nothing.
PROBE_WORKSPACE_SLUG = "canopy-probe"
PROBE_WORKSPACE_NAME = "canopy live probe"
#: `drive_root_folder_id` is NOT NULL + unique; empty is what
#: `access.resolve_ace_root_folder_id` treats as "no Drive root", so every opp
#: read of this workspace answers empty without a Drive call.
PROBE_DRIVE_ROOT = ""
PROBE_ROLE = "viewer"

#: The one call canopy makes: a read `opps:read` unlocks, meaningful for the
#: principal (it is a member of that workspace, so it succeeds).
PROBE_SCOPE = "opps:read"
PROBE_TOOL = "apps_opps_api_list_opps"
PROBE_ARGUMENTS = {"workspace_slug": PROBE_WORKSPACE_SLUG}
#: A REAL tool outside `opps:read` that the MCP must refuse to a delegated
#: session. A read (GET) on a workspace the principal is not in, so even if the
#: scope fence failed it would reveal nothing — and canopy calls it with empty
#: arguments, which the route would reject anyway.
PROBE_DENIED_TOOL = "apps_videos_api_list_programs"
#: The page key the probe stands in for (grant.PAGE_SCOPES), for the audit log.
PROBE_PAGE = "opp-workbench"


def subject() -> str:
    """The probe's ``sub`` — or ``""`` (probe off) while its user does not exist.

    The SDK resolves this on EVERY ``get_host_config()``, including from the
    MCP's DPoP gate, which builds its config on the event loop, where the ORM
    may not be called. Nothing on that path reads the probe, so there it answers
    the configured subject unchecked; the probe endpoint and the metadata are
    sync views and always get the checked answer. The endpoint also re-checks
    the account through ``SUBJECT_ACTIVE`` before it signs anything.
    """
    from apps.canopy.grant import subject_for

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        return subject_for(PROBE_EMAIL)

    from django.contrib.auth import get_user_model

    exists = get_user_model().objects.filter(email__iexact=PROBE_EMAIL, is_active=True).exists()
    return subject_for(PROBE_EMAIL) if exists else ""


def ensure_principal(User, Workspace, WorkspaceMembership):
    """Create (or repair) the probe principal. Idempotent. Takes the model
    classes so the migration can pass its historical ones.

    Never grants more than it finds missing: an existing user keeps no password
    and loses staff/superuser; the membership is forced back to viewer.
    """
    from django.contrib.auth.hashers import make_password

    user = User.objects.filter(email__iexact=PROBE_EMAIL).first()
    if user is None:
        user = User(email=PROBE_EMAIL)
    user.display_name = PROBE_DISPLAY_NAME
    user.password = make_password(None)  # unusable: no password login, ever
    user.google_sub = None
    user.is_active = True
    user.is_staff = False
    user.is_superuser = False
    user.save()

    workspace = Workspace.objects.filter(slug=PROBE_WORKSPACE_SLUG).first()
    if workspace is None:
        workspace = Workspace.objects.create(
            slug=PROBE_WORKSPACE_SLUG, display_name=PROBE_WORKSPACE_NAME,
            drive_root_folder_id=PROBE_DRIVE_ROOT, created_by=user)
    WorkspaceMembership.objects.update_or_create(
        workspace=workspace, user=user, defaults={"role": PROBE_ROLE})
    return user, workspace


def remove_principal(User, Workspace, WorkspaceMembership):
    """The migration's reverse: the principal, its membership and its workspace."""
    WorkspaceMembership.objects.filter(workspace__slug=PROBE_WORKSPACE_SLUG).delete()
    Workspace.objects.filter(slug=PROBE_WORKSPACE_SLUG).delete()
    User.objects.filter(email__iexact=PROBE_EMAIL).delete()
