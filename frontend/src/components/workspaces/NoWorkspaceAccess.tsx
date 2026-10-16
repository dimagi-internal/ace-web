import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  listMyPendingInvites,
  type MyPendingInvite,
  type WorkspaceRole,
} from "@/api/workspaces";
import { LoadingSpinner } from "@/components/opps/LoadingStates";

// Same wording as the invite email (apps/workspaces/invite_email.py _ROLE_WORDS).
const ROLE_WITH_ARTICLE: Record<WorkspaceRole, string> = {
  owner: "an owner",
  admin: "an admin",
  editor: "an editor",
  viewer: "a viewer",
};

/**
 * What a signed-in visitor sees on a `/w/<slug>/…` route for a workspace they
 * are not a member of (#911).
 *
 * The API answers non-members with the same 404 as a missing workspace, so
 * this page must say the same thing either way: nothing here depends on
 * whether `<slug>` exists. The one thing it adds — an "Accept invitation"
 * button — comes from the visitor's OWN pending invites
 * (`GET /api/invites/mine`), which can only name a workspace they were
 * invited to.
 */
export function NoWorkspaceAccess({ workspaceSlug }: { workspaceSlug: string }) {
  const [invite, setInvite] = useState<MyPendingInvite | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    setInvite(undefined);
    listMyPendingInvites(workspaceSlug)
      .then((invites) => {
        if (!cancelled) setInvite(invites.find((i) => i.workspace_slug === workspaceSlug) ?? null);
      })
      .catch(() => {
        // Can't tell whether an invite is waiting — fall back to the plain
        // no-access copy rather than an error the visitor can't act on.
        if (!cancelled) setInvite(null);
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceSlug]);

  if (invite === undefined) return <LoadingSpinner />;

  return (
    <div className="mx-auto max-w-xl px-6 py-12" data-testid="no-workspace-access">
      {invite ? (
        <>
          <h1 className="text-2xl font-semibold text-foreground">
            You've been invited to {invite.workspace_display_name} as{" "}
            {ROLE_WITH_ARTICLE[invite.role]}.
          </h1>
          {invite.invited_by_email && (
            <p className="mt-2 text-sm text-muted-foreground">
              Invited by {invite.invited_by_email}.
            </p>
          )}
          <Link
            to={invite.accept_url}
            className="mt-6 inline-flex items-center rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
          >
            Accept invitation
          </Link>
        </>
      ) : (
        <>
          <h1 className="text-2xl font-semibold text-foreground">
            You don't have access to this workspace
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Ask the person who sent you this link to invite you.
          </p>
        </>
      )}
    </div>
  );
}
