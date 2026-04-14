import { Link, useLocation } from "react-router-dom";

import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/ThemeToggle";

const NAV_ITEMS = [
  { label: "Library", path: "/library" },
  { label: "Chat", path: "/chat" },
  { label: "Opps", path: "/opps" },
  { label: "System", path: "/system" },
];

export function TopNav() {
  const { pathname } = useLocation();

  return (
    <nav className="flex items-center gap-6 border-b border-border bg-card px-4 py-2 text-sm">
      <Link to="/" className="font-semibold text-foreground">
        ACE
      </Link>
      <div className="flex items-center gap-4">
        {NAV_ITEMS.map((item) => {
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
