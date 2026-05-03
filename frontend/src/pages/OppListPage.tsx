import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertCircle, ArrowDownUp, ChevronDown, ChevronRight, GitCompareArrows, Plus, Trash2, X } from "lucide-react";

import { listOpps } from "../api/opps";
import type { OppCard } from "../api/types";
import { EmptyState, ErrorState, LoadingSpinner } from "../components/opps/LoadingStates";
import { CompareWithDialog } from "../components/opps/CompareWithDialog";
import { DeleteOppDialog } from "../components/opps/DeleteOppDialog";
import { NewOppDialog } from "../components/opps/NewOppDialog";
import { OppChatChildren } from "../components/views/hierarchy/OppChatChildren";
import { PlaceholderView } from "../components/views/PlaceholderView";
import { ViewSwitcher, type ViewTab } from "../components/views/ViewSwitcher";
import { useViewMode } from "../hooks/useViewMode";
import { relativeTime } from "../lib/relativeTime";
import { Button } from "@/components/ui/button";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; opps: OppCard[] };

type SortKey = "recent" | "score" | "status" | "slug";

const SORT_LABELS: Record<SortKey, string> = {
  recent: "Last activity",
  score: "Score (high → low)",
  status: "Status",
  slug: "Slug (A → Z)",
};

// We rank opps the user is most likely to need to look at first:
// load failures, then opps with no state.yaml, then opps with undecided gates,
// then everything else.
const STATUS_RANK: Record<string, number> = {
  error: 0,
  "no-state": 1,
  ok: 2,
};

// Workspace-wide view tabs. Flow is disabled at this scope — it's per-opp
// only — but rendered so users can SEE that other modes exist; clicking
// it shows a tooltip explaining why it's not active here. Hierarchy is
// the default; Timeline ships in a follow-up sprint.
const VIEW_TABS: ViewTab[] = [
  { kind: "hierarchy", label: "Hierarchy" },
  {
    kind: "flow",
    label: "Flow",
    disabled: true,
    disabledReason: "Open an opp to see its flow view",
  },
  { kind: "timeline", label: "Timeline" },
];

export default function OppListPage() {
  const { workspaceSlug = "" } = useParams<{ workspaceSlug?: string }>();
  const { view, setView } = useViewMode("hierarchy");
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [filter, setFilter] = useState("");
  const [tagFilter, setTagFilter] = useState<string[]>([]);
  const [needsReviewOnly, setNeedsReviewOnly] = useState(false);
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
    listOpps(tagFilter.length > 0 ? tagFilter : undefined)
      .then((opps) => setState({ kind: "loaded", opps }))
      .catch((err) => setState({ kind: "error", message: String(err?.message ?? err) }));
  }, [tagFilter]);

  useEffect(load, [load]);

  const allOpps = state.kind === "loaded" ? state.opps : [];
  const needsReviewCount = useMemo(
    () => allOpps.filter((o) => (o.pending_gates ?? []).length > 0).length,
    [allOpps],
  );

  const visibleOpps = useMemo(() => {
    if (state.kind !== "loaded") return [];
    let out = state.opps;
    if (needsReviewOnly) {
      out = out.filter((o) => (o.pending_gates ?? []).length > 0);
    }
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
  }, [state, filter, sortKey, needsReviewOnly]);

  const toggleTagFilter = (tag: string) => {
    setTagFilter((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  };

  if (state.kind === "loading") return <LoadingSpinner label="Loading opportunities…" />;
  if (state.kind === "error") return <ErrorState message={state.message} onRetry={load} />;

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-border bg-card px-6 py-4">
        <h1 className="text-xl font-semibold text-foreground">Opportunities</h1>
        <span className="text-sm text-muted-foreground">{state.opps.length} total</span>

        {needsReviewCount > 0 && (
          <button
            type="button"
            aria-pressed={needsReviewOnly}
            onClick={() => setNeedsReviewOnly((v) => !v)}
            className={
              "flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition " +
              (needsReviewOnly
                ? "bg-amber-500 text-amber-950 hover:bg-amber-400"
                : "bg-amber-500/15 text-amber-300 hover:bg-amber-500/25")
            }
            title={
              needsReviewOnly
                ? "Clear filter"
                : "Show only opps with gate briefs that have no decision recorded"
            }
          >
            <AlertCircle className="h-3.5 w-3.5" />
            Undecided gates ({needsReviewCount})
            {needsReviewOnly && <X className="h-3 w-3" />}
          </button>
        )}

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
            >
              {(Object.keys(SORT_LABELS) as SortKey[]).map((k) => (
                <option key={k} value={k}>{SORT_LABELS[k]}</option>
              ))}
            </select>
          </label>
          <input
            type="text"
            placeholder="Filter by slug, name, tag…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="w-64 rounded border border-input bg-card px-3 py-1 text-sm text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none"
          />
          <Button size="sm" onClick={() => setNewDialogOpen(true)}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            New Opp
          </Button>
        </div>
      </header>
      <ViewSwitcher current={view} tabs={VIEW_TABS} onChange={setView} />
      <NewOppDialog open={newDialogOpen} onOpenChange={setNewDialogOpen} />
      {deleteTarget && (
        <DeleteOppDialog
          open={true}
          onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
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

      {view === "timeline" && <PlaceholderView kind="timeline" />}
      {view === "flow" && <PlaceholderView kind="flow" />}
      {view === "hierarchy" && (visibleOpps.length === 0 ? (
        filter || needsReviewOnly ? (
          <EmptyState
            title={
              needsReviewOnly
                ? "No opps with undecided gates"
                : "No opps match your filter"
            }
            description={
              needsReviewOnly
                ? "Every gate brief has a decision recorded."
                : "Try a different search term."
            }
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
        <div className="grid grid-cols-1 gap-3 p-6 md:grid-cols-2 xl:grid-cols-3">
          {visibleOpps.map((opp) => {
            const isExpanded = expandedOpps.has(opp.slug);
            return (
            <div key={opp.slug} className="overflow-hidden rounded border border-border bg-card transition hover:border-primary">
            <Link
              to={`/opps/${opp.slug}`}
              className="group block p-4"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-start gap-1.5">
                  <button
                    type="button"
                    aria-label={isExpanded ? `Collapse ${opp.slug} chats` : `Show chats linked to ${opp.slug}`}
                    title={isExpanded ? "Hide linked chats" : "Show linked chats"}
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      toggleExpanded(opp.slug);
                    }}
                    className="mt-0.5 shrink-0 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    {isExpanded ? (
                      <ChevronDown className="h-3.5 w-3.5" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5" />
                    )}
                  </button>
                  <div className="min-w-0">
                    <h2 className="truncate font-semibold text-foreground group-hover:text-primary">
                      {opp.display_name || opp.slug}
                    </h2>
                    <div className="truncate text-xs text-muted-foreground">{opp.slug}</div>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <button
                    type="button"
                    aria-label={`Compare ${opp.slug} with another opp`}
                    title="Compare with another opp"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setCompareSource(opp);
                    }}
                    disabled={allOpps.length < 2}
                    className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded text-muted-foreground hover:bg-primary/10 hover:text-primary disabled:cursor-not-allowed disabled:opacity-30"
                  >
                    <GitCompareArrows className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete ${opp.slug}`}
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setDeleteTarget(opp);
                    }}
                    className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                  <StatusBadge status={opp.status} />
                </div>
              </div>

              {opp.eval_score !== null && opp.eval_score !== undefined && (
                <div className="mt-2">
                  <ScoreChip score={opp.eval_score} passed={opp.eval_passed} />
                </div>
              )}

              {/* Last observed position in the cycle, per state.yaml.
                  The plugin writes current_phase / current_step on every
                  step transition; we don't claim "running" because we
                  have no live process signal — the plugin may have
                  exited hours ago. */}
              {opp.current_step ? (
                <div className="mt-3 text-sm">
                  <span className="text-muted-foreground">Last step:</span>{" "}
                  <span className="font-mono text-foreground">{opp.current_step}</span>
                  {opp.current_phase && (
                    <span className="ml-2 text-xs text-muted-foreground">
                      ({opp.current_phase})
                    </span>
                  )}
                </div>
              ) : opp.status === "no-state" ? (
                <div className="mt-3 text-sm text-muted-foreground">
                  No <span className="font-mono">state.yaml</span> in this folder yet.
                </div>
              ) : null}

              {opp.last_activity_at && (
                <div className="mt-1 text-xs text-muted-foreground">
                  Last update: {relativeTime(opp.last_activity_at)}
                </div>
              )}

              {/* "Gate brief written, no decision recorded in state.yaml's
                  gates: map." We deliberately don't say "awaiting review" —
                  we don't know whether a human looked already and just
                  didn't record a decision. */}
              {(opp.pending_gates ?? []).length > 0 && (
                <div className="mt-2 flex items-start gap-1.5 text-xs text-amber-300">
                  <span className="mt-1 inline-block h-2 w-2 shrink-0 rounded-full bg-amber-400" />
                  <span className="min-w-0">
                    <span className="font-medium">
                      {(opp.pending_gates ?? []).length === 1
                        ? "Gate without decision:"
                        : "Gates without decisions:"}
                    </span>{" "}
                    <span className="truncate font-mono text-amber-200">
                      {(opp.pending_gates ?? []).join(", ")}
                    </span>
                  </span>
                </div>
              )}
              {(opp.tags.length > 0 || opp.labels.length > 0) && (
                <div className="mt-3 flex flex-wrap gap-1">
                  {opp.tags.map((tag) => (
                    <button
                      key={`tag-${tag}`}
                      type="button"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        toggleTagFilter(tag);
                      }}
                      className={
                        "rounded-full px-2 py-0.5 text-xs transition " +
                        (tagFilter.includes(tag)
                          ? "bg-primary text-primary-foreground"
                          : "bg-primary/10 text-primary hover:bg-primary/20")
                      }
                      title={tagFilter.includes(tag) ? "Remove tag filter" : "Filter by this tag"}
                    >
                      {tag}
                    </button>
                  ))}
                  {opp.labels.map((label) => (
                    <span
                      key={`label-${label}`}
                      className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                    >
                      {label}
                    </span>
                  ))}
                </div>
              )}
            </Link>
            {isExpanded && workspaceSlug && (
              <OppChatChildren oppSlug={opp.slug} workspaceSlug={workspaceSlug} />
            )}
            </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

// Only the unhappy paths get a pill. The common case (state.yaml present
// and parsable) is silent — we used to render a blue "running" pill here,
// but ace-web has no live process signal, so claiming the cycle is
// running was wishful thinking. Better to show nothing than to lie.
function StatusBadge({ status }: { status: string }) {
  if (status === "ok") return null;
  if (status === "no-state") {
    return (
      <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
        no state.yaml
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="rounded bg-red-900 px-2 py-0.5 text-xs text-red-300">
        load error
      </span>
    );
  }
  return (
    <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
      {status}
    </span>
  );
}

function ScoreChip({ score, passed }: { score: number; passed: boolean | null }) {
  // Match ScorecardPanel.tsx's convention: plugin scores are usually 0-100,
  // some opps land 0-10 — branch on the value, never assume scale.
  const scoreLabel = score > 10 ? `${score.toFixed(0)}/100` : `${score.toFixed(1)}/10`;
  const tone =
    passed === true
      ? "bg-emerald-900/60 text-emerald-200 border-emerald-700"
      : passed === false
        ? "bg-red-900/60 text-red-200 border-red-700"
        : "bg-muted text-muted-foreground border-border";
  const glyph = passed === true ? "✓" : passed === false ? "✕" : "·";
  const label =
    passed === true ? "passed" : passed === false ? "failed" : "scored";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium ${tone}`}
      title={`opp-eval ${label}: ${scoreLabel}`}
    >
      <span aria-hidden="true">{glyph}</span>
      <span>{scoreLabel}</span>
      <span className="opacity-70">opp-eval {label}</span>
    </span>
  );
}

function sortOpps(opps: OppCard[], key: SortKey): OppCard[] {
  const out = [...opps];
  switch (key) {
    case "recent":
      // "Last activity" = state.yaml's Drive modifiedTime (best cheap proxy
      // for "anything moved here"). Falls back to created_at when the opp
      // has no state.yaml yet.
      out.sort((a, b) => {
        const at = a.last_activity_at ?? a.created_at ?? "";
        const bt = b.last_activity_at ?? b.created_at ?? "";
        if (at === bt) return a.slug.localeCompare(b.slug);
        return bt.localeCompare(at);
      });
      break;
    case "score":
      out.sort((a, b) => {
        const av = a.eval_score ?? -1;
        const bv = b.eval_score ?? -1;
        if (av === bv) return a.slug.localeCompare(b.slug);
        return bv - av;
      });
      break;
    case "status":
      out.sort((a, b) => {
        const ar = STATUS_RANK[a.status] ?? 99;
        const br = STATUS_RANK[b.status] ?? 99;
        if (ar === br) return a.slug.localeCompare(b.slug);
        return ar - br;
      });
      break;
    case "slug":
      out.sort((a, b) => a.slug.localeCompare(b.slug));
      break;
  }
  return out;
}
