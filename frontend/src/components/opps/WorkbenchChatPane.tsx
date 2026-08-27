import { useParams } from "react-router-dom";
import { ExternalLink, MessageSquare, Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { useState } from "react";

import { Button } from "canopy-ui/ui";
import { CanopyChatPanel } from "../../canopy/CanopyChatPanel";
import { createCanopySession } from "../../canopy/api";
import { useCanopySessionsList } from "../../canopy/useCanopySessionsList";
import { useCanopyStatus } from "../../canopy/useCanopyStatus";

interface Props {
  slug: string;
  runId: string;
  skill: string;
  // Human-readable name for the selected skill (e.g. "Idea to PDD"). The
  // chat-pane header used to show the bare slug ``idea-to-pdd``; this
  // prop comes from the parent's selectedStep.display_name.
  skillDisplayName?: string;
}

/**
 * The Workbench's right pane: chats about the selected step, backed by
 * canopy-hosted chat (a canopy Session seeded with `opp_slug`/`opp_run_id`/
 * `opp_step_skill`, so canopy's own session list can be filtered to "this
 * run"). Selecting a chat populates the bottom section with a live
 * `CanopyChatPanel`.
 *
 * Retired (see the chat-retirement PR): the legacy ace-web session path
 * (`getLinkedChats`/`discussStep`, local `ChatPanel`) — `getLinkedChats` had
 * no v2 endpoint and always rejected in production, so that list was already
 * permanently empty; `discussStep` seeded an ace-web `Session` for a human to
 * type into, a flow canopy's "Discuss this step" (`createCanopySession`
 * below) now covers end to end.
 */
export function WorkbenchChatPane({ slug, runId, skill, skillDisplayName }: Props) {
  const { workspaceSlug = "" } = useParams<{ workspaceSlug?: string }>();
  const canopyStatus = useCanopyStatus();
  const canopyEnabled = Boolean(canopyStatus?.enabled);
  const canopyBase = canopyStatus?.base_url ?? "";
  const { sessions: canopyChats, refresh: refreshCanopyChats } = useCanopySessionsList(
    canopyEnabled ? canopyBase : null,
    workspaceSlug,
    { opp_slug: slug, opp_run_id: runId },
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const activeId = selectedId ?? (canopyChats.length > 0 ? canopyChats[0].id : null);

  const handleStart = async () => {
    setStarting(true);
    setStartError(null);
    try {
      const s = await createCanopySession(workspaceSlug, {
        title: skillDisplayName || skill,
        opp_slug: slug,
        opp_run_id: runId,
        opp_step_skill: skill,
      });
      setSelectedId(s.id);
      refreshCanopyChats();
    } catch (e) {
      setStartError(String((e as Error)?.message ?? e));
    } finally {
      setStarting(false);
    }
  };

  if (!canopyEnabled) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-center text-xs text-muted-foreground">
        Chat isn't available right now — canopy chat is unreachable.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-border bg-card px-3 py-2">
        <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-foreground">
          Chats about{" "}
          <span className="text-primary" title={skill}>
            {skillDisplayName || skill}
          </span>
        </span>
        <span className="ml-auto rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
          {canopyChats.length}
        </span>
      </header>

      {canopyChats.length > 0 && (
        <div className="border-b border-border">
          <div className="px-3 pt-2 text-[9px] uppercase tracking-wider text-muted-foreground/70">
            This run
          </div>
          <ul className="px-1 pb-2 pt-1">
            {canopyChats.map((c) => {
              const active = c.id === activeId;
              return (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(c.id)}
                    className={
                      "block w-full rounded px-2 py-1.5 text-left text-[11px] transition " +
                      (active
                        ? "bg-primary/15 text-foreground"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground")
                    }
                  >
                    <span className="truncate">{c.title || "Untitled"}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {canopyChats.length === 0 && (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-4 py-6 text-center">
          <p className="text-xs text-muted-foreground">
            No chats about this step yet.
          </p>
          <Button size="sm" onClick={handleStart} disabled={starting}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            {starting ? "Starting…" : "Start a chat about this step"}
          </Button>
          {startError && (
            <p className="text-xs text-destructive" role="alert">
              {startError}
            </p>
          )}
        </div>
      )}

      {activeId && (
        <div className="flex min-h-0 flex-1 flex-col border-t border-border">
          <div className="flex items-center justify-between border-b border-border bg-muted/40 px-3 py-1 text-[11px]">
            <span className="min-w-0 truncate text-muted-foreground">
              Chatting in
              <span className="ml-1 truncate text-foreground">
                {canopyChats.find((c) => c.id === activeId)?.title || "Canopy chat"}
              </span>
            </span>
            <Link
              to={
                workspaceSlug
                  ? `/w/${workspaceSlug}/chat/c/${activeId}`
                  : `/chat/c/${activeId}`
              }
              className="inline-flex shrink-0 items-center gap-1 text-muted-foreground hover:text-foreground"
              title="Open in dedicated chat page"
            >
              Open full
              <ExternalLink className="h-2.5 w-2.5" />
            </Link>
          </div>
          <div className="min-h-0 flex-1">
            <CanopyChatPanel key={activeId} sessionId={activeId} />
          </div>
        </div>
      )}
    </div>
  );
}
