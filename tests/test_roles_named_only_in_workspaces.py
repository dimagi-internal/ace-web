"""Outside `apps/workspaces/`, no production code names a workspace ROLE.

It asks `apps/workspaces/permissions.py` for a CAPABILITY instead
(`perms.can(user, ws, perms.DECISIONS_WRITE)`), and the one table there
(`MINIMUM_ROLE`) decides which roles hold it. Ported from canopy-web's
`tests/test_roles_named_only_in_workspaces.py` along with its ACL (owner
decision, 2026-10-07: "lets use the same acl as canopy").

Why a fitness test and not a convention: before this, ace-web spelled one tier
four ways — `role_for(...) != "owner"`, `role not in TEAM_VIEW_ROLES`,
`role__in=("owner", "editor")`, a bare membership test — and canopy-web's
2026-10-02 audit found that inserting `admin` between editor and owner
silently changed what such spellings meant. A role named at a call site is a
decision about the ladder made far from the ladder. With the names confined to
`apps/workspaces/`, a new role is one edit to `permissions.MINIMUM_ROLE`, and
nothing else can disagree.

What it flags, in any non-test, non-migration module outside `apps/workspaces/`:

* `WorkspaceMembership.OWNER` / `.ADMIN` / `.EDITOR` / `.VIEWER`
* `ROLE_RANK` / `ROLE_LEVELS`
* `require_role(` — a rank check by role name; ask `perms.can`
* `role_for(...)` compared with `==`, `!=`, `in` or `not in`
* `<x>.role` compared with a role-name string (`membership.role == "owner"`)
* a set / tuple / list literal holding two or more workspace role names — a
  role SET (`frozenset({"owner", "editor"})`), the shape `TEAM_VIEW_ROLES`
  and the sweep's `_WRITE_ROLES` had

Reading a role to DISPLAY it (`perms.role_for(...)` returned in a payload, or
passed to `perms.role_allows`) is fine — the rule is about deciding, not about
naming in a response.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "apps"

_ROLE_ATTRS = {"OWNER", "ADMIN", "EDITOR", "VIEWER"}
_ROLE_NAMES = {"owner", "admin", "editor", "viewer"}
_BANNED_CALLS = {"require_role"}
_BANNED_NAMES = {"ROLE_RANK", "ROLE_LEVELS"}

#: Modules that hold the same WORDS for a different concept. Each says why.
_EXEMPT = {
    # A chat Session's PARTICIPANT role (apps.sessions.models.SessionParticipant),
    # not a workspace role: it decides nothing about workspace access.
    "apps/sessions/schemas.py": "session participant roles",
    "apps/sessions/models.py": "session participant roles",
}


def _production_modules():
    for path in APPS.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("apps/workspaces/") or rel in _EXEMPT:
            continue
        if "/migrations/" in rel or "/tests/" in rel or path.name.startswith("test_"):
            continue
        yield rel, path


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Attribute):
            return f.attr
        if isinstance(f, ast.Name):
            return f.id
    return ""


def _is_role_str(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value in _ROLE_NAMES


def _violations(tree: ast.AST) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        owner_name = (getattr(node.value, "attr", getattr(node.value, "id", ""))
                      if isinstance(node, ast.Attribute) else "")
        if (isinstance(node, ast.Attribute) and node.attr in _ROLE_ATTRS
                and isinstance(node.value, (ast.Name, ast.Attribute))
                and owner_name == "WorkspaceMembership"):
            out.append((node.lineno, f"WorkspaceMembership.{node.attr}"))
        elif isinstance(node, (ast.Name, ast.Attribute)) and (
                getattr(node, "id", None) in _BANNED_NAMES
                or getattr(node, "attr", None) in _BANNED_NAMES):
            out.append((node.lineno, getattr(node, "id", None) or node.attr))
        elif _call_name(node) in _BANNED_CALLS:
            out.append((node.lineno, f"{_call_name(node)}(...)"))
        elif isinstance(node, ast.Compare):
            sides = [node.left, *node.comparators]
            if not any(isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)) for op in node.ops):
                continue
            if any(_call_name(s) == "role_for" for s in sides):
                out.append((node.lineno, "role_for(...) compared"))
            elif any(isinstance(s, ast.Attribute) and s.attr == "role" for s in sides) and any(
                    _is_role_str(s) for s in sides):
                out.append((node.lineno, ".role compared with a role name"))
        elif isinstance(node, (ast.Set, ast.Tuple, ast.List)):
            if len({e.value for e in node.elts if _is_role_str(e)}) >= 2:
                out.append((node.lineno, "role set literal"))
    return out


def test_no_module_outside_workspaces_names_a_role():
    found = []
    for rel, path in _production_modules():
        src = path.read_text()
        if not re.search(r"WorkspaceMembership|ROLE_RANK|ROLE_LEVELS|require_role|role_for|"
                         r"\.role\b|\"(owner|admin|editor|viewer)\"|'(owner|admin|editor|viewer)'",
                         src):
            continue
        for line, what in _violations(ast.parse(src)):
            found.append(f"{rel}:{line}  {what}")
    assert not found, (
        "Decide by CAPABILITY, not by role — ask apps/workspaces/permissions.py "
        "(perms.can / perms.slugs_with / perms.role_allows) and add a "
        "capability there if none fits:\n  " + "\n  ".join(sorted(found))
    )


def test_the_checker_catches_each_shape():
    """The rule is only as good as its parser — prove each banned shape trips."""
    src = (
        "WorkspaceMembership.OWNER\n"
        "x = models.WorkspaceMembership.ADMIN\n"
        "ROLE_RANK\n"
        "ROLE_LEVELS\n"
        "perms.require_role(u, w, r)\n"
        "if role_for(u, w) != 'owner': pass\n"
        "if perms.role_for(u, w) in roles: pass\n"
        "if membership.role == 'owner': pass\n"
        "TEAM = frozenset({'owner', 'editor'})\n"
        "qs.filter(role__in=('owner', 'editor'))\n"
    )
    kinds = [what for _, what in _violations(ast.parse(src))]
    assert set(kinds) == {
        "WorkspaceMembership.OWNER", "WorkspaceMembership.ADMIN", "ROLE_RANK", "ROLE_LEVELS",
        "require_role(...)", "role_for(...) compared", ".role compared with a role name",
        "role set literal",
    }
    assert kinds.count("role_for(...) compared") == 2
    assert kinds.count("role set literal") == 2


def test_the_checker_passes_capability_questions():
    """Asking by capability — and reading a role to display it — is clean."""
    src = (
        "if perms.can(u, w, perms.DECISIONS_WRITE): pass\n"
        "plain = not perms.role_allows(perms.role_for(u, w), perms.SUMMARY_TEAM_VIEW)\n"
        "payload = {'role': perms.role_for(u, w)}\n"
        "Message.objects.filter(role__in=('user', 'assistant'))\n"
        "PROBE_ROLE = 'viewer'\n"
    )
    assert _violations(ast.parse(src)) == []


def test_every_capability_maps_to_a_real_role():
    from apps.workspaces import permissions as perms
    from apps.workspaces.models import WorkspaceMembership

    assert set(perms.MINIMUM_ROLE.values()) <= set(WorkspaceMembership.ROLE_RANK)
