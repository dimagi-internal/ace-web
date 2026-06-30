import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ExternalLink, MessageSquare, Plus } from "lucide-react";

import { discussStep, getLinkedChats } from "../../api/opps";
import type { LinkedChat } from "../../api/types.ws";
import { Button } from "@marshellis/canopy-ui/ui";
import { ChatPanel } from "./ChatPanel";

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
 * The Workbench's right pane. Replaces the old in-step LinkedChats list
 * with a real, usable chat surface anchored to the selected step.
 *
 * Top section: list of chats linked to this opp+step (and a fallback
 * list of opp-wide chats — uploaded transcripts, the working session).
 * Selecting a chat slug populates the bottom section with a live
 * ChatPanel — same WS socket, same composer, same streaming as the
 * dedicated /chat/<slug> page.
 *
 * When no chats exist for the step, the bottom section shows a
 * "Start a chat about this step" CTA that calls the existing
 * /api/opps/<slug>/runs/<run>/steps/<skill>/discuss endpoint.
 */
export function WorkbenchChatPane({ slug, runId, skill, skillDisplayName }: Props) {
  const { workspaceSlug = "" } = useParams<{ workspaceSlug?: string }>();
  const navigate = useNavigate();
  const [chats, setChats] = useState<LinkedChat[] | null>(null);
  const [activeSlug, setActiveSlug] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    getLinkedChats(slug, runId, skill) // NOTE: no v2 endpoint; will fail loudly until backend ships it
      .then((list) => {
        setChats(list);
        // Auto-select the first step-scoped chat if nothing is selected.
        // We DON'T auto-select an opp-wide chat — those are off-topic for
        // a "talk about THIS step" interaction.
        setActiveSlug((prev) => {
          if (prev && list.some((c) => c.slug === prev)) return prev;
          const firstStep = list.find((c) => c.kind === "step");
          return firstStep?.slug ?? null;
        });
      })
      .catch(() => setChats([]));
  }, [slug, runId, skill]);

  useEffect(() => {
    setChats(null);
    setActiveSlug(null);
    refresh();
  }, [refresh]);

  const handleStart = async () => {
    setStarting(true);
    setStartError(null);
    try {
      const r = await discussStep(workspaceSlug, slug, runId, skill);
      // Seed-chat takes ~20s. The user needs to land on the new
      // session, not stare at a "Starting…" button. Navigate
      // immediately on 201; the destination page will load the
      // fresh transcript on its own.
      const dest = workspaceSlug
        ? `/w/${workspaceSlug}/chat/${r.session_slug}`
        : `/chat/${r.session_slug}`;
      navigate(dest);
    } catch (e) {
      setStartError(String((e as Error)?.message ?? e));
      setStarting(false);
    }
  };

  if (chats === null) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
        Loading chats…
      </div>
    );
  }

  const stepChats = chats.filter((c) => c.kind === "step");
  const oppChats = chats.filter((c) => c.kind === "opp");

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
          {chats.length}
        </span>
      </header>

      <ChatListSection
        title="For this step"
        chats={stepChats}
        activeSlug={activeSlug}
        onSelect={setActiveSlug}
        emptyHint={null}
      />

      {oppChats.length > 0 && (
        <ChatListSection
          title="Opp-wide"
          chats={oppChats}
          activeSlug={activeSlug}
          onSelect={setActiveSlug}
          emptyHint={null}
        />
      )}

      {!activeSlug && stepChats.length === 0 && (
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

      {activeSlug && (
        <div className="flex min-h-0 flex-1 flex-col border-t border-border">
          <div className="flex items-center justify-between border-b border-border bg-muted/40 px-3 py-1 text-[11px]">
            <span className="min-w-0 truncate text-muted-foreground" title={activeSlug}>
              Chatting in
              <span className="ml-1 truncate text-foreground">
                {chats.find((c) => c.slug === activeSlug)?.title || activeSlug}
              </span>
            </span>
            <Link
              to={
                workspaceSlug
                  ? `/w/${workspaceSlug}/chat/${activeSlug}`
                  : `/chat/${activeSlug}`
              }
              className="inline-flex shrink-0 items-center gap-1 text-muted-foreground hover:text-foreground"
              title="Open in dedicated chat page"
            >
              Open full
              <ExternalLink className="h-2.5 w-2.5" />
            </Link>
          </div>
          <div className="min-h-0 flex-1">
            <ChatPanel key={activeSlug} slug={activeSlug} workspaceSlug={workspaceSlug} />
          </div>
        </div>
      )}
    </div>
  );
}

interface ChatListProps {
  title: string;
  chats: LinkedChat[];
  activeSlug: string | null;
  onSelect: (slug: string) => void;
  emptyHint: string | null;
}

function ChatListSection({ title, chats, activeSlug, onSelect, emptyHint }: ChatListProps) {
  if (chats.length === 0 && !emptyHint) return null;
  return (
    <div className="border-b border-border">
      <div className="px-3 pt-2 text-[9px] uppercase tracking-wider text-muted-foreground/70">
        {title}
      </div>
      <ul className="px-1 pb-2 pt-1">
        {chats.length === 0 ? (
          <li className="px-2 py-1 text-[10px] text-muted-foreground">{emptyHint}</li>
        ) : (
          chats.map((c) => {
            const active = c.slug === activeSlug;
            return (
              <li key={c.slug}>
                <button
                  type="button"
                  onClick={() => onSelect(c.slug)}
                  className={
                    "block w-full rounded px-2 py-1.5 text-left text-[11px] transition " +
                    (active
                      ? "bg-primary/15 text-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground")
                  }
                >
                  <div className="flex items-center gap-1.5">
                    <span className="truncate flex-1">{c.title}</span>
                    {c.source === "upload" && (
                      <span
                        className="shrink-0 rounded bg-blue-500/15 px-1 text-[8px] font-medium uppercase tracking-wider text-blue-500"
                        title="Transcript uploaded via /ace:run --ace-web-url"
                      >
                        upload
                      </span>
                    )}
                    {c.kind === "opp" && c.step_skill && (
                      <span
                        className="shrink-0 rounded bg-muted px-1 text-[10px] text-muted-foreground"
                        title={`Scoped to step: ${c.step_skill_display || c.step_skill}`}
                      >
                        {c.step_skill_display || c.step_skill}
                      </span>
                    )}
                  </div>
                  {c.preview && (
                    <div className="truncate text-[10px] text-muted-foreground/70">
                      {c.preview}
                    </div>
                  )}
                </button>
              </li>
            );
          })
        )}
      </ul>
    </div>
  );
}
