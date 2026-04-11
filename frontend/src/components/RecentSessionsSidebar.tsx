import { Plus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { createSession } from "../api/sessions";
import { useRecentSessions } from "../hooks/useRecentSessions";

interface Props {
  currentSlug: string | null;
}

export function RecentSessionsSidebar({ currentSlug }: Props) {
  const { sessions, refresh } = useRecentSessions(10);
  const navigate = useNavigate();

  const handleNew = async () => {
    const s = await createSession();
    await refresh();
    navigate(`/chat/${s.slug}`);
  };

  return (
    <aside className="flex w-64 flex-col border-r border-border bg-muted/30">
      <div className="p-3">
        <Button
          type="button"
          onClick={handleNew}
          className="w-full"
          size="sm"
        >
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          New Chat
        </Button>
      </div>
      <nav className="flex-1 overflow-y-auto px-2">
        {sessions.length === 0 && (
          <div className="px-2 py-4 text-sm text-muted-foreground">No chats yet.</div>
        )}
        {sessions.map((s) => {
          const isActive = s.slug === currentSlug;
          return (
            <Link
              key={s.slug}
              to={`/chat/${s.slug}`}
              className={`block rounded px-3 py-2 text-sm ${
                isActive
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent"
              }`}
            >
              <div className="truncate font-medium">
                {s.title || "Untitled"}
              </div>
              <div className="truncate text-xs text-muted-foreground">
                {new Date(s.updated_at).toLocaleString()}
              </div>
            </Link>
          );
        })}
      </nav>
      <Link
        to="/library"
        className="border-t border-border px-3 py-2 text-center text-xs text-muted-foreground hover:text-foreground"
      >
        View all sessions &rarr;
      </Link>
    </aside>
  );
}
