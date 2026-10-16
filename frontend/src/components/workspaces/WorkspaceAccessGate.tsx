import { useEffect, useState } from "react";
import { Outlet, useParams } from "react-router-dom";

import { listWorkspaces } from "@/api/workspaces";
import { LoadingSpinner } from "@/components/opps/LoadingStates";

import { NoWorkspaceAccess } from "./NoWorkspaceAccess";

type Membership = "checking" | "member" | "not-member" | "unknown";

/**
 * Layout for every `/w/:workspaceSlug/…` route (#911).
 *
 * Every workspace-scoped API answers a non-member with a plain 404 — the same
 * answer as a workspace that does not exist — and each page used to render
 * that as "This doesn't exist (anymore)… moved in Drive", which is wrong for
 * someone who simply isn't in the workspace. The visitor's OWN membership
 * list (`GET /api/workspaces`) tells the two apart without the server leaking
 * anything: a slug that isn't in it gets the no-access page, which reads the
 * same whether or not the workspace exists. Members fall through to the page,
 * so a genuine not-found inside their workspace keeps its existing copy.
 */
export function WorkspaceAccessGate() {
  const { workspaceSlug = "" } = useParams<{ workspaceSlug: string }>();
  const [membership, setMembership] = useState<Membership>("checking");

  // Re-checked per slug, not once per mount: this layout stays mounted when
  // the visitor switches workspace (or creates one and is sent to it), so a
  // list fetched for the previous slug would be stale.
  useEffect(() => {
    let cancelled = false;
    setMembership("checking");
    listWorkspaces()
      .then((all) => {
        if (cancelled) return;
        setMembership(all.some((w) => w.slug === workspaceSlug) ? "member" : "not-member");
      })
      .catch(() => {
        // Can't tell — let the page load and report its own error.
        if (!cancelled) setMembership("unknown");
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceSlug]);

  if (membership === "checking") return <LoadingSpinner />;
  if (membership === "not-member") return <NoWorkspaceAccess workspaceSlug={workspaceSlug} />;
  return <Outlet />;
}
