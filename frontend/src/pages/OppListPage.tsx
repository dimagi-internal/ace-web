import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { ArrowDownUp, Plus, X } from "lucide-react";

import { listOpps } from "../api/opps";
import { ApiError } from "../api/client";
import type { OppCard } from "../api/types.ws";
import { EmptyState, ErrorState, LoadingSpinner } from "../components/opps/LoadingStates";
import { CompareWithDialog } from "../components/opps/CompareWithDialog";
import { DeleteOppDialog } from "../components/opps/DeleteOppDialog";
import { NewOppDialog } from "../components/opps/NewOppDialog";
import { OppCardItem } from "../components/opps/OppCard";
import { TimelineView } from "../components/views/TimelineView";
import { ViewSwitcher, type ViewTab } from "../components/views/ViewSwitcher";
import { useViewMode } from "../hooks/useViewMode";
import { sortOpps, SORT_OPTIONS, type SortKey } from "../lib/sortOpps";
import { Button } from "canopy-ui/ui";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string; code: string | null }
  | { kind: "loaded"; opps: OppCard[] };

// Workspace-wide view tabs. Hierarchy is the default; Timeline ships
// in a follow-up sprint.
const VIEW_TABS: ViewTab[] = [
  { kind: "hierarchy", label: "Hierarchy" },
  { kind: "timeline", label: "Timeline" },
];

export default function OppListPage() {
  const { workspaceSlug = "" } = useParams<{ workspaceSlug?: string }>();
  const { view, setView } = useViewMode("hierarchy");
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [filter, setFilter] = useState("");
  const [tagFilter, setTagFilter] = useState<string[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>("recent");
  const [newDialogOpen, setNewDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<OppCard | null>(null);
  const [compareSource, setCompareSource] = useState<OppCard | null>(null);
  // Per-opp expansion state for the Hierarchy view's chat-children. Lives
  // in component state (not URL) — bookmarking a specific expanded
  // opp would be over-engineered for v1; users re-expand on visit.
  const [expandedOpps, setExpandedOpps] = useState<Set<string>>(new Set());

  const toggleExpanded = (slug: string) => {
    setExpandedOpps((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  };

  const load = useCallback(() => {
    setState({ kind: "loading" });
    listOpps(workspaceSlug, tagFilter.length > 0 ? tagFilter : undefined)
      .then((opps) => setState({ kind: "loaded", opps }))
      .catch((err) =>
        setState({
          kind: "error",
          message: String(err?.message ?? err),
          code: err instanceof ApiError ? err.code : null,
        }),
      );
  }, [workspaceSlug, tagFilter]);

  useEffect(load, [load]);

  const allOpps = state.kind === "loaded" ? state.opps : [];

  const visibleOpps = useMemo(() => {
    if (state.kind !== "loaded") return [];
    let out = state.opps;
    const needle = filter.trim().toLowerCase();
    if (needle) {
      out = out.filter(
        (o) =>
          o.slug.toLowerCase().includes(needle) ||
          o.display_name.toLowerCase().includes(needle) ||
          o.tags.some((t) => t.toLowerCase().includes(needle)) ||
          o.labels.some((l) => l.toLowerCase().includes(needle)),
      );
    }
    return sortOpps(out, sortKey);
  }, [state, filter, sortKey]);

  const toggleTagFilter = (tag: string) => {
    setTagFilter((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  };

  // Only the Hierarchy view depends on the opp list; Timeline and Flow
  // render their own data and shouldn't be gated on Drive listing
  // 18 opps (a 30+ second cold-cache hit). For non-hierarchy views,
  // fall through and render the page chrome + body immediately.
  if (view === "hierarchy") {
    if (state.kind === "loading")
      return <LoadingSpinner label="Loading opportunities…" />;
    if (state.kind === "error")
      return <ErrorState message={state.message} code={state.code} onRetry={load} />;
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-border bg-card px-6 py-4">
        <h1 className="text-xl font-semibold text-foreground">Opportunities</h1>
        <span className="text-sm text-muted-foreground">
          {state.kind === "loaded" ? `${state.opps.length} total` : "loading…"}
        </span>

        {tagFilter.length > 0 && (
          <div className="flex items-center gap-1 text-xs">
            <span className="text-muted-foreground">tag filter:</span>
            {tagFilter.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => toggleTagFilter(t)}
                className="flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-primary hover:bg-primary/20"
              >
                {t}
                <X className="h-3 w-3" />
              </button>
            ))}
            <button
              type="button"
              onClick={() => setTagFilter([])}
              className="text-muted-foreground underline hover:text-foreground"
            >
              clear
            </button>
          </div>
        )}

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <ArrowDownUp className="h-3.5 w-3.5" />
            Sort by
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              className="rounded border border-input bg-card px-2 py-1 text-xs text-foreground focus:border-ring focus:outline-none"
              aria-label="Sort opportunities"
              title={SORT_OPTIONS.find((o) => o.key === sortKey)?.title}
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.key} value={o.key} title={o.title}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <input
            type="text"
            placeholder="Filter by name or tag…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="w-64 rounded border border-input bg-card px-3 py-1 text-sm text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none"
            aria-label="Filter opportunities by name, tag, or ID"
            title="Matches anywhere in the opp's name, tags, labels, or ID"
          />
          <Button size="sm" onClick={() => setNewDialogOpen(true)}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            New Opp
          </Button>
        </div>
      </header>
      <ViewSwitcher current={view} tabs={VIEW_TABS} onChange={setView} />
      <NewOppDialog open={newDialogOpen} onOpenChange={setNewDialogOpen} workspaceSlug={workspaceSlug} />
      {deleteTarget && (
        <DeleteOppDialog
          open={true}
          onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
          workspaceSlug={workspaceSlug}
          slug={deleteTarget.slug}
          displayName={deleteTarget.display_name}
          onDeleted={() => {
            setDeleteTarget(null);
            load();
          }}
        />
      )}
      {compareSource && (
        <CompareWithDialog
          open={true}
          onOpenChange={(v) => { if (!v) setCompareSource(null); }}
          source={compareSource}
          candidates={allOpps}
        />
      )}

      {view === "timeline" && (
        <div className="min-h-0 flex-1">
          <TimelineView />
        </div>
      )}
      {view === "hierarchy" && (visibleOpps.length === 0 ? (
        filter ? (
          <EmptyState
            title="No opps match your filter"
            description="Try a different name or tag."
          />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 py-16 text-center">
            <div>
              <h2 className="text-lg font-semibold text-foreground">
                No opportunities yet
              </h2>
              <p className="mt-1 max-w-md text-sm text-muted-foreground">
                Create your first opp to start an ACE cycle in this workspace.
              </p>
            </div>
            <Button onClick={() => setNewDialogOpen(true)}>
              <Plus className="mr-1.5 h-4 w-4" />
              Create your first opp
            </Button>
          </div>
        )
      ) : (
        <div className="grid grid-cols-1 items-start gap-3 p-6 md:grid-cols-2 xl:grid-cols-3">
          {visibleOpps.map((opp) => (
            <OppCardItem
              key={opp.slug}
              opp={opp}
              workspaceSlug={workspaceSlug}
              isExpanded={expandedOpps.has(opp.slug)}
              tagFilter={tagFilter}
              canCompare={allOpps.length >= 2}
              onToggleExpanded={toggleExpanded}
              onToggleTag={toggleTagFilter}
              onRequestDelete={setDeleteTarget}
              onRequestCompare={setCompareSource}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
