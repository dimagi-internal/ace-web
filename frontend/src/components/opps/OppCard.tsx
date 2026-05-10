import { ChevronDown, ChevronRight, GitCompareArrows, Trash2 } from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { OppCard as OppCardData } from "../../api/types";
import { OppCardRunsStrip } from "../views/hierarchy/OppCardRunsStrip";
import { OppChatChildren } from "../views/hierarchy/OppChatChildren";
import { OppRunsList } from "../views/hierarchy/OppRunsList";
import { relativeTime } from "../../lib/relativeTime";

interface OppCardProps {
  opp: OppCardData;
  workspaceSlug: string;
  isExpanded: boolean;
  tagFilter: string[];
  canCompare: boolean;
  onToggleExpanded: (slug: string) => void;
  onToggleTag: (tag: string) => void;
  onRequestDelete: (opp: OppCardData) => void;
  onRequestCompare: (opp: OppCardData) => void;
}

/**
 * One card in the Opps grid. Renders metadata, status pill, score chip,
 * runs strip, tags / labels, and (when expanded) the linked-runs and
 * linked-chats panels. Card-level click navigates to the workbench;
 * inner buttons stop propagation so a click on a chevron / trash / tag
 * doesn't double-fire navigation.
 */
export function OppCardItem({
  opp,
  workspaceSlug,
  isExpanded,
  tagFilter,
  canCompare,
  onToggleExpanded,
  onToggleTag,
  onRequestDelete,
  onRequestCompare,
}: OppCardProps) {
  const navigate = useNavigate();
  const goToWorkbench = () => navigate(`/opps/${opp.slug}`);
  const scorePct = opp.eval_score_pct ?? toPct(opp.eval_score);

  return (
    <div
      className="group overflow-hidden rounded border border-border bg-card transition hover:border-primary"
      role="button"
      tabIndex={0}
      onClick={(e) => {
        // Card-level click navigates. Buttons / links inside call
        // stopPropagation so they don't trigger this. We use a div +
        // onClick (not <Link> wrapping) because nesting <button>
        // inside <a> is invalid HTML and browsers handle the click
        // ambiguously — clicking a chevron could fire either the
        // button or the anchor first, which manifested as "I clicked
        // leep's chevron but turmeric expanded."
        if ((e.target as HTMLElement).closest("button, a")) return;
        goToWorkbench();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          if ((e.target as HTMLElement).closest("button, a")) return;
          e.preventDefault();
          goToWorkbench();
        }
      }}
    >
      <div className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 items-start gap-1.5">
            <button
              type="button"
              aria-label={
                isExpanded
                  ? `Collapse ${opp.slug} chats`
                  : `Show chats linked to ${opp.slug}`
              }
              title={isExpanded ? "Hide linked chats" : "Show linked chats"}
              onClick={(e) => {
                e.stopPropagation();
                onToggleExpanded(opp.slug);
              }}
              className="-ml-1 mt-0.5 shrink-0 rounded p-1.5 text-muted-foreground transition hover:bg-muted hover:text-foreground"
            >
              {isExpanded ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
            </button>
            <div className="min-w-0">
              <h2
                className="truncate font-semibold text-foreground group-hover:text-primary"
                title={
                  opp.created_at
                    ? `${opp.display_name || opp.slug}\nCreated ${new Date(opp.created_at).toLocaleString()}${opp.created_by ? " by " + opp.created_by : ""}`
                    : opp.display_name || opp.slug
                }
              >
                {opp.display_name || opp.slug}
              </h2>
              <div
                className="truncate text-xs text-muted-foreground"
                title={opp.slug}
              >
                {opp.slug}
              </div>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {/* Trash sits LEFT of compare so the destructive action
                isn't the easy mis-click target at the row's right
                edge. */}
            <button
              type="button"
              aria-label={`Delete ${opp.slug}`}
              title="Delete this opp"
              onClick={(e) => {
                e.stopPropagation();
                onRequestDelete(opp);
              }}
              className="rounded p-1 text-muted-foreground/40 transition hover:bg-destructive/10 hover:text-destructive group-hover:text-muted-foreground/80"
            >
              <Trash2 className="h-4 w-4" />
            </button>
            <button
              type="button"
              aria-label={`Compare ${opp.slug} with another opp`}
              title={
                canCompare
                  ? "Compare with another opp"
                  : "Compare requires at least 2 opps"
              }
              onClick={(e) => {
                e.stopPropagation();
                onRequestCompare(opp);
              }}
              disabled={!canCompare}
              className="rounded p-1 text-muted-foreground/40 transition hover:bg-primary/10 hover:text-primary group-hover:text-muted-foreground/80 disabled:cursor-not-allowed disabled:opacity-30"
            >
              <GitCompareArrows className="h-4 w-4" />
            </button>
            <StatusBadge status={opp.status} />
          </div>
        </div>

        {scorePct !== null && (
          <div className="mt-2">
            <ScoreChip scorePct={scorePct} passed={opp.eval_passed} />
          </div>
        )}

        {opp.current_step ? (
          <div className="mt-3 text-sm">
            <span className="text-muted-foreground">Last step:</span>{" "}
            <span className="text-foreground" title={opp.current_step}>
              {opp.current_step_display || opp.current_step}
            </span>
            {opp.current_phase && (
              <span
                className="ml-2 text-xs text-muted-foreground"
                title={opp.current_phase}
              >
                ({opp.current_phase_display || opp.current_phase})
              </span>
            )}
          </div>
        ) : opp.status === "no-state" ? (
          <div className="mt-3 text-sm text-muted-foreground">
            Cycle hasn't started yet.
          </div>
        ) : null}

        <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
          <span title="Each run is one execution of /ace:run for this opp.">
            {opp.run_count === 1 ? "1 run" : `${opp.run_count} runs`}
          </span>
          {opp.last_activity_at && (
            <>
              <span aria-hidden="true">·</span>
              <span title={new Date(opp.last_activity_at).toLocaleString()}>
                last {relativeTime(opp.last_activity_at)}
              </span>
            </>
          )}
        </div>

        {workspaceSlug && (
          <OppCardRunsStrip
            oppSlug={opp.slug}
            workspaceSlug={workspaceSlug}
          />
        )}

        {(opp.tags.length > 0 || opp.labels.length > 0) && (
          <div className="mt-3 flex flex-wrap gap-1">
            {opp.tags.map((tag) => (
              <button
                key={`tag-${tag}`}
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleTag(tag);
                }}
                className={
                  "rounded-full px-2 py-0.5 text-xs transition " +
                  (tagFilter.includes(tag)
                    ? "bg-primary text-primary-foreground"
                    : "bg-primary/10 text-primary hover:bg-primary/20")
                }
                title={
                  tagFilter.includes(tag)
                    ? "Remove tag filter"
                    : "Filter by this tag"
                }
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
      </div>
      {isExpanded && workspaceSlug && (
        <>
          <OppRunsList oppSlug={opp.slug} workspaceSlug={workspaceSlug} />
          <OppChatChildren oppSlug={opp.slug} workspaceSlug={workspaceSlug} />
        </>
      )}
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
      <span
        className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground"
        title="No state.yaml file in this opp's Drive folder yet"
      >
        Not started yet
      </span>
    );
  }
  if (status === "error") {
    return (
      <span
        className="rounded bg-destructive/20 px-2 py-0.5 text-xs text-destructive"
        title="ace-web couldn't read this opp's Drive folder"
      >
        Couldn't load
      </span>
    );
  }
  return (
    <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
      {status}
    </span>
  );
}

// Local fallback for OppCards from old API payloads that pre-date
// ``eval_score_pct``. Mirrors ``apps/opps/serializers.normalize_score_pct``.
function toPct(score: number | null): number | null {
  if (score === null || score === undefined) return null;
  return score > 10 ? score : score * 10;
}

function ScoreChip({
  scorePct,
  passed,
}: {
  scorePct: number | null;
  passed: boolean | null;
}) {
  if (scorePct === null) return null;
  const tone =
    passed === true
      ? "bg-emerald-900/60 text-emerald-200 border-emerald-700"
      : passed === false
        ? "bg-red-900/60 text-red-200 border-red-700"
        : "bg-muted text-muted-foreground border-border";
  const glyph = passed === true ? "✓" : passed === false ? "✕" : "·";
  const verb = passed === true ? "passed" : passed === false ? "failed" : "scored";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${tone}`}
      title={`opp-eval ${verb}: ${Math.round(scorePct)}/100`}
    >
      <span aria-hidden="true">{glyph}</span>
      <span>{Math.round(scorePct)}/100</span>
    </span>
  );
}
