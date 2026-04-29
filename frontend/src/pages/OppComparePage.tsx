import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, ChevronLeft } from "lucide-react";

import { getOppCompare } from "../api/opps";
import type { OppCompare, OppCompareSummary } from "../api/types";
import { CompareTable } from "../components/opps/CompareTable";
import { ErrorState, LoadingSpinner } from "../components/opps/LoadingStates";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; payload: OppCompare };

export default function OppComparePage() {
  const { slugA, slugB, workspaceSlug } = useParams<{
    slugA: string;
    slugB: string;
    workspaceSlug: string;
  }>();
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    if (!slugA || !slugB) return;
    setState({ kind: "loading" });
    getOppCompare(slugA, slugB)
      .then((payload) => setState({ kind: "loaded", payload }))
      .catch((err) =>
        setState({ kind: "error", message: String(err?.message ?? err) }),
      );
  }, [slugA, slugB]);

  const wsBase = workspaceSlug ? `/w/${workspaceSlug}` : "";

  if (state.kind === "loading") return <LoadingSpinner label="Loading comparison…" />;
  if (state.kind === "error")
    return (
      <ErrorState
        message={state.message}
        onRetry={() => {
          if (!slugA || !slugB) return;
          setState({ kind: "loading" });
          getOppCompare(slugA, slugB)
            .then((payload) => setState({ kind: "loaded", payload }))
            .catch((err) =>
              setState({ kind: "error", message: String(err?.message ?? err) }),
            );
        }}
      />
    );

  const { a, b, summary } = state.payload;

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-border bg-card px-6 py-4">
        <Link
          to={`${wsBase}/opps`}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" />
          All opportunities
        </Link>
        <h1 className="text-xl font-semibold text-foreground">Compare</h1>
        <Link
          to={`${wsBase}/opps/${a.opp.slug}`}
          className="rounded bg-muted px-2 py-0.5 font-mono text-xs text-foreground hover:bg-muted/70"
        >
          {a.opp.slug}
        </Link>
        <ArrowRight className="h-4 w-4 text-muted-foreground" />
        <Link
          to={`${wsBase}/opps/${b.opp.slug}`}
          className="rounded bg-muted px-2 py-0.5 font-mono text-xs text-foreground hover:bg-muted/70"
        >
          {b.opp.slug}
        </Link>
      </header>

      <div className="overflow-y-auto">
        <CompareSummaryBanner summary={summary} aSlug={a.opp.slug} bSlug={b.opp.slug} />
        <CompareTable a={a} b={b} />
      </div>
    </div>
  );
}

function CompareSummaryBanner({
  summary,
  aSlug,
  bSlug,
}: {
  summary: OppCompareSummary;
  aSlug: string;
  bSlug: string;
}) {
  const headline = buildHeadline(summary, aSlug, bSlug);
  const tone = headlineTone(summary);

  return (
    <div className={`border-b border-border px-6 py-5 ${tone.bg}`}>
      <h2 className={`text-base font-semibold ${tone.fg}`}>{headline}</h2>
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
        <ScoreCard
          label={aSlug}
          score={summary.score_a}
          passed={summary.passed_a}
          pending={summary.pending_gates_a}
        />
        <DeltaCard summary={summary} />
        <ScoreCard
          label={bSlug}
          score={summary.score_b}
          passed={summary.passed_b}
          pending={summary.pending_gates_b}
        />
      </div>
    </div>
  );
}

function buildHeadline(
  summary: OppCompareSummary,
  _aSlug: string,
  bSlug: string,
): string {
  const parts: string[] = [];

  if (summary.score_delta != null) {
    if (Math.abs(summary.score_delta) < 0.05) {
      parts.push("opp-eval score is unchanged");
    } else if (summary.score_delta > 0) {
      parts.push(
        `${bSlug} improved by +${summary.score_delta.toFixed(0)} (${formatScore(
          summary.score_a,
        )} → ${formatScore(summary.score_b)})`,
      );
    } else {
      parts.push(
        `${bSlug} regressed by ${summary.score_delta.toFixed(0)} (${formatScore(
          summary.score_a,
        )} → ${formatScore(summary.score_b)})`,
      );
    }
  } else if (summary.score_a != null || summary.score_b != null) {
    parts.push("opp-eval score available on only one opp");
  } else {
    parts.push("Neither opp has been judged by opp-eval yet");
  }

  if (summary.pending_gates_delta < 0) {
    parts.push(
      `${Math.abs(summary.pending_gates_delta)} fewer pending gate${
        Math.abs(summary.pending_gates_delta) === 1 ? "" : "s"
      }`,
    );
  } else if (summary.pending_gates_delta > 0) {
    parts.push(
      `${summary.pending_gates_delta} more pending gate${
        summary.pending_gates_delta === 1 ? "" : "s"
      }`,
    );
  }

  return parts.join(" · ");
}

function headlineTone(summary: OppCompareSummary): { fg: string; bg: string } {
  // Bias by score_delta first, fall back to pending_gates_delta.
  if (summary.score_delta != null && summary.score_delta > 0.05) {
    return { fg: "text-emerald-200", bg: "bg-emerald-950/30" };
  }
  if (summary.score_delta != null && summary.score_delta < -0.05) {
    return { fg: "text-red-200", bg: "bg-red-950/30" };
  }
  if (summary.pending_gates_delta < 0) {
    return { fg: "text-emerald-200", bg: "bg-emerald-950/30" };
  }
  if (summary.pending_gates_delta > 0) {
    return { fg: "text-amber-200", bg: "bg-amber-950/30" };
  }
  return { fg: "text-foreground", bg: "bg-muted/30" };
}

function ScoreCard({
  label,
  score,
  passed,
  pending,
}: {
  label: string;
  score: number | null;
  passed: boolean | null;
  pending: number;
}) {
  return (
    <div className="rounded border border-border bg-card p-3">
      <div className="truncate font-mono text-xs text-muted-foreground">{label}</div>
      <div className="mt-1.5 flex items-baseline gap-2">
        <span className="text-2xl font-semibold text-foreground">
          {score == null ? "—" : formatScore(score)}
        </span>
        <span
          className={
            "text-xs font-medium " +
            (passed === true
              ? "text-emerald-300"
              : passed === false
                ? "text-red-300"
                : "text-muted-foreground")
          }
        >
          {passed === true ? "passed" : passed === false ? "failed" : "unscored"}
        </span>
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        {pending > 0
          ? `${pending} pending gate${pending === 1 ? "" : "s"}`
          : "no pending gates"}
      </div>
    </div>
  );
}

function DeltaCard({ summary }: { summary: OppCompareSummary }) {
  const sd = summary.score_delta;
  const gd = summary.pending_gates_delta;
  return (
    <div className="rounded border border-border bg-muted/30 p-3 text-center">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Delta
      </div>
      <div className="mt-1.5 text-2xl font-semibold">
        {sd == null ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <span
            className={
              sd > 0.05
                ? "text-emerald-300"
                : sd < -0.05
                  ? "text-red-300"
                  : "text-foreground"
            }
          >
            {sd > 0.05 ? "+" : ""}
            {sd.toFixed(0)}
          </span>
        )}
      </div>
      <div className="text-xs text-muted-foreground">
        {gd === 0
          ? "same gate count"
          : `${gd > 0 ? "+" : ""}${gd} gate${Math.abs(gd) === 1 ? "" : "s"}`}
      </div>
    </div>
  );
}

function formatScore(s: number | null): string {
  if (s == null) return "—";
  return s > 10 ? `${s.toFixed(0)}/100` : `${s.toFixed(1)}/10`;
}
