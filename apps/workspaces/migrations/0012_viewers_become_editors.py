"""Every existing `viewer` becomes an `editor` — memberships AND pending invites.

Until 0011 a workspace `viewer` could confirm, change and comment on the
decisions on a run summary; from 0011 on a viewer is read-only, as in
canopy-web (owner decision, 2026-10-07: "lets use the same acl as canopy,
owner, admin, editor, viewer"), and the review-and-edit tier is `editor`.

Every viewer that exists today was granted in order to review and edit:
ACE's `/ace:release` invited every outside reviewer as `viewer` precisely so
they could confirm, change and comment (workspace `spark` had seven such
reviewers when this shipped, members and pending invites both). Left alone,
each would silently lose the edit rights they were invited for. So this moves
them to `editor`, the role that now carries exactly what they had. Nothing
they could do before is lost; nothing new is granted except what `editor`
adds over the old viewer (the Workbench writes an editor always had).

What it touches:

* every `WorkspaceMembership` with role `viewer` → `editor`;
* every PENDING `WorkspaceInvite` (not accepted, not revoked) with role
  `viewer` → `editor` — an invite accepted after this would otherwise mint a
  read-only member. Expired-but-unactioned invites are included: they are
  still the record of what was offered, and reissuing one should offer edit.
  Accepted and revoked invites are history and are left as written.

Except canopy's live-probe principal (`apps/canopy/probe.py`): it is a viewer
of the `canopy-probe` workspace BY DESIGN — the least privilege that still
makes its one read meaningful — and `ensure_principal` forces it back to
viewer anyway. It is left a viewer.

Reverse is a deliberate no-op. After this runs, "was a viewer before 0012"
and "was made an editor on purpose" are indistinguishable, so a reverse that
demoted every editor would strip access from people who were always editors;
and rolling back 0011 alone (the viewer→read-only change) already restores
what these rows meant. Nothing needs undoing for the schema to roll back.
"""
from django.db import migrations

VIEWER, EDITOR = "viewer", "editor"
#: apps.canopy.probe.PROBE_WORKSPACE_SLUG — its viewer membership is intended.
PROBE_WORKSPACE_SLUG = "canopy-probe"


def viewers_to_editors(apps, schema_editor):
    WorkspaceMembership = apps.get_model("ace_workspaces", "WorkspaceMembership")
    WorkspaceInvite = apps.get_model("ace_workspaces", "WorkspaceInvite")

    WorkspaceMembership.objects.filter(role=VIEWER).exclude(
        workspace__slug=PROBE_WORKSPACE_SLUG,
    ).update(role=EDITOR)
    WorkspaceInvite.objects.filter(
        role=VIEWER, accepted_at__isnull=True, revoked_at__isnull=True,
    ).exclude(workspace__slug=PROBE_WORKSPACE_SLUG).update(role=EDITOR)


class Migration(migrations.Migration):

    dependencies = [
        ("ace_workspaces", "0011_admin_role"),
    ]

    operations = [
        # Reverse: no-op on purpose — see the module docstring.
        migrations.RunPython(viewers_to_editors, reverse_code=migrations.RunPython.noop),
    ]
