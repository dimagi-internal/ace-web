import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown, LayoutDashboard, LogOut, Settings, User } from "lucide-react";

import { getCurrentUser, type CurrentUser } from "@/api/auth";
import { ThemeToggle } from "@/components/ThemeToggle";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "canopy-ui/ui";

/**
 * Top-right account menu. Surfaces the signed-in identity so users can
 * tell which Connect account they're authenticated as without having
 * to navigate to /welcome — and gives them a one-click sign-out when
 * they realize they're on the wrong one.
 *
 * Renders the account email next to a chevron, with the menu offering
 * System Overview → Settings → Theme → Sign out.
 */
export function UserMenu() {
  const navigate = useNavigate();
  const [me, setMe] = useState<CurrentUser | null>(null);

  useEffect(() => {
    getCurrentUser()
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="flex items-center gap-1.5 rounded border border-input
          bg-card px-2 py-1 text-xs text-foreground hover:border-primary/60"
        title={me ? `Signed in as ${me.email}` : "Account menu"}
        aria-label="Open account menu"
      >
        <span
          className="flex h-5 w-5 shrink-0 items-center justify-center
            rounded-full bg-primary/15 text-[10px] font-semibold text-primary"
          aria-hidden
        >
          {avatarLetters(me)}
        </span>
        <span className="hidden max-w-[14rem] truncate sm:inline">
          {me?.email ?? "Account"}
        </span>
        <ChevronDown className="h-3 w-3 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="flex items-center gap-2 py-2">
          <User className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs font-medium text-foreground">
              {me?.display_name || me?.email || "Not signed in"}
            </span>
            {me?.email && me.email !== me.display_name && (
              <span className="block truncate text-[10px] font-normal text-muted-foreground">
                {me.email}
              </span>
            )}
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onClick={() => navigate("/system")}
          className="gap-2"
        >
          <LayoutDashboard className="h-3.5 w-3.5" />
          System Overview
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => navigate("/settings")}
          className="gap-2"
        >
          <Settings className="h-3.5 w-3.5" />
          Settings
        </DropdownMenuItem>
        <div className="flex items-center justify-between px-2 py-1.5 text-xs">
          <span className="text-muted-foreground">Theme</span>
          <ThemeToggle />
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          // Plain navigation, not React Router — /auth/logout/ is a
          // Django view that needs a real GET to clear the session.
          onClick={() => {
            window.location.href = "/ace/auth/logout/";
          }}
          className="gap-2 text-rose-500 focus:text-rose-500"
        >
          <LogOut className="h-3.5 w-3.5" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function avatarLetters(me: CurrentUser | null): string {
  if (!me) return "?";
  const source = (me.display_name || me.email || "").trim();
  if (!source) return "?";
  // Prefer initials of a multi-word display name; fall back to the
  // first letter of the email local-part.
  const words = source.split(/[\s_]+/).filter(Boolean);
  if (words.length >= 2) {
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  return source[0].toUpperCase();
}
