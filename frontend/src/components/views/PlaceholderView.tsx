import { Construction } from "lucide-react";

interface Props {
  /** Which view-mode shows this placeholder. */
  kind: "flow" | "timeline";
}

/**
 * Stub for Phase-2-onward view modes. Phase 1 ships only the
 * Hierarchy view as fully built; this preserves the switcher's
 * shape so users can SEE that other modes are coming and the URL
 * (`?view=flow`) is bookmarkable from day one.
 *
 * Replace per-phase as TimelineView.tsx and FlowView.tsx land.
 */
export function PlaceholderView({ kind }: Props) {
  const copy: Record<typeof kind, { title: string; body: string }> = {
    flow: {
      title: "Flow view",
      body: "A per-opp DAG showing chat → artifact → verdict → next chat. Ships next sprint, after the run-formalization work lands. The tab is here so the URL (?view=flow) is shareable from day one.",
    },
    timeline: {
      title: "Timeline view",
      body: "A workspace-wide activity feed: chats, artifacts, verdicts, gates — chronological, filterable by opp and event type. Ships next sprint.",
    },
  };
  const { title, body } = copy[kind];

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-6 py-16 text-center">
      <Construction className="mb-4 h-10 w-10 text-muted-foreground/60" />
      <h2 className="text-lg font-semibold text-foreground">{title}</h2>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">{body}</p>
    </div>
  );
}
