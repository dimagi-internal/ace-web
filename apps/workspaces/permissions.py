"""What each workspace role may DO — the one table, and the only door to it.

ace-web runs canopy-web's workspace ACL (owner decision, 2026-10-07: "lets
use the same acl as canopy, owner, admin, editor, viewer"). The roles and
their order live on `models.WorkspaceMembership` (`ROLE_RANK`); this module
answers the question every gate actually asks: **may this person do X in
this workspace?** Code outside `apps/workspaces/` asks it here, by
CAPABILITY, and never names a role — `tests/test_roles_named_only_in_workspaces.py`
fails the build on a role constant, a role-name comparison, or a role set
anywhere else.

Why a table rather than a role check at each call site: before this, ace-web
spelled one tier four ways (`role_for(...) != "owner"`, `role not in
TEAM_VIEW_ROLES`, `role__in=("owner", "editor")`, a bare membership test), and
canopy's 2026-10-02 audit found that inserting a role between editor and owner
silently changes what such spellings mean. With the table, adding or moving a
role is one edit here, and every gate follows.

Capabilities are named for what they PROTECT, not for a page, so one is
reused across surfaces that share a trust decision. ace-web's set is smaller
than canopy's on purpose — it is derived from what ace-web gates, not copied:

====================  =========  =============================================
capability            minimum    what it protects
====================  =========  =============================================
``read``              viewer     read the workspace: opps, runs, the Workbench,
                                 the run summary as a member — including a
                                 PRIVATE review's feedback ledger (membership,
                                 not team view; owner decision 2026-10-08)
``content.write``     editor     create / change / delete workspace content:
                                 opps, runs, forks, gate decisions, seeded runs,
                                 sessions, uploads, videos
``decisions.write``   editor     confirm, change or comment on a decision (run
                                 summary + the Workbench's decision overrides)
``summary.team_view`` admin      the TEAM view of a run summary (run ids,
                                 grader logs, lineage history, claim audit
                                 evidence); everyone below
                                 gets the partner view an outsider gets
``logs.read``         admin      the workspace audit log
``members.manage``    admin      invite, change and remove members — strictly
                                 BELOW your own role (`may_manage_member`)
``own``               owner      the keys: workspace settings (name, Drive
                                 root, auto-join domains, default tenancy),
                                 per-opp tenancy, cloning and releasing runs,
                                 the resume-interrupted sweep
====================  =========  =============================================
"""
from __future__ import annotations

from django.db.models import QuerySet

from apps.workspaces.models import Workspace
from apps.workspaces.models import WorkspaceMembership as _M

# --- viewer: reading --------------------------------------------------------------

#: Read anything the workspace holds: opps, runs, the Workbench, the run
#: summary (as a member) — and on it, a PRIVATE review's feedback ledger,
#: which a non-member never gets (owner decision 2026-10-08: "reviewers can
#: see the feedback"). The summary asks this as plain membership.
READ = "read"

# --- editor: making things --------------------------------------------------------

#: Create, change or delete workspace content: opps, runs, forks, gate
#: decisions, seeded runs, sessions, uploads, videos.
CONTENT_WRITE = "content.write"

#: Confirm, change or comment on a decision — on the run summary
#: (`apps.opps.api._member_reviewer`) and in the Workbench's decision editor.
#: A viewer reads decisions and their discussion but cannot change them.
DECISIONS_WRITE = "decisions.write"

# --- admin: running the workspace -------------------------------------------------

#: The TEAM view of a run summary: run ids, grader logs, per-decision lineage
#: history, claim audit ``evidence``. Everyone below — editors and viewers
#: alike, and non-members — gets the PARTNER view (orientation block, plain
#: deep QA, lineage in plain words).
#: Presentation, not access: an editor in the partner view may still write.
SUMMARY_TEAM_VIEW = "summary.team_view"

#: The workspace audit log (Drive accesses, tenancy changes).
LOGS_READ = "logs.read"

#: Invite people and change or remove members — always strictly BELOW your
#: own role (`may_manage_member`). Owners act on anyone.
MEMBERS_MANAGE = "members.manage"

# --- owner: the keys --------------------------------------------------------------

#: The workspace's keys: its settings (name, Drive root folder, auto-join
#: domains, default tenancy), per-opp tenancy (where ACE may write), cloning
#: and releasing runs into other workspaces, and the resume-interrupted sweep.
#: An ADMIN holds none of this: running a workspace is not holding its keys.
OWN = "own"

MINIMUM_ROLE: dict[str, str] = {
    READ: _M.VIEWER,
    CONTENT_WRITE: _M.EDITOR,
    DECISIONS_WRITE: _M.EDITOR,
    SUMMARY_TEAM_VIEW: _M.ADMIN,
    LOGS_READ: _M.ADMIN,
    MEMBERS_MANAGE: _M.ADMIN,
    OWN: _M.OWNER,
}

#: Every role, highest first — for validating a role a caller supplies (an
#: invite, a role change) without naming one outside this app.
ROLES: tuple[str, ...] = tuple(sorted(_M.ROLE_RANK, key=_M.ROLE_RANK.__getitem__, reverse=True))

#: The role a membership gets when a caller does not say (an invite with no
#: role, an auto-join). Editor: may review and edit, holds no keys.
DEFAULT_ROLE = _M.EDITOR


def _rank(role: str | None) -> int:
    return _M.ROLE_RANK.get(role or "", -1)


def is_role(role: str | None) -> bool:
    """Is `role` one of the four workspace roles?"""
    return role in _M.ROLE_RANK


def role_allows(role: str | None, capability: str) -> bool:
    """Does `role` hold `capability`? For a caller that already has the role in
    hand. ``None`` (not a member) holds nothing. An unknown capability raises
    KeyError — a typo must not read as "no"."""
    return _rank(role) >= _M.ROLE_RANK[MINIMUM_ROLE[capability]]


def higher_role(a: str | None, b: str | None) -> str | None:
    """The higher-ranked of two roles (for upgrade-only grants)."""
    return a if _rank(a) >= _rank(b) else b


# --- membership reads -------------------------------------------------------------


def is_member(user, workspace: Workspace) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return _M.objects.filter(workspace=workspace, user=user).exists()


def role_for(user, workspace: Workspace | str) -> str | None:
    """`user`'s role in `workspace` (a `Workspace` or its slug), or None.

    For DISPLAY. To decide anything, ask `can` — comparing this to a role name
    outside `apps/workspaces/` fails the build."""
    if not getattr(user, "is_authenticated", False):
        return None
    qs = _M.objects.filter(user=user)
    qs = qs.filter(workspace__slug=workspace) if isinstance(workspace, str) else qs.filter(
        workspace=workspace)
    return qs.values_list("role", flat=True).first()


def can(user, workspace: Workspace | str, capability: str) -> bool:
    """May `user` exercise `capability` in `workspace` (a `Workspace` or slug)?
    False for a non-member or an anonymous user. An unknown capability raises
    KeyError rather than reading as "no"."""
    MINIMUM_ROLE[capability]  # fail loudly on a typo, even for an anonymous user
    return role_allows(role_for(user, workspace), capability)


def slugs_with(user, capability: str) -> set[str]:
    """The workspaces where `user` holds `capability` — for listings and bulk
    operations that span tenants. One query."""
    MINIMUM_ROLE[capability]
    if not getattr(user, "is_authenticated", False):
        return set()
    rows = _M.objects.filter(user=user).values_list("workspace__slug", "role")
    return {slug for slug, role in rows if role_allows(role, capability)}


def require_role(user, workspace: Workspace, minimum: str) -> bool:
    """True iff `user` is a member of `workspace` with a role >= `minimum`.

    Rank-by-name — kept for this app's own use; everything else asks `can`."""
    return _rank(role_for(user, workspace)) >= _M.ROLE_RANK[minimum]


def may_manage_member(actor_role: str | None, target_role: str | None,
                      new_role: str | None = None) -> bool:
    """May someone holding `actor_role` change a member holding `target_role`
    (to `new_role`, or remove them when `new_role` is None), or invite at
    `new_role` (pass `target_role=None`)?

    An owner may do anything to anyone (the last-owner guard is separate, in
    `api`). Anyone else with MEMBERS_MANAGE acts only STRICTLY below
    themselves, and may only grant a role strictly below themselves — so an
    admin can invite, promote and remove viewers and editors, but can neither
    make another admin nor touch one, and nothing short of an owner can mint an
    owner. Same rule as canopy-web's `permissions.may_manage_member`.
    """
    if actor_role == _M.OWNER:
        return True
    if not role_allows(actor_role, MEMBERS_MANAGE):
        return False
    mine = _rank(actor_role)
    if target_role is not None and _rank(target_role) >= mine:
        return False
    if new_role is not None and _rank(new_role) >= mine:
        return False
    return True


def is_owner_role(role: str | None) -> bool:
    """Is `role` the owner role? For the last-owner guard, which counts owners."""
    return role == _M.OWNER


def owners(workspace: Workspace):
    """The workspace's owner memberships (for the last-owner guard)."""
    return workspace.memberships.filter(role=_M.OWNER)


def user_workspaces(user) -> QuerySet[Workspace]:
    """Workspaces the user is a member of, ordered by most-recent membership first."""
    if not getattr(user, "is_authenticated", False):
        return Workspace.objects.none()
    return Workspace.objects.filter(memberships__user=user).order_by(
        "-memberships__joined_at"
    )
