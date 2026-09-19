/**
 * What the later run did differently — two runs of one opp, compared.
 *
 * Leads with what is NEW (decisions it made, checks it ran, answers that
 * moved) and keeps the per-step verdicts in a plain table further down.
 * Scores alone tell the wrong story: after an outside review ACE's graders got
 * stricter, so the better run passed fewer of its own checks. See
 * apps/opps/run_compare.py.
 *
 * Says WHAT changed, never WHY — between two runs ACE changes for many
 * reasons at once, and the run data doesn't record which caused which.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import {
  type CompareDecision,
  type CompareStep,
  type RunCompare,
  type RunHeader,
  fetchRunCompare,
} from "@/api/runCompare";
import { ErrorState, LoadingSpinner } from "@/components/opps/LoadingStates";

export default function RunComparePage() {
  const { workspaceSlug = "", slug = "" } = useParams();
  const [params] = useSearchParams();
  const base = params.get("base") ?? "";
  const head = params.get("head") ?? "";
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "loaded"; data: RunCompare }
    | { kind: "error"; message: string }
  >({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    fetchRunCompare(workspaceSlug, slug, base, head)
      .then((data) => !cancelled && setState({ kind: "loaded", data }))
      .catch(
        (e: unknown) =>
          !cancelled &&
          setState({ kind: "error", message: e instanceof Error ? e.message : String(e) }),
      );
    return () => {
      cancelled = true;
    };
  }, [workspaceSlug, slug, base, head]);

  const back = `/w/${workspaceSlug}/opps/${encodeURIComponent(slug)}?view=runs`;

  return (
    <div className="mx-auto max-w-5xl px-6 py-6">
      <Link
        to={back}
        className="mb-4 inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" /> Runs
      </Link>

      {state.kind === "loading" && <LoadingSpinner label="Comparing runs…" />}
      {state.kind === "error" && <ErrorState message={state.message} code={null} />}
      {state.kind === "loaded" && <Comparison data={state.data} />}
    </div>
  );
}

function Comparison({ data }: { data: RunCompare }) {
  return (
    <>
      <header className="mb-6">
        <h1 className="text-xl font-semibold text-foreground">
          What the later run did differently
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {data.opp_title ?? data.opp_slug}: <RunLabel run={data.base} /> compared with{" "}
          <RunLabel run={data.head} />.
        </p>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <Stat
            href="#new-decisions"
            n={data.new_decisions.length}
            label="new decisions"
            note="Questions the later run settled that the earlier never raised."
          />
          <Stat
            href="#changed-decisions"
            n={data.changed_decisions.length}
            label="answered differently"
            note="Same question, a different answer."
          />
          <Stat
            href="#new-checks"
            n={data.new_steps.length}
            label="new checks"
            note="Steps the later run ran that the earlier did not."
          />
        </div>
      </header>

      <Section
        id="new-decisions"
        title="Decisions it made that the earlier run didn't"
        empty="The later run made no decisions the earlier one hadn't."
        count={data.new_decisions.length}
      >
        <ByPhase rows={data.new_decisions}>
          {(d) => (
            <li key={d.id} className="py-2">
              <div className="text-sm text-foreground">{d.question}</div>
              <div className="mt-0.5 text-sm text-muted-foreground">{text(d.answer)}</div>
            </li>
          )}
        </ByPhase>
      </Section>

      <Section
        id="changed-decisions"
        title="Answered differently"
        empty="Every decision both runs made was answered the same way."
        count={data.changed_decisions.length}
      >
        <ByPhase rows={data.changed_decisions}>
          {(d) => (
            <li key={d.id} className="py-2">
              <div className="text-sm text-foreground">{d.question}</div>
              <div className="mt-1 grid gap-1 text-sm sm:grid-cols-2 sm:gap-4">
                <div>
                  <span className="text-xs text-muted-foreground">Earlier run </span>
                  <div className="text-muted-foreground line-through decoration-muted-foreground/50">
                    {text(d.before)}
                  </div>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">Later run </span>
                  <div className="text-foreground">{text(d.after)}</div>
                </div>
              </div>
            </li>
          )}
        </ByPhase>
      </Section>

      <Section
        id="new-checks"
        title="New checks it ran"
        empty="The later run ran no steps the earlier one didn't."
        count={data.new_steps.length}
      >
        <StepList steps={data.new_steps} />
      </Section>

      {(data.dropped_decisions.length > 0 || data.dropped_steps.length > 0) && (
        <details className="mt-8 border-t pt-4">
          <summary className="cursor-pointer text-sm font-medium text-foreground">
            No longer in the later run ({data.dropped_decisions.length + data.dropped_steps.length})
          </summary>
          <div className="mt-3 space-y-4">
            {data.dropped_steps.length > 0 && <StepList steps={data.dropped_steps} />}
            {data.dropped_decisions.length > 0 && (
              <ul className="divide-y">
                {data.dropped_decisions.map((d) => (
                  <li key={d.id} className="py-2 text-sm text-muted-foreground">
                    {d.question}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </details>
      )}

      <details className="mt-8 border-t pt-4">
        <summary className="cursor-pointer text-sm font-medium text-foreground">
          Every step, side by side ({data.steps.length})
        </summary>
        <p className="mt-2 max-w-[70ch] text-xs text-muted-foreground">
          Each run&rsquo;s own review, as it reported it. Reviews can get stricter between
          runs, so a lower verdict isn&rsquo;t on its own a sign of worse work.
        </p>
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-1.5 font-normal">Step</th>
              <th className="py-1.5 font-normal">Earlier run</th>
              <th className="py-1.5 font-normal">Later run</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {data.steps.map((r) => (
              <tr key={r.skill} className={r.changed ? "" : "text-muted-foreground"}>
                <td className="py-1.5 pr-4">
                  <div className={r.changed ? "text-foreground" : undefined}>
                    {r.display_name}
                  </div>
                  <div className="text-xs text-muted-foreground">{r.phase_display}</div>
                </td>
                <td className="py-1.5 pr-4">{r.base?.label ?? "—"}</td>
                <td className="py-1.5">{r.head?.label ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </>
  );
}

function RunLabel({ run }: { run: RunHeader }) {
  return <span className="font-mono text-foreground">{run.run_id}</span>;
}

function Stat({
  href,
  n,
  label,
  note,
}: {
  href: string;
  n: number;
  label: string;
  note: string;
}) {
  return (
    <a href={href} className="rounded-md border bg-card px-3 py-2.5 hover:bg-accent">
      <div className="text-2xl font-semibold leading-none text-foreground">{n}</div>
      <div className="mt-1 text-sm font-medium text-foreground">{label}</div>
      <div className="mt-0.5 text-xs text-muted-foreground">{note}</div>
    </a>
  );
}

function Section({
  id,
  title,
  empty,
  count,
  children,
}: {
  id: string;
  title: string;
  empty: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="mt-8 scroll-mt-4 border-t pt-4">
      <h2 className="text-base font-semibold text-foreground">
        {title} <span className="font-normal text-muted-foreground">({count})</span>
      </h2>
      {count === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">{empty}</p>
      ) : (
        <div className="mt-2">{children}</div>
      )}
    </section>
  );
}

/** Rows grouped under their phase, in phase order (the backend sorts them). */
function ByPhase({
  rows,
  children,
}: {
  rows: readonly CompareDecision[];
  children: (d: CompareDecision) => React.ReactNode;
}) {
  const groups = useMemo(() => {
    const out: { phase: string; label: string; rows: CompareDecision[] }[] = [];
    for (const d of rows) {
      const last = out.at(-1);
      if (last && last.phase === d.phase) last.rows.push(d);
      else out.push({ phase: d.phase, label: d.phase_display || d.phase, rows: [d] });
    }
    return out;
  }, [rows]);
  return (
    <div className="space-y-4">
      {groups.map((g) => (
        <div key={g.phase}>
          <div className="text-xs font-medium text-muted-foreground">{g.label}</div>
          <ul className="divide-y">{g.rows.map(children)}</ul>
        </div>
      ))}
    </div>
  );
}

function StepList({ steps }: { steps: readonly CompareStep[] }) {
  return (
    <ul className="divide-y">
      {steps.map((s) => (
        <li key={s.skill} className="flex items-baseline justify-between gap-4 py-2 text-sm">
          <span className="text-foreground">{s.display_name}</span>
          <span className="shrink-0 text-xs text-muted-foreground">{s.phase_display}</span>
        </li>
      ))}
    </ul>
  );
}

function text(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  return typeof v === "string" ? v : JSON.stringify(v);
}
