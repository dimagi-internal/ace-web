import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ListTree } from "lucide-react";

import { Button } from "@/components/ui/button";
import { createSession, getSession, updateSession } from "../api/sessions";
import type { Session } from "../api/types.ws";
import { AddTeammateButton } from "../components/AddTeammateButton";
import { InlineTitleEdit } from "../components/InlineTitleEdit";
import { OppHeaderBreadcrumb } from "../components/OppHeaderBreadcrumb";
import { RecentSessionsSidebar } from "../components/RecentSessionsSidebar";
import { SharePopover } from "../components/SharePopover";
import { ChatPanel } from "../components/opps/ChatPanel";
import {
  SESSIONS_UPDATED_EVENT,
  notifySessionsUpdated,
} from "../hooks/useRecentSessions";

export function ChatPage() {
  const { slug = "", workspaceSlug = "" } = useParams<{
    slug: string;
    workspaceSlug: string;
  }>();
  const navigate = useNavigate();
  const [meta, setMeta] = useState<Session | null>(null);
  // Distinct from `meta == null` (loading) so the "session not found"
  // branch is reachable. Previously this page caught fetch errors with
  // setMeta(null), which collided with the initial loading state and
  // left the user on "Loading…" forever for any deleted-or-invalid slug.
  const [loadError, setLoadError] = useState<string | null>(null);

  // Back-compat redirect: an earlier iteration of the Structure feature used
  // a `#structure` hash on the chat URL to auto-open an embedded panel. The
  // panel was promoted to a dedicated /chat/<slug>/structure page in PR #299;
  // any saved links with the hash should land on that page directly.
  useEffect(() => {
    if (
      slug &&
      workspaceSlug &&
      typeof window !== "undefined" &&
      window.location.hash === "#structure"
    ) {
      navigate(`/w/${workspaceSlug}/chat/${slug}/structure`, { replace: true });
    }
  }, [slug, workspaceSlug, navigate]);

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
          <div className="flex flex-col gap-0.5">
            <OppHeaderBreadcrumb
              oppSlug={meta.opp_slug}
              oppRunId={meta.opp_run_id}
              oppStepSkill={meta.opp_step_skill}
              oppDisplayName={meta.opp_display_name}
              oppStepSkillDisplay={meta.opp_step_skill_display}
            />
            <InlineTitleEdit value={meta.title} onSave={handleTitleSave} />
          </div>
          <div className="relative flex items-center gap-3">
            <Link
              to={`/w/${workspaceSlug}/chat/${slug}/structure`}
              className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
              title="View hierarchical breakdown of this session"
            >
              <ListTree className="h-4 w-4" />
              Structure
            </Link>
            <AddTeammateButton slug={slug} />
            <SharePopover slug={slug} workspaceSlug={workspaceSlug} />
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
            <Link
              to={sessionsHref}
              className="inline-flex h-8 items-center justify-center rounded-lg border border-border bg-background px-2.5 text-sm font-medium text-foreground transition-colors hover:bg-muted"
            >
              View all chats
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
