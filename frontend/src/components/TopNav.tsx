import { Link, useLocation } from "react-router-dom";

import { ThemeToggle } from "@/components/ThemeToggle";
import { WorkspaceSwitcher } from "@/components/WorkspaceSwitcher";
import { useWorkspace } from "@/hooks/useWorkspace";
import { cn } from "@/lib/utils";

const WORKSPACE_NAV = [
  { label: "Opps", subPath: "opps" },
  { label: "Sessions", subPath: "sessions" },
  { label: "Chat", subPath: "chat" },
];

// "System" sounded operational and was the only entry into the
// "what is ACE?" surface for new users. "Overview" reads as a
// destination instead of an admin-tools tab.
const GLOBAL_NAV = [{ label: "Overview", path: "/system" }];

export function TopNav() {
  const { pathname } = useLocation();
  const { current, all } = useWorkspace();

  // Prefer the URL's workspace; fall back to the user's first one for
  // legacy paths (so the nav links remain useful even on /settings etc.).
  const slug = current?.slug ?? all[0]?.slug;

  return (
    <nav className="flex items-center gap-4 border-b border-border bg-card px-4 py-2 text-sm">
      <Link
        to={slug ? `/w/${slug}/opps` : "/welcome"}
        className="font-semibold text-foreground"
        title="ACE — agentic CRISPR-Connect orchestration. Visit Overview for the full picture."
      >
        ACE
      </Link>
      <Link
        to="/system"
        aria-label="What is ACE? — open the Overview"
        title="What is ACE? — open the Overview"
        className="rounded-full border border-border px-1.5 text-[10px] font-semibold leading-none text-muted-foreground hover:border-primary hover:text-primary"
      >
        ?
      </Link>
      <WorkspaceSwitcher />
      <div className="flex items-center gap-4">
        {WORKSPACE_NAV.map((item) => {
          const target = slug ? `/w/${slug}/${item.subPath}` : `/${item.subPath}`;
          const isActive = pathname.includes(`/${item.subPath}`);
          return (
            <Link
              key={item.subPath}
              to={target}
              className={cn(
                "text-muted-foreground hover:text-foreground",
                isActive && "text-foreground font-medium",
              )}
            >
              {item.label}
            </Link>
          );
        })}
        {GLOBAL_NAV.map((item) => {
          const isActive = pathname.startsWith(item.path);
          return (
            <Link
              key={item.path}
              to={item.path}
              className={cn(
                "text-muted-foreground hover:text-foreground",
                isActive && "text-foreground font-medium",
              )}
            >
              {item.label}
            </Link>
          );
        })}
      </div>
      <div className="ml-auto">
        <ThemeToggle />
      </div>
    </nav>
  );
}
