import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { CanopyChatPanel } from "../canopy/CanopyChatPanel";
import { getCanopySession } from "../canopy/api";
import { useCanopyStatus, useCanopyStatusFailed } from "../canopy/useCanopyStatus";
import { RecentSessionsSidebar } from "../components/RecentSessionsSidebar";
import { SESSIONS_UPDATED_EVENT } from "../hooks/useRecentSessions";

/**
 * Chat, canopy-hosted — the `/w/:workspaceSlug/chat/c/:canopyId` route.
 *
 * Ace-web's own interactive chat page (WebSocket-driven, `apps.sessions`
 * backed) was retired here; canopy-hosted chat is now simply "the chat", not
 * one branch of a flag. `useCanopyStatus` stays wired up because a
 * disabled/unreachable canopy must degrade visibly (see below) rather than
 * try to render a page with nothing behind it.
 *
 * Title comes from the single-session detail endpoint (`getCanopySession`),
 * refreshed on `session.title_updated` via the same `SESSIONS_UPDATED_EVENT`
 * bus every other session list already listens on.
 */
export function CanopyChatRoutePage() {
  const { canopyId = "" } = useParams<{
    canopyId: string;
    workspaceSlug: string;
  }>();
  const status = useCanopyStatus();
  // useCanopyStatus() alone can't tell "still loading" apart from "the one
  // status fetch failed" (both are `null`) — without this the page would
  // render "Loading…" forever on a status blip, with no way out short of a
  // manual reload.
  const statusFailed = useCanopyStatusFailed();
  const enabled = status?.enabled ?? false;
  const base = status?.base_url ?? "";
  const [title, setTitle] = useState<string>("");

  useEffect(() => {
    if (!status || !enabled || !canopyId) return;
    let cancelled = false;
    const load = () => {
      getCanopySession(base, canopyId)
        .then((detail) => {
          if (!cancelled) setTitle(detail.title);
        })
        .catch(() => {
          /* non-fatal: the header just shows a blank/stale title */
        });
    };
    load();
    window.addEventListener(SESSIONS_UPDATED_EVENT, load);
    return () => {
      cancelled = true;
      window.removeEventListener(SESSIONS_UPDATED_EVENT, load);
    };
  }, [status, enabled, base, canopyId]);

  if (statusFailed) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-sm text-destructive">
        Couldn't reach canopy chat. Check your connection and reload the page.
      </div>
    );
  }

  if (status && !enabled) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-sm text-muted-foreground">
        Chat is unavailable right now — canopy chat isn't enabled for this
        deployment.
      </div>
    );
  }

  return (
    <div className="flex h-full bg-background text-foreground">
      <RecentSessionsSidebar currentSlug={null} currentCanopyId={canopyId} />
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border bg-background px-4 py-2">
          <h1 className="truncate text-sm font-semibold text-foreground">
            {status ? title.trim() || "Chat" : "Loading…"}
          </h1>
        </header>
        <div className="flex-1 overflow-hidden">
          {status ? (
            <CanopyChatPanel key={canopyId} sessionId={canopyId} />
          ) : (
            <div className="flex h-full items-center justify-center p-8 text-sm text-muted-foreground">
              Loading…
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
