import { Link, useLocation } from "react-router-dom";
import { PresenceBadge, pageKeyFor, usePresence } from "canopy-ui/presence";

import { UserMenu } from "@/components/UserMenu";
import { WorkspaceSwitcher } from "@/components/WorkspaceSwitcher";
import { useWorkspace } from "@/hooks/useWorkspace";
import { cn } from "@/lib/utils";
import { wsUrl } from "@/lib/wsUrl";
import { acePresenceRules } from "@/presence/routes";
import { usePresenceReconnectNonce } from "@/presence/usePresenceReconnectNonce";

const WORKSPACE_NAV = [
  { label: "Activity", subPath: "activity" },
  { label: "Opps", subPath: "opps" },
  { label: "Sessions", subPath: "sessions" },
  { label: "Chat", subPath: "chat" },
  { label: "Videos", subPath: "videos" },
];

// One presence socket per tab, mounted here (TopNav persists across
// navigation via App.tsx's Outlet, so it's the right layout-level home for
// it) so the socket persists across route changes rather than churning a
// new handshake on every click — `usePresence` re-keys the existing
// connection on pathname change instead of reconnecting.
//
// Split into its own component and keyed by `presenceReconnectNonce` below:
// the `PresenceConsumer` only re-reads the user's visibility preference on
// `presence.enter` (i.e. the next navigation) — see
// `apps/presence/consumers.py`. A user who just opted out in Settings would
// otherwise stay visible in every already-open tab until it happened to
// navigate. Bumping the key forces React to unmount this subtree (closing
// the socket in `usePresence`'s cleanup) and mount a fresh one, which
// reconnects and sends a brand-new `presence.enter` under the just-saved
// preference. See `usePresenceReconnectNonce` for the mechanism.
function PresenceHeaderBadge() {
  const { pathname } = useLocation();
  const location = pageKeyFor("ace", pathname, acePresenceRules);
  const { viewers } = usePresence({ url: wsUrl("ws/presence/"), location });
  return <PresenceBadge viewers={viewers} />;
}

export function TopNav() {
  const { pathname } = useLocation();
  const { current, all } = useWorkspace();
  const presenceReconnectNonce = usePresenceReconnectNonce();

  // Prefer the URL's workspace; fall back to the user's first one for
  // legacy paths (so the nav links remain useful even on /settings etc.).
  const slug = current?.slug ?? all[0]?.slug;

  return (
    <nav className="flex items-center gap-3 border-b border-border bg-card px-4 py-2 text-sm">
      <Link
        to={slug ? `/w/${slug}/opps` : "/welcome"}
        className="font-semibold text-foreground"
        title="ACE Workbench — agentic CRISPR-Connect orchestration"
      >
        ACE
      </Link>

      {/* Workspace-scoped nav. The opp/page name in the body dominates
          the header — workspace switcher lives in the right cluster
          since for most users it's near-static. */}
      <div className="flex items-center gap-4">
        {WORKSPACE_NAV.map((item) => {
          const target = slug ? `/w/${slug}/${item.subPath}` : `/${item.subPath}`;
          const isActive = pathname.includes(`/${item.subPath}`);
          return (
            <Link
              key={item.subPath}
              to={target}
              className={cn(
                "flex items-center gap-1.5 text-muted-foreground hover:text-foreground",
                isActive && "text-foreground font-medium",
              )}
            >
              <span>{item.label}</span>
            </Link>
          );
        })}
      </div>

      {/* Utility cluster, right-aligned. System Overview lives in the
          account menu (UserMenu) now — it's a global destination, not a
          workspace page, so it doesn't belong inline with the nav. */}
      <div className="ml-auto flex items-center gap-4">
        <PresenceHeaderBadge key={presenceReconnectNonce} />
        <WorkspaceSwitcher />
        <UserMenu />
      </div>
    </nav>
  );
}
