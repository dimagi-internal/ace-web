import { useEffect, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";

import { createCanopySession } from "../canopy/api";
import { useCanopyStatus } from "../canopy/useCanopyStatus";

/**
 * Bare `/w/:workspaceSlug/chat` — "chat home". Creates a fresh canopy
 * session and redirects to it, same UX as the retired ace-web-native
 * `createSession` version of this page (see the chat-retirement PR).
 */
export function ChatRedirectPage() {
  const navigate = useNavigate();
  const { workspaceSlug = "" } = useParams<{ workspaceSlug?: string }>();
  const status = useCanopyStatus();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!workspaceSlug || !status) return;
    if (!status.enabled) {
      setError("Chat is unavailable right now — canopy chat isn't enabled for this deployment.");
      return;
    }
    createCanopySession(workspaceSlug, {})
      .then((s) => {
        navigate(`/w/${workspaceSlug}/chat/c/${s.id}`, { replace: true });
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Could not start a new chat.");
      });
  }, [navigate, workspaceSlug, status]);

  if (error) {
    return <div className="p-4 text-sm text-destructive">{error}</div>;
  }
  return <div className="p-4 text-muted-foreground">Starting a new chat…</div>;
}

/**
 * `/w/:workspaceSlug/chat/:slug` — a bookmarked/linked-from-elsewhere URL
 * for the retired interactive ace-web-native chat page. Bounces to chat
 * home (`ChatRedirectPage` above), which starts a fresh canopy session,
 * rather than 404ing. An absolute redirect (not a relative `Navigate
 * to=".."`) so it can't be misresolved by route-nesting depth.
 */
export function LegacyChatSlugRedirect() {
  const { workspaceSlug = "" } = useParams<{ workspaceSlug?: string }>();
  return <Navigate to={workspaceSlug ? `/w/${workspaceSlug}/chat` : "/chat"} replace />;
}
