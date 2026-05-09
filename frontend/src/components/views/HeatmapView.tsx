import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { getMultiRunSummary } from "@/api/opps";
import type { MultiRunSummary } from "@/api/types";

interface Props {
  oppSlug: string;
  workspaceSlug: string;
}

/**
 * Skill × run heatmap. One row per skill (grouped by phase, in
 * lifecycle order), one column per run (newest on the right). Each
 * cell colored by judge score; click to drill into the step detail
 * for that (skill, run) pair.
 *
 * The single grid that tells the multi-run improvement-loop story
 * — green band trending up = "we're getting better at OCS"; red
 * vertical strip = "this run regressed broadly".
 */
export function HeatmapView({ oppSlug, workspaceSlug }: Props) {
  const [data, setData] = useState<MultiRunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    getMultiRunSummary(oppSlug, { limit: 10 })
      .then(setData)
      .catch((e) => setError(String(e?.message ?? e)));
  }, [oppSlug]);

  // Newest run rightmost — easier to read "improvement over time".
  const orderedRuns = useMemo(
    () => (data ? [...data.per_run].reverse() : []),
    [data],
  );

  const skillsByPhase = useMemo(() => {
    if (!data) return [];
    const phaseMap = new Map<
      string,
      {
        name: string;
        display: string;
        ordinal: number;
        skills: typeof data.skill_index;
      }
    >();
    for (const s of data.skill_index) {
      const existing = phaseMap.get(s.phase);
      if (existing) {
        existing.skills.push(s);
      } else {
        phaseMap.set(s.phase, {
          name: s.phase,
          display: s.phase_display,
          ordinal: s.phase_ordinal,
          skills: [s],
        });
      }
    }
    return Array.from(phaseMap.values()).sort((a, b) => a.ordinal - b.ordinal);
  }, [data]);

  if (error) {
    return (
      <div className="p-6 text-sm text-destructive">
        Couldn't load heatmap: {error}
      </div>
    );
  }
  if (!data) {
    return <div className="p-6 text-sm text-muted-foreground">Loading…</div>;
  }
  if (orderedRuns.length === 0) {
    return (
      <div className="p-6 text-sm text-muted-foreground">No runs yet.</div>
    );
  }

  return (
    <div className="overflow-auto px-4 py-4">
      <table className="border-separate border-spacing-y-0.5 text-xs">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-background pr-2 text-left font-normal" />
            {orderedRuns.map((r) => (
              <th
                key={r.run_id}
                className="px-1 pb-1 text-center font-normal text-[10px] text-muted-foreground"
                title={r.run_id}
              >
                {formatRunId(r.run_id)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {skillsByPhase.map((phase) => (
            <>
              <tr key={`hdr:${phase.name}`}>
                <td
                  colSpan={orderedRuns.length + 1}
                  className="sticky left-0 z-10 bg-background pt-3
                    text-[10px] uppercase tracking-wider text-muted-foreground"
                >
                  Phase {phase.ordinal} · {phase.display}
                </td>
              </tr>
              {phase.skills.map((s) => (
                <tr key={s.skill_name}>
                  <td
                    className="sticky left-0 z-10 bg-background pr-3
                      text-foreground"
                    title={s.skill_name}
                  >
                    <span className="block max-w-[16rem] truncate">
                      {s.display_name}
                    </span>
                  </td>
                  {orderedRuns.map((r) => {
                    const score = r.skill_scores[s.skill_name];
                    const status = r.skill_status[s.skill_name];
                    const passed = r.skill_passed[s.skill_name];
                    return (
                      <td key={r.run_id} className="px-0.5">
                        <button
                          type="button"
                          onClick={() =>
                            navigate(
                              `/w/${workspaceSlug}/opps/${oppSlug}/runs/${r.run_id}/steps/${s.skill_name}`,
                            )
                          }
                          title={cellTitle(score, status, passed)}
                          style={{
                            background: cellBg(score, status, passed),
                          }}
                          className="block h-6 w-12 rounded-sm
                            text-center text-[10px] font-medium
                            text-foreground/90 hover:ring-2
                            hover:ring-primary"
                        >
                          {cellLabel(score, status)}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </>
          ))}
        </tbody>
      </table>

      <Legend />
    </div>
  );
}

function cellBg(
  score: number | null | undefined,
  status: string | undefined,
  passed: boolean | null | undefined,
): string {
  // Empty / never-ran: very dim.
  if (status === undefined || status === "pending") return "rgba(120,120,120,0.08)";
  if (status === "skipped") return "rgba(120,120,120,0.05)";
  if (passed === false || status === "judge-fail") {
    return "rgba(244,63,94,0.55)"; // rose-500 @ alpha
  }
  if (score === null || score === undefined) {
    return "rgba(120,120,120,0.18)";
  }
  // Linear interp green → amber → green. Keep simple: bucket.
  if (score >= 90) return "rgba(34,197,94,0.6)"; // green-500
  if (score >= 75) return "rgba(132,204,22,0.45)"; // lime
  if (score >= 60) return "rgba(245,158,11,0.45)"; // amber
  return "rgba(244,63,94,0.45)"; // rose
}

function cellLabel(
  score: number | null | undefined,
  status: string | undefined,
): string {
  if (score !== null && score !== undefined) return String(Math.round(score));
  if (status === "complete") return "✓";
  if (status === "judge-fail") return "✗";
  return "·";
}

function cellTitle(
  score: number | null | undefined,
  status: string | undefined,
  passed: boolean | null | undefined,
): string {
  const s = score !== null && score !== undefined ? `${Math.round(score)}/100` : "no score";
  const p = passed === true ? "passed" : passed === false ? "failed" : "—";
  return `${status ?? "?"} · ${s} · ${p}`;
}

function formatRunId(runId: string): string {
  const m = runId.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})$/);
  if (!m) return runId;
  return `${m[2]}/${m[3]} ${m[4]}:${m[5]}`;
}

function Legend() {
  return (
    <div className="mt-3 flex items-center gap-3 text-[10px] text-muted-foreground">
      <span>Score:</span>
      {[
        { label: "≥90", bg: "rgba(34,197,94,0.6)" },
        { label: "75-89", bg: "rgba(132,204,22,0.45)" },
        { label: "60-74", bg: "rgba(245,158,11,0.45)" },
        { label: "<60", bg: "rgba(244,63,94,0.45)" },
        { label: "fail", bg: "rgba(244,63,94,0.55)" },
        { label: "didn't run", bg: "rgba(120,120,120,0.08)" },
      ].map((s) => (
        <span key={s.label} className="flex items-center gap-1">
          <span
            className="inline-block h-3 w-4 rounded-sm"
            style={{ background: s.bg }}
          />
          {s.label}
        </span>
      ))}
    </div>
  );
}
