import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { getMultiRunSummary } from "@/api/opps";
import type { MultiRunSummary, PerRunSummary } from "@/api/types";

interface Props {
  oppSlug: string;
  workspaceSlug: string;
}

/**
 * Run-vs-prior-run diff: pick the latest two runs and show
 * per-skill score deltas, gates that landed, and a one-line headline.
 *
 * Built for the "I iterated on the plugin, did anything actually
 * improve?" workflow. Defaults to (newest, second-newest) but lets
 * the user pick any two.
 */
export function RunDiffView({ oppSlug, workspaceSlug }: Props) {
  const [data, setData] = useState<MultiRunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aId, setAId] = useState<string | null>(null);
  const [bId, setBId] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    getMultiRunSummary(oppSlug, { limit: 10 })
      .then((d) => {
        setData(d);
        if (d.per_run.length >= 2) {
          setAId(d.per_run[0].run_id);
          setBId(d.per_run[1].run_id);
        }
      })
      .catch((e) => setError(String(e?.message ?? e)));
  }, [oppSlug]);

  const a = useMemo(
    () => data?.per_run.find((r) => r.run_id === aId),
    [data, aId],
  );
  const b = useMemo(
    () => data?.per_run.find((r) => r.run_id === bId),
    [data, bId],
  );

  if (error)
    return (
      <div className="p-6 text-sm text-destructive">
        Couldn't load diff: {error}
      </div>
    );
  if (!data)
    return <div className="p-6 text-sm text-muted-foreground">Loading…</div>;
  if (data.per_run.length < 2) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Need at least two runs to compute a diff. This opp has{" "}
        {data.per_run.length}.
      </div>
    );
  }
  if (!a || !b) return null;

  const rows = data.skill_index
    .map((s) => {
      const aScore = a.skill_scores[s.skill_name];
      const bScore = b.skill_scores[s.skill_name];
      const aStatus = a.skill_status[s.skill_name];
      const bStatus = b.skill_status[s.skill_name];
      let delta: number | null = null;
      if (
        aScore !== null && aScore !== undefined &&
        bScore !== null && bScore !== undefined
      ) {
        delta = aScore - bScore;
      }
      return {
        skill: s,
        aScore,
        bScore,
        aStatus,
        bStatus,
        delta,
        statusChanged: aStatus !== bStatus,
      };
    })
    // Surface anything interesting first: status change, big delta,
    // then alphabetical-by-phase.
    .sort((a, b) => {
      const aInteresting =
        a.statusChanged || (a.delta !== null && Math.abs(a.delta) >= 3);
      const bInteresting =
        b.statusChanged || (b.delta !== null && Math.abs(b.delta) >= 3);
      if (aInteresting && !bInteresting) return -1;
      if (!aInteresting && bInteresting) return 1;
      return a.skill.phase_ordinal - b.skill.phase_ordinal ||
        a.skill.ordinal - b.skill.ordinal;
    });

  const interesting = rows.filter(
    (r) =>
      r.statusChanged ||
      (r.delta !== null && Math.abs(r.delta) >= 3),
  );
  const headline = buildHeadline(a, b, interesting.length);

  return (
    <div className="overflow-y-auto px-6 py-4">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <RunPicker
          label="Newer"
          runs={data.per_run}
          value={aId}
          onChange={setAId}
        />
        <span className="text-muted-foreground">vs</span>
        <RunPicker
          label="Older"
          runs={data.per_run}
          value={bId}
          onChange={setBId}
        />
      </div>

      <div className="mb-4 rounded-lg border border-border bg-card p-4">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
          Headline
        </div>
        <div className="mt-1 text-sm text-foreground">{headline}</div>

        <div className="mt-3 grid grid-cols-3 gap-3 text-xs">
          <Stat
            label="Mean score Δ"
            a={a.mean_score}
            b={b.mean_score}
            unit="/100"
          />
          <Stat
            label="Skills complete Δ"
            a={a.complete_count}
            b={b.complete_count}
            unit={` / ${a.total_count}`}
          />
          <Stat
            label="Pending gates Δ"
            a={a.gate_pending_count}
            b={b.gate_pending_count}
          />
        </div>
      </div>

      <div className="rounded-lg border border-border">
        <div className="grid grid-cols-[1fr_5rem_5rem_5rem_5rem]
          items-center gap-2 border-b border-border bg-muted/40 px-3 py-2
          text-[10px] uppercase tracking-wider text-muted-foreground">
          <span>Skill</span>
          <span className="text-right">Older</span>
          <span className="text-right">Newer</span>
          <span className="text-right">Δ score</span>
          <span className="text-right">Status</span>
        </div>
        <ul className="divide-y divide-border">
          {rows.map((r) => (
            <li
              key={r.skill.skill_name}
              className="grid grid-cols-[1fr_5rem_5rem_5rem_5rem]
                items-center gap-2 px-3 py-1.5 text-xs hover:bg-accent/30"
            >
              <button
                type="button"
                onClick={() =>
                  navigate(
                    `/w/${workspaceSlug}/opps/${oppSlug}/runs/${a.run_id}/steps/${r.skill.skill_name}`,
                  )
                }
                className="truncate text-left text-foreground hover:underline"
                title={r.skill.skill_name}
              >
                <span className="text-[10px] text-muted-foreground">
                  P{r.skill.phase_ordinal} ·
                </span>{" "}
                {r.skill.display_name}
              </button>
              <span className="text-right tabular-nums text-muted-foreground">
                {fmtScore(r.bScore)}
              </span>
              <span className="text-right tabular-nums text-foreground">
                {fmtScore(r.aScore)}
              </span>
              <DeltaCell delta={r.delta} />
              <StatusCell
                older={r.bStatus}
                newer={r.aStatus}
                changed={r.statusChanged}
              />
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function RunPicker({
  label,
  runs,
  value,
  onChange,
}: {
  label: string;
  runs: PerRunSummary[];
  value: string | null;
  onChange: (id: string) => void;
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs">
      <span className="uppercase tracking-wide text-[10px] text-muted-foreground">
        {label}
      </span>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-input bg-card px-2 py-1 text-xs"
      >
        {runs.map((r) => (
          <option key={r.run_id} value={r.run_id}>
            {r.run_id}
          </option>
        ))}
      </select>
    </label>
  );
}

function Stat({
  label,
  a,
  b,
  unit = "",
}: {
  label: string;
  a: number | null;
  b: number | null;
  unit?: string;
}) {
  const delta = a !== null && b !== null ? a - b : null;
  const tone =
    delta === null
      ? "text-muted-foreground"
      : delta > 0
        ? "text-emerald-500"
        : delta < 0
          ? "text-rose-500"
          : "text-muted-foreground";
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className={`text-base font-medium tabular-nums ${tone}`}>
        {delta === null
          ? "—"
          : delta > 0
            ? `+${formatNum(delta)}`
            : delta < 0
              ? `${formatNum(delta)}`
              : "±0"}
        <span className="ml-1 text-[10px] font-normal text-muted-foreground">
          {unit}
        </span>
      </div>
      <div className="text-[10px] text-muted-foreground/80">
        {b !== null ? formatNum(b) : "—"} → {a !== null ? formatNum(a) : "—"}
      </div>
    </div>
  );
}

function DeltaCell({ delta }: { delta: number | null }) {
  if (delta === null)
    return <span className="text-right text-muted-foreground/40">—</span>;
  if (Math.abs(delta) < 0.5)
    return (
      <span className="flex items-center justify-end gap-1 text-muted-foreground">
        <Minus className="h-3 w-3" />
      </span>
    );
  if (delta > 0)
    return (
      <span className="flex items-center justify-end gap-1 text-emerald-500">
        <ArrowUpRight className="h-3 w-3" />
        +{Math.round(delta)}
      </span>
    );
  return (
    <span className="flex items-center justify-end gap-1 text-rose-500">
      <ArrowDownRight className="h-3 w-3" />
      {Math.round(delta)}
    </span>
  );
}

function StatusCell({
  older,
  newer,
  changed,
}: {
  older: string | undefined;
  newer: string | undefined;
  changed: boolean;
}) {
  if (!changed)
    return (
      <span className="text-right text-muted-foreground/40">{newer ?? "—"}</span>
    );
  return (
    <span className="text-right text-foreground">
      <span className="text-muted-foreground">{older ?? "—"}</span>
      <span className="mx-0.5 text-muted-foreground">→</span>
      {newer ?? "—"}
    </span>
  );
}

function fmtScore(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return String(Math.round(v));
}

function formatNum(v: number): string {
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(1);
}

function buildHeadline(
  a: PerRunSummary,
  b: PerRunSummary,
  interestingCount: number,
): string {
  const meanDelta =
    a.mean_score !== null && b.mean_score !== null
      ? a.mean_score - b.mean_score
      : null;
  if (meanDelta === null) {
    return `Run ${a.run_id} added ${interestingCount} change${interestingCount === 1 ? "" : "s"} vs ${b.run_id}.`;
  }
  if (Math.abs(meanDelta) < 0.5) {
    return `Run ${a.run_id} ≈ ${b.run_id}; ${interestingCount} skill${interestingCount === 1 ? "" : "s"} changed materially.`;
  }
  const direction = meanDelta > 0 ? "improved" : "regressed";
  return `Run ${a.run_id} ${direction} mean score by ${Math.abs(Math.round(meanDelta))} vs ${b.run_id} (${interestingCount} skill${interestingCount === 1 ? "" : "s"} moved).`;
}
