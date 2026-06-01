import { Link, useLocation } from "react-router-dom";

import { UserMenu } from "@/components/UserMenu";
import { WorkspaceSwitcher } from "@/components/WorkspaceSwitcher";
import { useWorkspace } from "@/hooks/useWorkspace";
import { cn } from "@/lib/utils";

const WORKSPACE_NAV = [
  { label: "Activity", subPath: "activity" },
  { label: "Opps", subPath: "opps" },
  { label: "Sessions", subPath: "sessions" },
  { label: "Chat", subPath: "chat" },
  { label: "Videos", subPath: "videos" },
];

export function TopNav() {
  const { pathname } = useLocation();
  const { current, all } = useWorkspace();

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
        <WorkspaceSwitcher />
        <UserMenu />
      </div>
    </nav>
  );
}
