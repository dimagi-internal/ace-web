import { Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Button } from "canopy-ui/ui";
import { createCanopySession } from "../canopy/api";
import { useCanopySessionsList } from "../canopy/useCanopySessionsList";
import { useCanopyStatus } from "../canopy/useCanopyStatus";
import { notifySessionsUpdated } from "../hooks/useRecentSessions";
import { relativeTime } from "../lib/relativeTime";

interface Props {
  /** Retained for callers still on the legacy `/chat/:slug` route shape
   *  (which now redirects — see router.tsx); always null going forward. */
  currentSlug: string | null;
  /** The active canopy session id, when the current route is
   *  `/w/:workspace/chat/c/:canopyId`. */
  currentCanopyId?: string | null;
}

/**
 * The chat sidebar — canopy-hosted sessions only. Ace-web's own interactive
 * chat UI (a "Legacy" section listing `apps.sessions.Session` rows, grouped
 * by opp) was retired here in favor of canopy-hosted chat; see the PR that
 * deleted `useSessionSocket`/`sessionReducer`/local `ChatPanel` and friends.
 * Past chats aren't gone from the database (Session/Message are still live
 * infrastructure for programmatic ACE runs — see apps/sessions/models.py's
 * docstring) — they're just not orderable/browsable as a chat list anymore;
 * `/sessions` (SessionsPage) still lists them read-only for uploaded/
 * imported transcripts.
 */
export function RecentSessionsSidebar({ currentCanopyId = null }: Props) {
  const { workspaceSlug } = useParams<{ workspaceSlug?: string }>();
  const canopyStatus = useCanopyStatus();
  const canopyEnabled = Boolean(canopyStatus?.enabled);
  const { sessions: canopySessions } = useCanopySessionsList(
    canopyEnabled ? canopyStatus!.base_url : null,
    workspaceSlug ?? "",
  );
  const navigate = useNavigate();
  const [newChatError, setNewChatError] = useState<string | null>(null);

  const handleNew = async () => {
    if (!workspaceSlug) return;
    setNewChatError(null);
    try {
      const s = await createCanopySession(workspaceSlug, {});
      notifySessionsUpdated();
      navigate(`/w/${workspaceSlug}/chat/c/${s.id}`);
    } catch (err) {
      setNewChatError(err instanceof Error ? err.message : "Could not start a new chat.");
    }
  };

  return (
    <aside className="flex w-64 flex-col border-r border-border bg-muted/30">
      <div className="p-3">
        <Button
          type="button"
          onClick={handleNew}
          className="w-full"
          size="sm"
          disabled={!canopyEnabled}
        >
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          New Chat
        </Button>
        {newChatError && (
          <p className="mt-1.5 text-xs text-destructive" role="alert">
            {newChatError}
          </p>
        )}
        {!canopyEnabled && (
          <p className="mt-1.5 text-xs text-muted-foreground">
            Chat is unreachable right now.
          </p>
        )}
      </div>
      <nav className="flex-1 overflow-y-auto px-2 pb-2">
        {canopySessions.length === 0 ? (
          <div className="px-2 py-4 text-sm text-muted-foreground">No chats yet.</div>
        ) : (
          canopySessions.map((s) => {
            const isActive = s.id === currentCanopyId;
            const href = workspaceSlug
              ? `/w/${workspaceSlug}/chat/c/${s.id}`
              : `/chat/c/${s.id}`;
            return (
              <Link
                key={s.id}
                to={href}
                className={`block rounded px-3 py-2 text-sm ${
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent"
                }`}
              >
                <div className="truncate font-medium">{s.title || "Untitled"}</div>
                <div className="truncate text-xs text-muted-foreground">
                  {relativeTime(s.updated_at)}
                </div>
              </Link>
            );
          })
        )}
      </nav>
      <Link
        to="/sessions"
        className="border-t border-border px-3 py-2 text-center text-xs text-muted-foreground hover:text-foreground"
      >
        View all sessions &rarr;
      </Link>
    </aside>
  );
}
