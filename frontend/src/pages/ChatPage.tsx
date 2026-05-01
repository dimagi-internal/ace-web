import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { createSession, getSession, updateSession } from "../api/sessions";
import type { Session } from "../api/types";
import { AddTeammateButton } from "../components/AddTeammateButton";
import { InlineTitleEdit } from "../components/InlineTitleEdit";
import { RecentSessionsSidebar } from "../components/RecentSessionsSidebar";
import { SharePopover } from "../components/SharePopover";
import { ChatPanel } from "../components/opps/ChatPanel";
import {
  SESSIONS_UPDATED_EVENT,
  notifySessionsUpdated,
} from "../hooks/useRecentSessions";

export function ChatPage() {
  const { slug = "" } = useParams();
  const [meta, setMeta] = useState<Session | null>(null);
  // Distinct from `meta == null` (loading) so the "session not found"
  // branch is reachable. Previously this page caught fetch errors with
  // setMeta(null), which collided with the initial loading state and
  // left the user on "Loading…" forever for any deleted-or-invalid slug.
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    setMeta(null);
    setLoadError(null);
    const load = () => {
      getSession(slug)
        .then((s) => {
          if (!cancelled) {
            setMeta(s);
            setLoadError(null);
          }
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          const detail = err instanceof Error ? err.message : String(err);
          setLoadError(detail || "session not found");
        });
    };
    load();
    const handler = () => load();
    window.addEventListener(SESSIONS_UPDATED_EVENT, handler);
    return () => {
      cancelled = true;
      window.removeEventListener(SESSIONS_UPDATED_EVENT, handler);
    };
  }, [slug]);

  const handleTitleSave = async (newTitle: string) => {
    if (!meta) return;
    const updated = await updateSession(slug, { title: newTitle });
    setMeta({ ...meta, title: updated.title });
    notifySessionsUpdated();
  };

  if (loadError) {
    return <ChatNotFound slug={slug} detail={loadError} />;
  }

  if (!meta) {
    return <div className="p-4 text-muted-foreground">Loading…</div>;
  }

  return (
    <div className="flex h-full bg-background text-foreground">
      <RecentSessionsSidebar currentSlug={slug} />
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border bg-background px-4 py-2">
          <InlineTitleEdit value={meta.title} onSave={handleTitleSave} />
          <div className="relative flex items-center gap-3">
            <AddTeammateButton slug={slug} />
            <SharePopover slug={slug} />
          </div>
        </header>
        <div className="flex-1 overflow-hidden">
          <ChatPanel key={slug} slug={slug} />
        </div>
      </div>
    </div>
  );
}

function ChatNotFound({ slug, detail }: { slug: string; detail: string }) {
  const navigate = useNavigate();
  // Read workspace slug straight from the URL — same approach as
  // useWorkspace.ts. Lives in the URL kwarg `:workspaceSlug` for any
  // path under `/w/:workspaceSlug/...`.
  const { workspaceSlug } = useParams<{ workspaceSlug?: string }>();
  const sessionsHref = workspaceSlug
    ? `/w/${workspaceSlug}/sessions`
    : "/sessions";

  const handleNew = async () => {
    const s = await createSession();
    notifySessionsUpdated();
    const path = workspaceSlug
      ? `/w/${workspaceSlug}/chat/${s.slug}`
      : `/chat/${s.slug}`;
    navigate(path, { replace: true });
  };

  return (
    <div className="flex h-full bg-background text-foreground">
      <RecentSessionsSidebar currentSlug={slug} />
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="max-w-md text-center">
          <h1 className="mb-2 text-xl font-semibold">This chat isn't here</h1>
          <p className="mb-6 text-sm text-muted-foreground">
            We couldn't load <code className="rounded bg-muted px-1 py-0.5 text-xs">{slug}</code>.
            It may have been deleted, or the link is wrong.
          </p>
          <p className="mb-6 text-xs text-muted-foreground/80" aria-live="polite">
            {detail}
          </p>
          <div className="flex items-center justify-center gap-2">
            <Button type="button" onClick={handleNew}>
              Start a new chat
            </Button>
            <Button asChild type="button" variant="outline">
              <Link to={sessionsHref}>View all chats</Link>
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
